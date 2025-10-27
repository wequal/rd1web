# Configuration Externalization Implementation Plan

## Overview
This document outlines the plan for externalizing configuration settings to make the web application easier to deploy across different locations.

## Completed Tasks ✓

### Phase 1: Configuration File Setup ✓
- [x] Create `local_config.py` with all location-specific settings
- [x] Create `local_config.template.py` as a reference template for new deployments
- [x] Update `remote_config.py` to load from `local_config.py`
- [x] Update `.gitignore` to exclude `local_config.py`

## Configuration Categories Externalized

### 1. File System Paths ✓
- `RMA_BASE_DIR`: `/srv/rma-b31`
- `TEMP_ZIPS_DIR`: `/srv/rma-b31/.TempZips`
- `RMA_PXE_GENERATION_SCRIPT`: `/srv/share/scripts/rma_pxe_generation`
- `PXE_BOOT_PATH`: `/var/www/pxe/boot/`

### 2. Database Configuration ✓
- Database name, user, password, host, and port
- Currently configured for: `pxe_db` on `172.31.56.135:5432`

### 3. Remote Server Connections ✓
- RMA server: `root@10.4.4.80`
- US B3 server: `root@172.31.56.135`
- US B1 server: `root@172.31.58.142`
- TW server: `root@10.135.179.104`

### 4. RMA DHCP Leases API ✓
- Port: `8000`
- Endpoint: `/leases`
- Timeout: `10` seconds

### 5. Network Scanning Configuration ✓
- Local subnet: `172.31.0.0/16` on `eno1np0` (arp-scan)
- Remote subnet: `10.135.0.0/16` on `eno1` (FastAPI)

### 6. Service Configuration ✓
- Web app port: `5003`
- Redis: `localhost:6379`

### 7. Django Settings ✓
- SECRET_KEY
- TIME_ZONE: `America/Los_Angeles`
- DEBUG mode

### 8. Cache/Timeout Settings ✓
- RMA_CACHE_TIMEOUT: 30s
- RMA_DETAILS_CACHE_TIMEOUT: 60s
- RMA_STATS_CACHE_TIMEOUT: 300s
- ZIP_TASK_TIMEOUT: 3600s

## Phase 2: Code Updates - COMPLETED ✓

### Files Updated to Use local_config.py ✓
All files have been successfully updated to import from `local_config.py`:

#### High Priority ✓
- [x] `rd1web/rd1web/settings.py` - Database, Redis, Django settings
- [x] `rd1web/pxe/views/rma_logs.py` - RMA_BASE_DIR, TEMP_ZIPS_DIR, cache timeouts
- [x] `rd1web/pxe/rma_statistics.py` - RMA_BASE_DIR
- [x] `rd1web/pxe/views/rma_pxe.py` - RMA_PXE_GENERATION_SCRIPT, PXE_BOOT_PATH
- [x] `rd1web/pxe/views/rma_dhcp_leases.py` - RMA DHCP API settings
- [x] `rd1web/pxe/views/mac_ip_view.py` - SUBNET_CONFIGS

#### Medium Priority ✓
- [x] `rd1web/run_server.py` - WEB_APP_PORT
- [x] All hardcoded IPs and paths externalized

### Phase 3: Testing - COMPLETED ✓
- [x] Test application startup with new configuration
  - Django check passed successfully
  - All configuration imports working correctly
  - No syntax or import errors
- [x] Verify configuration loading
  - Database: 172.31.56.135 ✓
  - RMA Base: /srv/rma-b31 ✓
  - Web Port: 5003 ✓
  - Remote Servers: rma, us_b3, us_b1, tw ✓

### Test Results
```
✓ Successfully loaded REMOTE_SERVERS from local_config.py
✓ MAC-IP scanning using SUBNET_CONFIGS from local_config.py
✓ RMA PXE using configuration from local_config.py
✓ RMA logs using configuration from local_config.py
✓ RMA DHCP Leases using configuration: 10.4.4.80:8000/leases
✓ RMA statistics using RMA_BASE_DIR from local_config.py
✓ Django system check passed (0 errors, 5 security warnings for HTTPS/SSL)
```

## Ready for Production Testing
The application can now be tested with actual operations:
- Remote connections
- RMA logs viewing
- PXE generation
- DHCP leases API
- Network scanning

### Phase 4: Documentation
- [ ] Update README with deployment instructions
- [ ] Document how to set up `local_config.py` for new locations
- [ ] Create location-specific configuration examples

## Deployment Instructions for New Locations

1. Clone the repository
2. Copy the template:
   ```bash
   cp rd1web/pxe/local_config.template.py rd1web/pxe/local_config.py
   ```
3. Edit `local_config.py` with location-specific values:
   - Update `DEPLOYMENT_LOCATION`
   - Update database credentials and host
   - Update remote server IPs and credentials
   - Update network interfaces and subnets
   - Generate a new SECRET_KEY for production
   - Set appropriate TIME_ZONE
4. Verify `.gitignore` excludes `local_config.py`
5. Test the application

## Benefits

✅ **Security**: Passwords and sensitive data not in git
✅ **Flexibility**: Easy to deploy to different locations
✅ **Maintainability**: Configuration structure is version controlled
✅ **Documentation**: Template file serves as reference
✅ **No Code Duplication**: Same codebase works everywhere

## Notes

- The `remote_config.py` module now builds Fabric Connection objects dynamically from `local_config.py`
- All async functionality remains unchanged
- Fallback to defaults if `local_config.py` doesn't exist (for backwards compatibility)
- Each deployment location maintains its own `local_config.py` file (not in git)
