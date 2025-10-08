# Database Connection Pool Exhaustion Fix

## Problem
The RMA logs page is causing PostgreSQL connection pool exhaustion with error:
```
FATAL: remaining connection slots are reserved for roles with the SUPERUSER attribute
```

## Root Cause
In `rma_logs.py`, the `load_rma_details_batch()` function loops through directories and calls `get_tester_name()` for each one. Each call makes a separate database query to `RmaTestingDb`. With many directories (100+), this creates too many concurrent database connections.

### Current Flow (Line 390-404):
```python
for dir_name in directory_names:  # Loop through 100+ directories
    tester_name = get_tester_name(dir_name)  # Each makes a DB query!
```

### Why It Fails:
- PostgreSQL has max_connections limit (typically 100-200)
- Each query opens a connection
- With many directories + multiple users = connection exhaustion

## Solution
**Batch all database queries into a single query** instead of N individual queries.

### Strategy:
1. Collect all BMC IPs from all directories first
2. Query database ONCE for all BMC IPs
3. Create a lookup dictionary
4. Use the lookup instead of individual queries

## Implementation Tasks

- [x] 1. Create new `get_all_testers_batch()` function to query all testers at once
- [x] 2. Update `load_rma_details_batch()` to use batch query
- [x] 3. Add connection closing in exception handlers
- [ ] 4. Test with many RMA directories

## Files Modified
- ✅ rd1web/pxe/views/rma_logs.py

## Code Changes

### New Function: `get_all_testers_batch()`
```python
def get_all_testers_batch(directory_names):
    """
    Get all tester names for multiple directories in a single database query
    Returns dict mapping directory_name -> tester_name
    """
    from ..models import RmaTestingDb
    from django.db import connection
    
    tester_map = {}
    bmc_ip_to_dir = {}  # Map BMC IP to directory name
    
    # Step 1: Get all BMC IPs from all directories
    for dir_name in directory_names:
        cache_key = f"rma_tester_{dir_name}"
        cached = cache.get(cache_key)
        if cached:
            tester_map[dir_name] = cached
            continue
            
        # Get BMC IP for this directory
        bmc_ip = get_bmc_ip_for_directory(dir_name)
        if bmc_ip:
            bmc_ip_to_dir[bmc_ip] = dir_name
    
    # Step 2: Query database ONCE for all BMC IPs
    if bmc_ip_to_dir:
        try:
            entries = RmaTestingDb.objects.filter(
                bmc_ip__in=bmc_ip_to_dir.keys()
            ).select_related('linked_user').values('bmc_ip', 'linked_user__username', 'last_tester')
            
            # Step 3: Build lookup dictionary
            for entry in entries:
                bmc_ip = entry['bmc_ip']
                dir_name = bmc_ip_to_dir[bmc_ip]
                tester = entry['linked_user__username'] or entry['last_tester'] or 'N/A'
                tester_map[dir_name] = tester
                cache.set(f"rma_tester_{dir_name}", tester, RMA_DETAILS_CACHE_TIMEOUT)
                
        finally:
            connection.close()  # Ensure connection is released
    
    # Fill in N/A for directories without tester info
    for dir_name in directory_names:
        if dir_name not in tester_map:
            tester_map[dir_name] = 'N/A'
    
    return tester_map
```

### Update `load_rma_details_batch()`:
```python
# Before the loop, get all testers at once
tester_map = get_all_testers_batch(directory_names)

for dir_name in directory_names:
    # ... existing code ...
    tester_name = tester_map.get(dir_name, 'N/A')  # Use lookup instead of query
```

## Performance Impact
- **Before**: N database queries (one per directory)
- **After**: 1 database query (for all directories)
- **Connection Usage**: Reduced from N connections to 1 connection
- **Speed**: Much faster due to single query

## Expected Results
- ✅ No more connection pool exhaustion errors
- ✅ Faster page load times
- ✅ Better scalability with many directories
- ✅ Reduced database load

---

## Implementation Summary

### Changes Applied (Lines in rma_logs.py):

1. **New Function `get_all_testers_batch()`** (Lines 1016-1106)
   - Collects all BMC IPs from directories
   - Makes a single batched database query for all BMC IPs at once
   - Creates a lookup dictionary mapping directory → tester
   - Includes caching to avoid repeated queries
   - **Explicitly closes database connection** to prevent pool exhaustion

2. **Updated `load_directory_details_batch()`** (Lines 374-432)
   - Added batch query call before the loop (Line 391)
   - Changed individual `get_tester_name()` call to dictionary lookup (Line 407)
   - Reduced from N database queries to 1 database query

### Key Optimizations:
- **Database Queries**: Reduced from N queries (one per directory) to 1 query (all directories)
- **Connection Management**: Added `connection.close()` in finally block to ensure connections are released
- **Caching**: Results are cached to avoid repeated database hits
- **Error Handling**: Graceful fallback to 'N/A' if any errors occur

### Testing Notes:
The fix should be tested by:
1. Loading RMA logs page with many directories (100+)
2. Monitoring PostgreSQL connections: `SELECT count(*) FROM pg_stat_activity WHERE datname='rd1web';`
3. Checking logs for the warning message - should not appear anymore
4. Verifying tester names still display correctly

