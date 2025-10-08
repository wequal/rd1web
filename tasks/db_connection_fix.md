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

## Implementation Summary - COMPREHENSIVE FIX v2

### Changes Applied (Lines in rma_logs.py):

1. **New Function `get_all_rma_data_batch()`** (Lines 1019-1121)
   - Collects all BMC IPs from directories
   - Makes **ONE single database query** for all BMC IPs at once
   - Gets **BOTH golden numbers AND tester names** in the same query
   - Creates TWO lookup dictionaries: tester_map and golden_map
   - Includes caching for both values to avoid repeated queries
   - **Explicitly closes database connection** in finally block to prevent pool exhaustion

2. **Updated `load_directory_details_batch()`** (Lines 390-407)
   - Calls combined batch query for both testers and golden numbers (Line 391)
   - Uses dictionary lookups instead of individual queries (Lines 406-407)
   - **Reduced from 2N database queries to 1 database query**
   - (Was: N queries for testers + N queries for golden numbers = 2N total)
   - (Now: 1 query for both = 1 total)

3. **Added connection.close() to `get_golden_number()`** (Lines 1012-1014)
   - Ensures connection is released even if function is called individually
   - Prevents connection leaks in edge cases

4. **Added connection.close() to `get_tester_name()`** (Lines 1191-1193)
   - Ensures connection is released even if function is called individually
   - Prevents connection leaks in edge cases

### Key Optimizations:
- **Database Queries**: Reduced from 2N queries (N for testers + N for golden) to 1 query total
- **Connection Management**: Added `connection.close()` in 3 places to ensure ALL connections are released
- **Caching**: Both tester and golden results are cached to avoid repeated database hits
- **Error Handling**: Graceful fallback to 'N/A' if any errors occur
- **Batch Processing**: ONE query fetches everything needed for all directories

### Why This Fix Works:
1. **Eliminates N+N Query Problem**: Instead of querying once per directory for each field, we query once for ALL directories
2. **Explicit Connection Closing**: Django's connection pooling can leak connections; we now explicitly close them
3. **Reduced Database Load**: From 200+ queries to 1 query for 100 directories
4. **Connection Pool Safety**: Even if individual functions are called, connections are properly closed

### Testing Notes:
The fix should be tested by:
1. Loading RMA logs page with many directories (100+)
2. Monitoring PostgreSQL connections: `SELECT count(*) FROM pg_stat_activity WHERE datname='rd1web';`
3. Checking logs - the warning messages should not appear anymore:
   - "Error querying RMA Testing DB for {directory}" - should be gone
   - "Error querying RMA Testing DB for tester of {directory}" - should be gone
4. Verifying both tester names AND golden numbers still display correctly

