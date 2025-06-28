#!/usr/bin/env python3
"""
Background tasks for the PXE application.
This module runs arp-scan periodically in a background thread for multiple subnets.
"""

import os
import re
import subprocess
import threading
import time
import logging
import requests
import json
from datetime import datetime
from django.utils import timezone
from django.db import transaction
from .models import ArpScanResult

logger = logging.getLogger(__name__)

class MultiSubnetScanner:
    """Background task that runs arp-scan concurrently for multiple subnets"""
    
    def __init__(self):
        self.main_thread = None
        self.running = False
        self.output_file = '/tmp/ip'
        
        # Define multiple subnets to scan
        self.subnets = {
            'local': {
                'interface': 'eno1',
                'network': '172.31.0.0/16',
                'description': 'Local Network',
                'scan_method': 'arp-scan'  # Use arp-scan directly
            },
            'remote': {
                'interface': 'eno1', 
                'network': '10.135.0.0/16',
                'description': 'Remote Network',
                'scan_method': 'fastapi',  # Use FastAPI endpoint
                'api_url': 'http://10.135.179.104:8000/scan'
            }
        }
        
    def start(self):
        """Start the background task"""
        if self.running:
            logger.warning("Multi-subnet scanner is already running")
            return
            
        self.running = True
        
        self.main_thread = threading.Thread(target=self._run_loop, daemon=True)
        self.main_thread.start()
        
        subnets_info = ', '.join([f"{k}: {v['network']} ({v['scan_method']})" for k, v in self.subnets.items()])
        logger.info(f"Started multi-subnet scanner with concurrent scanning (subnets: {subnets_info})")
        
    def stop(self):
        """Stop the background task"""
        if self.running:
            self.running = False
            logger.info("Stopping multi-subnet scanner...")
            if self.main_thread and self.main_thread.is_alive():
                self.main_thread.join(timeout=30)
            logger.info("Multi-subnet scanner stopped")
    
    def _run_loop(self):
        """Main loop that scans all subnets concurrently"""
        scan_count = 0
        
        while self.running:
            try:
                scan_count += 1
                logger.info(f"Starting concurrent multi-subnet scan #{scan_count}")
                
                # Create threads for concurrent scanning
                scan_threads = []
                
                for subnet_name, subnet_config in self.subnets.items():
                    if not self.running:
                        break
                        
                    # Create a thread for each subnet scan
                    thread = threading.Thread(
                        target=self._scan_subnet_worker,
                        args=(subnet_name, subnet_config),
                        daemon=True
                    )
                    scan_threads.append(thread)
                    thread.start()
                    logger.debug(f"Started scan thread for {subnet_name} subnet ({subnet_config['scan_method']})")
                
                # Wait for all scan threads to complete
                for thread in scan_threads:
                    thread.join(timeout=600)  # 10 minute timeout per thread
                
                logger.info(f"Concurrent multi-subnet scan #{scan_count} completed")
                    
            except Exception as e:
                logger.error(f"Error in multi-subnet scan #{scan_count}: {str(e)}")
            
            # Small delay between scan cycles
            if self.running:
                time.sleep(10)  # Slightly longer delay since scans are concurrent
    
    def _scan_subnet_worker(self, subnet_name, subnet_config):
        """Worker thread function to scan a specific subnet"""
        try:
            scan_method = subnet_config.get('scan_method', 'arp-scan')
            logger.info(f"Scanning {subnet_name} subnet: {subnet_config['network']} (method: {scan_method})")
            
            if scan_method == 'fastapi':
                success = self._run_fastapi_scan(subnet_name, subnet_config)
            else:
                success = self._run_subnet_scan(subnet_name, subnet_config)
                
            if success:
                self._update_database_for_subnet(subnet_name, subnet_config)
                logger.info(f"Concurrent scan completed for {subnet_name} subnet")
            else:
                logger.error(f"Concurrent scan failed for {subnet_name} subnet")
                
        except Exception as e:
            logger.error(f"Error in concurrent scan worker for {subnet_name}: {str(e)}")
    
    def _run_fastapi_scan(self, subnet_name, subnet_config):
        """Get scan results from FastAPI endpoint"""
        api_url = subnet_config.get('api_url')
        if not api_url:
            logger.error(f"No API URL configured for {subnet_name}")
            return False
            
        try:
            logger.debug(f"Calling FastAPI endpoint: {api_url}")
            
            # Make HTTP request to FastAPI endpoint
            response = requests.get(api_url, timeout=300)  # 5 minute timeout
            
            if response.status_code == 200:
                data = response.json()
                hosts = data.get('hosts', [])
                
                # Convert FastAPI format to arp-scan format and save to file
                output_file = f"{self.output_file}_{subnet_name}"
                with open(output_file, 'w') as f:
                    f.write(f"Interface: {subnet_config['interface']}, type: EN10MB\n")
                    f.write(f"Starting arp-scan 1.10.0 with {len(hosts)} hosts\n")
                    
                    for host in hosts:
                        ip = host.get('IP Address', '')
                        mac = host.get('MAC Address', '')
                        hostname = host.get('Hostname', '(Unknown)')
                        
                        if ip and mac:
                            f.write(f"{ip}\t{mac}\t{hostname}\n")
                    
                    f.write(f"\n{len(hosts)} packets received by filter\n")
                    f.write(f"{len(hosts)} packets captured by pcap\n")
                
                logger.debug(f"FastAPI scan for {subnet_name} returned {len(hosts)} hosts")
                return True
            else:
                logger.error(f"FastAPI endpoint returned status {response.status_code}: {response.text}")
                return False
                
        except requests.exceptions.Timeout:
            logger.error(f"FastAPI request to {api_url} timed out after 300 seconds")
            return False
        except requests.exceptions.RequestException as e:
            logger.error(f"Error calling FastAPI endpoint {api_url}: {str(e)}")
            return False
        except Exception as e:
            logger.error(f"Error in FastAPI scan for {subnet_name}: {str(e)}")
            return False
    
    def _run_subnet_scan(self, subnet_name, subnet_config):
        """Run arp-scan for a specific subnet"""
        interface = subnet_config['interface']
        network = subnet_config['network']
        output_file = f"{self.output_file}_{subnet_name}"
        
        command = f'arp-scan -I {interface} {network}'
        
        try:
            logger.debug(f"Running concurrent arp-scan: {command}")
            
            # Run arp-scan and redirect output to subnet-specific file
            with open(output_file, 'w') as f:
                result = subprocess.run(
                    command.split(),
                    stdout=f,
                    stderr=subprocess.PIPE,
                    timeout=300,  # 5 minute timeout
                    text=True
                )
            
            if result.returncode != 0:
                error_msg = result.stderr if result.stderr else 'Unknown error'
                logger.error(f"Arp-scan failed for {subnet_name} with return code {result.returncode}: {error_msg}")
                return False
                
            return True
            
        except subprocess.TimeoutExpired:
            logger.error(f"Arp-scan timed out for {subnet_name} after 300 seconds")
            return False
        except Exception as e:
            logger.error(f"Error running arp-scan for {subnet_name}: {str(e)}")
            return False
    
    def _update_database_for_subnet(self, subnet_name, subnet_config):
        """Parse arp-scan results and update database for specific subnet"""
        output_file = f"{self.output_file}_{subnet_name}"
        
        if not os.path.exists(output_file):
            logger.error(f"Output file {output_file} not found for {subnet_name}")
            return
        
        try:
            current_ips = set()
            new_entries = 0
            updated_entries = 0
            
            with open(output_file, 'r') as f:
                for line in f:
                    line = line.strip()
                    
                    # Skip empty lines and header/footer lines
                    if not line or line.startswith('Interface:') or line.startswith('Starting') or line.startswith('packets'):
                        continue
                        
                    # Parse lines: IP_ADDRESS    MAC_ADDRESS    HOSTNAME
                    # Support both formats:
                    # 1. Standard arp-scan: 172.31.60.1    00:0c:29:3e:f7:8a    (Unknown)
                    # 2. FastAPI format: IP + MAC + Hostname (tab separated)
                    match = re.match(r'^(\d+\.\d+\.\d+\.\d+)\s+([0-9a-fA-F:]{17})\s*(.*?)$', line)
                    
                    if match:
                        ip_address = match.group(1)
                        mac_address = match.group(2).lower()
                        hostname = match.group(3).strip()
                        
                        # Clean up hostname
                        if hostname in ['', '(Unknown)', '(unknown)']:
                            hostname = None
                            
                        current_ips.add(ip_address)
                        
                        # Update or create database entry with subnet info
                        with transaction.atomic():
                            obj, created = ArpScanResult.objects.update_or_create(
                                ip_address=ip_address,
                                defaults={
                                    'mac_address': mac_address,
                                    'hostname': hostname,
                                    'is_active': True,
                                    'last_seen': timezone.now(),
                                    'subnet_source': subnet_name,
                                    'scan_interface': subnet_config['interface']
                                }
                            )
                            
                            if created:
                                new_entries += 1
                                logger.debug(f'New {subnet_name} entry: {ip_address} ({mac_address})')
                            else:
                                updated_entries += 1
                                logger.debug(f'Updated {subnet_name}: {ip_address} ({mac_address})')
            
            # Mark entries from this subnet not in current scan as inactive
            inactive_count = 0
            if current_ips:
                with transaction.atomic():
                    inactive_entries = ArpScanResult.objects.filter(
                        is_active=True,
                        subnet_source=subnet_name
                    ).exclude(ip_address__in=current_ips)
                    
                    for entry in inactive_entries:
                        entry.is_active = False
                        entry.save()
                        inactive_count += 1
                        logger.debug(f'Marked inactive in {subnet_name}: {entry.ip_address} ({entry.mac_address})')
            
            logger.info(f'{subnet_name} database update: {new_entries} new, {updated_entries} updated, {inactive_count} inactive')
            
            # Clean up output file
            try:
                os.remove(output_file)
            except OSError:
                pass
                
        except Exception as e:
            logger.error(f"Error updating database for {subnet_name}: {str(e)}")

    def get_status(self):
        """Get current scanner status"""
        return {
            'running': self.running,
            'subnets': self.subnets,
            'mode': 'concurrent-multi-subnet'
        }


# Global instance - keeping the same variable name for backward compatibility
mac_ip_task = MultiSubnetScanner() 