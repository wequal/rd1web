# Firmware Inventory - File Upload Size Fix

## Issue
Getting "413 Request Entity Too Large" error when uploading firmware files.

## Root Cause
The nginx configuration had a `client_max_body_size` limit of 100MB, which was too small for large firmware files.

## Solution

### Updated nginx Configuration
**File**: `/etc/nginx/sites-available/rd1web`

**Changes Made:**
1. Increased `client_max_body_size` from **100M** to **500M**
2. Increased `client_body_timeout` from **120s** to **300s** 
3. Increased `client_header_timeout` from **120s** to **300s**

**Applied to:**
- Main production server (port 80)
- Test server (port 5003)

### Commands Executed
```bash
# Test configuration
nginx -t

# Reload nginx
systemctl reload nginx
```

## Result
✅ Users can now upload firmware files up to 500MB in size
✅ Upload timeout increased to 5 minutes for large files
✅ No Django code changes required (Django has no explicit limits)

## Configuration Details

**Before:**
```nginx
client_max_body_size 100M;
client_body_timeout 120s;
client_header_timeout 120s;
```

**After:**
```nginx
client_max_body_size 500M;
client_body_timeout 300s;
client_header_timeout 300s;
```

## Testing
1. Navigate to any product ECO page (e.g., H100_AC/31882)
2. Upload firmware files (GPU, retimers)
3. Files up to 500MB should upload successfully
4. Upload progress should be visible
5. Files should be renamed correctly and saved to `/srv/firmwareinventory/`

## Notes
- Django's default `FILE_UPLOAD_MAX_MEMORY_SIZE` is 2.5MB (files larger than this are streamed to temp files)
- Django's default `DATA_UPLOAD_MAX_MEMORY_SIZE` is 2.5MB (for POST data excluding files)
- No need to modify Django settings - nginx limit is the primary constraint
- If larger files are needed in future, simply increase `client_max_body_size` in nginx config

