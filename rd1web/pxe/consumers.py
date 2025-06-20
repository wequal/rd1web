import json
import asyncio
import subprocess
import pty
import os
import select
import termios
import struct
import fcntl
import logging
from channels.generic.websocket import AsyncWebsocketConsumer
from pxe.sol_session import SOLSession
from pxe.utils import get_system_sysconfig
import urllib.parse

logger = logging.getLogger(__name__)

BASE_DIR = '/srv/log'

class SOLConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.folder_name = self.scope['url_route']['kwargs']['folder_name']
        self.sol_session = None
        self.read_task = None
        
        logger.info(f"SOL WebSocket connection attempt for {self.folder_name}")
        
        # Get system configuration
        sysconfig = get_system_sysconfig(self.folder_name)
        if not sysconfig or 'bmc_ip' not in sysconfig:
            logger.error(f"BMC IP not found for {self.folder_name}")
            await self.close(code=4001)
            return
        
        bmc_ip = sysconfig['bmc_ip']
        bmc_user = sysconfig.get('bmc_user', 'ADMIN')
        bmc_pwd = sysconfig.get('bmc_unique_pwd', 'ADMIN')
        
        # Create SOL session
        self.sol_session = SOLSession(self.folder_name, bmc_ip, bmc_user, bmc_pwd)
        
        # Accept the WebSocket connection
        await self.accept()
        
        # Start SOL process
        if self.sol_session.start_sol_process():
            # Send initial connection message
            await self.send(text_data=json.dumps({
                'type': 'info',
                'message': f'SOL session connected to {bmc_ip}\r\nUse ~. to exit SOL session\r\nUse ~? for help\r\n\r\n'
            }))
            
            # Start reading from SOL process
            self.read_task = asyncio.create_task(self.read_sol_output())
            logger.info(f"SOL WebSocket connected for {self.folder_name}")
        else:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Failed to start SOL process'
            }))
            await self.close(code=4002)

    async def disconnect(self, close_code):
        logger.info(f"SOL WebSocket disconnected for {self.folder_name} with code: {close_code}")
        
        # Cancel read task
        if self.read_task:
            self.read_task.cancel()
            try:
                await self.read_task
            except asyncio.CancelledError:
                pass
        
        # Clean up SOL session
        if self.sol_session:
            self.sol_session.cleanup()

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            
            if data.get('type') == 'input':
                input_data = data.get('data', '')
                if self.sol_session:
                    self.sol_session.write_to_sol(input_data)
                    
            elif data.get('type') == 'resize':
                # Handle terminal resize
                rows = data.get('rows', 24)
                cols = data.get('cols', 80)
                if self.sol_session and self.sol_session.master_fd:
                    try:
                        # Set terminal size
                        winsize = struct.pack('HHHH', rows, cols, 0, 0)
                        fcntl.ioctl(self.sol_session.master_fd, termios.TIOCSWINSZ, winsize)
                    except Exception as e:
                        logger.error(f"Error setting terminal size: {str(e)}")
                        
            elif data.get('type') == 'disconnect':
                # Handle explicit disconnect request
                reason = data.get('reason', 'Client requested disconnect')
                logger.info(f"SOL disconnect requested for {self.folder_name}: {reason}")
                
                # Send SOL exit sequence to ensure clean termination
                if self.sol_session:
                    self.sol_session.write_to_sol('~.')
                    
                # Send acknowledgment
                await self.send(text_data=json.dumps({
                    'type': 'info',
                    'message': 'SOL session terminating...\r\n'
                }))
                
                # Close the WebSocket connection
                await self.close(code=1000)
                        
        except json.JSONDecodeError:
            logger.error("Invalid JSON received from WebSocket")
        except Exception as e:
            logger.error(f"Error handling WebSocket message: {str(e)}")

    async def read_sol_output(self):
        """Continuously read output from SOL process and send to WebSocket"""
        while self.sol_session and self.sol_session.running:
            try:
                output = self.sol_session.read_from_sol()
                if output:
                    await self.send(text_data=json.dumps({
                        'type': 'output',
                        'data': output
                    }))
                await asyncio.sleep(0.05)  # Small delay to prevent busy waiting
            except Exception as e:
                logger.error(f"Error reading SOL output: {str(e)}")
                break 

class RemoteSOLConsumer(AsyncWebsocketConsumer):
    """WebSocket consumer for ad-hoc SOL sessions started from *Remote Control*."""

    async def connect(self):
        # Extract connection parameters from query string
        query_params = urllib.parse.parse_qs(self.scope.get('query_string', b'').decode())
        self.bmc_ip = (query_params.get('bmc_ip') or [None])[0]
        self.bmc_user = (query_params.get('bmc_user') or ['ADMIN'])[0]
        self.bmc_pwd = (query_params.get('bmc_pwd') or [None])[0]
        self.session_id = (query_params.get('session') or ['remote'])[0]

        logger.info(
            "Remote SOL WebSocket connect: ip=%s user=%s session=%s",
            self.bmc_ip, self.bmc_user, self.session_id,
        )

        if not (self.bmc_ip and self.bmc_pwd):
            await self.close(code=4001)
            return

        # Create SOL session
        self.sol_session = SOLSession(self.session_id, self.bmc_ip, self.bmc_user, self.bmc_pwd)

        await self.accept()

        if self.sol_session.start_sol_process():
            await self.send(text_data=json.dumps({
                'type': 'info',
                'message': f'SOL session connected to {self.bmc_ip}\r\nUse ~. to exit SOL session\r\nUse ~? for help\r\n\r\n'
            }))
            self.read_task = asyncio.create_task(self.read_sol_output())
        else:
            await self.send(text_data=json.dumps({
                'type': 'error',
                'message': 'Failed to start SOL process'
            }))
            await self.close(code=4002)

    async def disconnect(self, close_code):
        logger.info("Remote SOL disconnected (code=%s session=%s)", close_code, self.session_id)
        if hasattr(self, 'read_task') and self.read_task:
            self.read_task.cancel()
            try:
                await self.read_task
            except asyncio.CancelledError:
                pass
        if hasattr(self, 'sol_session') and self.sol_session:
            self.sol_session.cleanup()

    async def receive(self, text_data):
        try:
            data = json.loads(text_data)
            msg_type = data.get('type')
            if msg_type == 'input':
                if self.sol_session:
                    self.sol_session.write_to_sol(data.get('data', ''))
            elif msg_type == 'resize':
                rows = data.get('rows', 24)
                cols = data.get('cols', 80)
                if self.sol_session and self.sol_session.master_fd:
                    try:
                        winsize = struct.pack('HHHH', rows, cols, 0, 0)
                        fcntl.ioctl(self.sol_session.master_fd, termios.TIOCSWINSZ, winsize)
                    except Exception:
                        pass
            elif msg_type == 'disconnect':
                if self.sol_session:
                    self.sol_session.write_to_sol('~.')
                await self.send(text_data=json.dumps({'type': 'info', 'message': 'SOL session terminating...\r\n'}))
                await self.close(code=1000)
        except Exception:
            logger.exception('Error in RemoteSOLConsumer.receive')

    async def read_sol_output(self):
        while self.sol_session and self.sol_session.running:
            try:
                output = self.sol_session.read_from_sol()
                if output:
                    await self.send(text_data=json.dumps({'type': 'output', 'data': output}))
                await asyncio.sleep(0.05)
            except Exception:
                logger.exception('Error reading SOL output')
                break 