import subprocess
import threading
import time
import json
import logging
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from .system_details import get_file_content, parse_sysconfig
import os
import uuid

logger = logging.getLogger(__name__)
BASE_DIR = '/srv/log'

# Global dictionary to store active SOL sessions
active_sessions = {}

class SOLSession:
    def __init__(self, folder_name, bmc_config):
        self.folder_name = folder_name
        self.session_id = str(uuid.uuid4())
        self.bmc_config = bmc_config
        self.process = None
        self.output_buffer = []
        self.is_active = False
        self.lock = threading.Lock()
        self.last_output_time = time.time()
        
    def start(self):
        """Start the SOL session"""
        try:
            bmc_ip = self.bmc_config.get('bmc_ip')
            bmc_user = self.bmc_config.get('bmc_user', 'ADMIN')
            bmc_pwd = self.bmc_config.get('bmc_unique_pwd', 'ADMIN')
            
            # First deactivate any existing SOL sessions
            deactivate_cmd = [
                'ipmitool', '-I', 'lanplus', '-C', '3',
                '-H', bmc_ip, '-U', bmc_user, '-P', bmc_pwd,
                'sol', 'deactivate'
            ]
            subprocess.run(deactivate_cmd, capture_output=True, timeout=10)
            
            # Start SOL session
            cmd = [
                'ipmitool', '-I', 'lanplus', '-C', '3',
                '-H', bmc_ip, '-U', bmc_user, '-P', bmc_pwd,
                'sol', 'activate'
            ]
            
            self.process = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=0  # Unbuffered
            )
            
            self.is_active = True
            self.last_output_time = time.time()
            
            # Start output reader thread
            threading.Thread(target=self._read_output, daemon=True).start()
            
            # Add initial messages
            self.add_output(f"SOL session starting for {bmc_ip}...\r\n")
            self.add_output("Connecting to BMC console...\r\n")
            
            logger.info(f"SOL session started for {self.folder_name} (PID: {self.process.pid})")
            return True
            
        except Exception as e:
            logger.error(f"Failed to start SOL session: {e}")
            self.add_output(f"Error starting SOL session: {str(e)}\r\n")
            return False
    
    def _read_output(self):
        """Read output from SOL process in a separate thread"""
        try:
            buffer = ""
            while self.is_active and self.process and self.process.poll() is None:
                try:
                    # Read in small chunks for better performance
                    chunk = self.process.stdout.read(64)
                    if chunk:
                        # Process the chunk to normalize line endings
                        buffer += chunk
                        
                        # Process complete lines or when buffer gets large
                        while '\n' in buffer or len(buffer) > 256:
                            if '\n' in buffer:
                                line, buffer = buffer.split('\n', 1)
                                # Normalize line endings for xterm.js
                                line = line.rstrip('\r') + '\r\n'
                                self.add_output(line)
                            else:
                                # Buffer too large, output as-is
                                self.add_output(buffer)
                                buffer = ""
                        
                        self.last_output_time = time.time()
                    else:
                        time.sleep(0.01)  # Small delay to prevent busy waiting
                except Exception as e:
                    logger.error(f"Error reading SOL output: {e}")
                    break
            
            # Output any remaining buffer
            if buffer:
                self.add_output(buffer)
                    
        except Exception as e:
            logger.error(f"SOL output reader error: {e}")
        finally:
            self.add_output("\r\nSOL session ended\r\n")
            self.is_active = False
    
    def add_output(self, text):
        """Add output to buffer"""
        with self.lock:
            self.output_buffer.append({
                'timestamp': time.time(),
                'data': text
            })
            # Keep only last 2000 entries
            if len(self.output_buffer) > 2000:
                self.output_buffer = self.output_buffer[-2000:]
    
    def get_output_since(self, timestamp):
        """Get output since given timestamp"""
        with self.lock:
            return [item for item in self.output_buffer if item['timestamp'] > timestamp]
    
    def get_all_output(self):
        """Get all buffered output"""
        with self.lock:
            return list(self.output_buffer)
    
    def send_input(self, data):
        """Send input to SOL session"""
        try:
            if self.process and self.process.stdin and self.is_active:
                self.process.stdin.write(data)
                self.process.stdin.flush()
                return True
        except Exception as e:
            logger.error(f"Error sending input to SOL: {e}")
        return False
    
    def stop(self):
        """Stop the SOL session"""
        self.is_active = False
        try:
            if self.process:
                # Send SOL escape sequence
                try:
                    self.process.stdin.write('~.')
                    self.process.stdin.flush()
                    time.sleep(0.5)
                except:
                    pass
                
                # Terminate process
                if self.process.poll() is None:
                    self.process.terminate()
                    time.sleep(1)
                    if self.process.poll() is None:
                        self.process.kill()
                        
        except Exception as e:
            logger.error(f"Error stopping SOL session: {e}")

@require_http_methods(["POST"])
@csrf_exempt
def start_sol_session(request, folder_name):
    """Start a new SOL session"""
    try:
        # Get system configuration
        log_dir = os.path.join(BASE_DIR, folder_name)
        if not os.path.exists(log_dir):
            return JsonResponse({
                'success': False,
                'error': f'Log directory not found: {log_dir}'
            })
        
        sysconfig_path = os.path.join(log_dir, 'sysconfig')
        sysconfig_content = get_file_content(sysconfig_path)
        
        if not sysconfig_content:
            return JsonResponse({
                'success': False,
                'error': f'Sysconfig not found: {sysconfig_path}'
            })
        
        sysconfig = parse_sysconfig(sysconfig_content)
        
        if 'bmc_ip' not in sysconfig:
            return JsonResponse({
                'success': False,
                'error': 'BMC IP not found in sysconfig'
            })
        
        # Stop any existing session for this folder
        if folder_name in active_sessions:
            active_sessions[folder_name].stop()
            del active_sessions[folder_name]
        
        # Create new session
        session = SOLSession(folder_name, sysconfig)
        if session.start():
            active_sessions[folder_name] = session
            return JsonResponse({
                'success': True,
                'session_id': session.session_id,
                'message': 'SOL session started'
            })
        else:
            return JsonResponse({
                'success': False,
                'error': 'Failed to start SOL session'
            })
            
    except Exception as e:
        logger.exception(f"Error starting SOL session for {folder_name}")
        return JsonResponse({
            'success': False,
            'error': f'Internal error: {str(e)}'
        })

@require_http_methods(["GET"])
def get_sol_output(request, folder_name):
    """Get SOL output using polling"""
    try:
        if folder_name not in active_sessions:
            return JsonResponse({
                'success': False,
                'error': 'No active SOL session',
                'status': 'not_found'
            })
        
        session = active_sessions[folder_name]
        since_timestamp = float(request.GET.get('since', 0))
        
        if since_timestamp == 0:
            # First request - get all output
            output = session.get_all_output()
        else:
            # Subsequent requests - get new output
            output = session.get_output_since(since_timestamp)
        
        return JsonResponse({
            'success': True,
            'output': output,
            'is_active': session.is_active,
            'current_time': time.time()
        })
        
    except Exception as e:
        logger.error(f"Error getting SOL output: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@require_http_methods(["POST"])
@csrf_exempt
def sol_input(request, folder_name):
    """Send input to SOL session"""
    try:
        if folder_name not in active_sessions:
            return JsonResponse({
                'success': False,
                'error': 'No active SOL session'
            })
        
        data = json.loads(request.body)
        input_text = data.get('input', '')
        
        session = active_sessions[folder_name]
        success = session.send_input(input_text)
        
        return JsonResponse({
            'success': success
        })
        
    except Exception as e:
        logger.error(f"Error sending SOL input: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        })

@require_http_methods(["POST"])
@csrf_exempt
def stop_sol_session(request, folder_name):
    """Stop SOL session"""
    try:
        if folder_name in active_sessions:
            active_sessions[folder_name].stop()
            del active_sessions[folder_name]
        
        return JsonResponse({
            'success': True,
            'message': 'SOL session stopped'
        })
        
    except Exception as e:
        logger.error(f"Error stopping SOL session: {e}")
        return JsonResponse({
            'success': False,
            'error': str(e)
        }) 