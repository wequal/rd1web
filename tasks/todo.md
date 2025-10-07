# RMA Logs - Show Last Tester Enhancement

## Overview
Show current tester if linked, or show last tester if no one is currently linked to the golden number.

## Tasks

- [x] 1. Add last_tester field to RmaTestingDb model
- [x] 2. Update golden_unlink() function to save current user before unlinking
- [x] 3. Update get_tester_name() function to show current or last tester
- [x] 4. Create and run Django migrations

## Files Modified
- ✅ rd1web/pxe/models.py - Added last_tester field
- ✅ rd1web/pxe/views/rma_testing_db.py - Updated golden_unlink()
- ✅ rd1web/pxe/views/rma_logs.py - Updated get_tester_name()
- ✅ rd1web/pxe/migrations/0017_rmatestingdb_last_tester.py - Created migration

## Implementation Summary

### 1. Database Model Change (models.py:110-116)
Added new field after linked_user:
```python
last_tester = models.CharField(
    max_length=150,
    null=True,
    blank=True,
    help_text='Last user who was linked to this golden number',
    verbose_name='Last Tester'
)
```

### 2. Updated Golden Unlink Logic (rma_testing_db.py:302-308)
Before unlinking, save current tester:
```python
# Save current tester before unlinking
if entry.linked_user:
    entry.last_tester = entry.linked_user.username

# Unlink the golden number
entry.linked_user = None
entry.save()
```

### 3. Updated Tester Display Logic (rma_logs.py:1059-1074)
Show current tester if linked, otherwise show last tester:
```python
# Show current tester if linked, otherwise show last tester
if rma_entry and rma_entry.linked_user:
    tester_name = rma_entry.linked_user.username  # Current tester
    cache.set(cache_key, tester_name, RMA_DETAILS_CACHE_TIMEOUT)
    return tester_name
elif rma_entry and hasattr(rma_entry, 'last_tester') and rma_entry.last_tester:
    tester_name = rma_entry.last_tester  # Last tester
    cache.set(cache_key, tester_name, RMA_DETAILS_CACHE_TIMEOUT)
    return tester_name
else:
    cache.set(cache_key, 'N/A', RMA_DETAILS_CACHE_TIMEOUT)
    return 'N/A'
```

## How It Works

1. **When a golden number is linked**: The tester column shows the current user's username
2. **When a golden number is unlinked**: The system saves the current user's username to `last_tester` field
3. **When viewing RMA logs**: 
   - If golden is currently linked → shows current tester
   - If golden is unlinked but has history → shows last tester
   - If no history → shows 'N/A'

## Impact
- ✅ Preserves historical tester information
- ✅ Backward compatible (nullable field)
- ✅ Minimal code changes
- ✅ Database migration applied successfully
- ✅ Shows current or last tester automatically
