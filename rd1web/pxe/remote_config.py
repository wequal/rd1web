"""
Remote connection configuration for PXE services.

This module centralizes all remote server connection configurations
used by both rma_pxe.py and pxe_input.py views.

Configuration is loaded from local_config.py which contains location-specific settings.
"""

from fabric import Connection
import asyncio
import threading
import logging

logger = logging.getLogger(__name__)

# Import configuration from local_config
try:
    from .local_config import REMOTE_SERVERS
    logger.info("Successfully loaded REMOTE_SERVERS from local_config.py")
except ImportError:
    # Fallback to default if local_config doesn't exist
    logger.warning("local_config.py not found, using default configuration")
    REMOTE_SERVERS = {
        'rma': {
            'host': 'root@10.4.4.80',
            'password': 'superrd1',
            'timeout': 30,
        },
        'us_b3': {
            'host': 'root@172.31.56.135',
            'password': 'superrd1',
            'timeout': 30,
        },
        'us_b1': {
            'host': 'root@172.31.58.142',
            'password': 'superrd1',
            'timeout': 30,
        },
        'tw': {
            'host': 'root@10.135.179.104',
            'password': 'superrd1',
            'timeout': 30,
        },
    }

# Build remote_dict from configuration
# This creates Fabric Connection objects from the config
remote_dict = {}
for key, config in REMOTE_SERVERS.items():
    remote_dict[key] = Connection(
        host=config['host'],
        connect_kwargs={
            "password": config['password'],
            "banner_timeout": config.get('timeout', 30),
            "auth_timeout": config.get('timeout', 30)
        },
        connect_timeout=config.get('timeout', 30)
    )
    logger.debug(f"Created connection for '{key}': {config['host']}")

class AsyncFabricWrapper:
    """
    Async wrapper for Fabric operations to prevent ASGI event loop blocking
    """
    
    def __init__(self, connection_key):
        self.connection_key = connection_key
        self._last_used = 0
        self._connection_timeout = 300  # 5 minutes before considering connection stale
    
    def _get_fresh_connection(self):
        """Get a fresh connection, creating new one if needed"""
        import time
        
        current_time = time.time()
        
        # Check if connection is too old (stale)
        if current_time - self._last_used > self._connection_timeout:
            logger.info(f"Creating fresh connection for {self.connection_key} (stale connection)")
            self._create_new_connection()
        
        self._last_used = current_time
        return remote_dict[self.connection_key]
    
    def _create_new_connection(self):
        """Create a completely new connection"""
        try:
            # Get original connection settings
            original_conn = remote_dict[self.connection_key]
            
            # Close existing connection if it exists
            try:
                if hasattr(original_conn, 'close'):
                    original_conn.close()
            except:
                pass  # Ignore close errors
            
            # Create fresh connection
            new_conn = Connection(
                host=original_conn.host,
                connect_kwargs=original_conn.connect_kwargs.copy(),
                connect_timeout=original_conn.connect_timeout
            )
            
            # Update the global connection
            remote_dict[self.connection_key] = new_conn
            logger.info(f"Created fresh connection for {self.connection_key}")
            
        except Exception as e:
            logger.error(f"Failed to create fresh connection for {self.connection_key}: {e}")
            raise
    
    async def run_async(self, command, timeout=30, **kwargs):
        """
        Run a Fabric command asynchronously to prevent blocking ASGI event loop
        
        Args:
            command (str): Command to execute
            timeout (int): Timeout in seconds
            **kwargs: Additional arguments for Fabric run()
            
        Returns:
            tuple: (result, success, error_message)
        """
        def run_in_thread():
            try:
                # Get a fresh connection
                connection = self._get_fresh_connection()
                
                # Add timeout to kwargs if not already specified
                if 'timeout' not in kwargs:
                    kwargs['timeout'] = max(5, timeout - 5)  # Leave 5 seconds buffer for async timeout, minimum 5s
                
                result = connection.run(command, **kwargs)
                return result, True, None
                
            except Exception as e:
                logger.error(f"Fabric command failed: {command}, Error: {e}")
                
                # Try once more with a completely fresh connection
                try:
                    logger.info(f"Retrying {command} with fresh connection")
                    self._create_new_connection()
                    connection = self._get_fresh_connection()
                    
                    result = connection.run(command, **kwargs)
                    return result, True, None
                except Exception as retry_error:
                    logger.error(f"Fabric command retry failed: {command}, Error: {retry_error}")
                    return None, False, str(retry_error)
        
        try:
            # Run the Fabric operation in a thread pool to avoid blocking
            loop = asyncio.get_event_loop()
            result, success, error = await asyncio.wait_for(
                loop.run_in_executor(None, run_in_thread),
                timeout=timeout
            )
            return result, success, error
        except asyncio.TimeoutError:
            logger.error(f"Fabric command timed out after {timeout}s: {command}")
            # Force connection refresh for next time
            self._last_used = 0
            return None, False, f"Operation timed out after {timeout} seconds"
        except Exception as e:
            logger.error(f"Async Fabric wrapper error: {e}")
            return None, False, str(e)

# Global async wrappers for each connection
async_rma = AsyncFabricWrapper('rma')
async_us_b3 = AsyncFabricWrapper('us_b3')
async_us_b1 = AsyncFabricWrapper('us_b1')
async_tw = AsyncFabricWrapper('tw')
