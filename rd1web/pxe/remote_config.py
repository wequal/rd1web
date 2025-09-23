"""
Remote connection configuration for PXE services.

This module centralizes all remote server connection configurations
used by both rma_pxe.py and pxe_input.py views.
"""

from fabric import Connection
import asyncio
import threading
import logging

logger = logging.getLogger(__name__)

# Centralized remote connection dictionary
# Contains all remote server connections used across PXE services
remote_dict = {
    # RMA server connection with timeout settings
    'rma': Connection(
        host="root@10.4.4.80", 
        connect_kwargs={
            "password": "superrd1",
            "banner_timeout": 30,  # Banner negotiation timeout
            "auth_timeout": 30  # Authentication timeout
        },
        connect_timeout=30  # Overall connection timeout
    ),
    
    # PXE input location connections
    'us_b3': Connection(
        host="root@172.31.60.129", 
        connect_kwargs={
            "password": "superrd1",
            "banner_timeout": 30,
            "auth_timeout": 30
        },
        connect_timeout=30
    ),
    'us_b1': Connection(
        host="root@172.31.58.142", 
        connect_kwargs={
            "password": "superrd1",
            "banner_timeout": 30,
            "auth_timeout": 30
        },
        connect_timeout=30
    ),
    'tw': Connection(
        host="root@10.135.179.104", 
        connect_kwargs={
            "password": "superrd1",
            "banner_timeout": 30,
            "auth_timeout": 30
        },
        connect_timeout=30
    )
}

class AsyncFabricWrapper:
    """
    Async wrapper for Fabric operations to prevent ASGI event loop blocking
    """
    
    def __init__(self, connection_key):
        self.connection_key = connection_key
        self.connection = remote_dict[connection_key]
    
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
                # Validate connection first
                if not self._validate_connection():
                    self._reconnect()
                
                result = self.connection.run(command, **kwargs)
                return result, True, None
            except Exception as e:
                logger.error(f"Fabric command failed: {command}, Error: {e}")
                return None, False, str(e)
        
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
            return None, False, f"Operation timed out after {timeout} seconds"
        except Exception as e:
            logger.error(f"Async Fabric wrapper error: {e}")
            return None, False, str(e)
    
    def _validate_connection(self):
        """Validate if connection is alive"""
        try:
            # Simple test command with short timeout
            result = self.connection.run('echo "test"', hide=True, warn=True, timeout=5)
            return result.return_code == 0
        except Exception:
            return False
    
    def _reconnect(self):
        """Reconnect if connection is stale"""
        try:
            logger.info(f"Reconnecting to {self.connection_key}")
            # Close existing connection
            if hasattr(self.connection, 'close'):
                self.connection.close()
            
            # Create new connection with same settings
            original_conn = remote_dict[self.connection_key]
            new_conn = Connection(
                host=original_conn.host,
                connect_kwargs=original_conn.connect_kwargs,
                connect_timeout=original_conn.connect_timeout
            )
            
            # Update the global connection
            remote_dict[self.connection_key] = new_conn
            self.connection = new_conn
            
            logger.info(f"Successfully reconnected to {self.connection_key}")
        except Exception as e:
            logger.error(f"Failed to reconnect to {self.connection_key}: {e}")

# Global async wrappers for each connection
async_rma = AsyncFabricWrapper('rma')
async_us_b3 = AsyncFabricWrapper('us_b3')
async_us_b1 = AsyncFabricWrapper('us_b1')
async_tw = AsyncFabricWrapper('tw')
