# RMA Statistics - Filter GPU Models from Breakdown

## Date: October 15, 2025

## Change Requested
Remove GPU models "unknown", "Unknown", and "BMC_IP:" from the GPU breakdown table display.

## Implementation

### Updated View Functions
**File:** `rd1web/pxe/views/rma_statistics.py`

Added filtering logic to both:
1. `rma_statistics()` - Main statistics page view
2. `rma_statistics_api()` - API endpoint

### Filtering Logic
```python
# Filter out unwanted GPU models from breakdown
if 'gpu_breakdown' in stats and stats['gpu_breakdown']:
    filtered_breakdown = {
        gpu_model: data 
        for gpu_model, data in stats['gpu_breakdown'].items()
        if gpu_model not in ['unknown', 'Unknown', 'BMC_IP:']
    }
    stats['gpu_breakdown'] = filtered_breakdown
```

### What Gets Filtered

**Models to be hidden:**
- `unknown` - 1 record (lowercase)
- `Unknown` - 38 records (capitalized)
- `BMC_IP:` - 1 record (invalid GPU model name)

**Total filtered:** 40 records (32.8% of total)

### Models Still Displayed

**Visible GPU models:**
- `H100` - 54 records
- `H200` - 11 records
- `MI325` - 13 records (combined from MI325DLC + MI325X)
- `MI300X` - 2 records
- `MI355` - 1 record
- `B200` - 1 record

**Total visible:** 82 records (67.2% of total)

## Impact

### Before Change
GPU Breakdown Table showed:
```
GPU Model    Total Units
H100         54
Unknown      38  ← Clutters display
H200         11
MI325        13
unknown      1   ← Clutters display
BMC_IP:      1   ← Invalid/error
MI300X       2
B200         1
MI355        1
```

### After Change
GPU Breakdown Table shows:
```
GPU Model    Total Units
H100         54
H200         11
MI325        13
MI300X       2
MI355        1
B200         1
```

**Benefits:**
- ✅ Cleaner, more focused display
- ✅ Only shows valid, identifiable GPU models
- ✅ Removes noise from error/unknown cases
- ✅ Better data quality visibility

## Technical Details

### Database Records
- **Not deleted:** Records remain in database
- **Still counted:** Contribute to total RMA count
- **Still tracked:** Test failures still monitored
- **Only hidden:** From GPU breakdown table display

### Failure Tracking
Failures from filtered GPU models:
- ✅ Still counted in total failure numbers
- ✅ Still included in overall statistics
- ❌ Not shown in per-GPU-model breakdown

### Total RMA Count
```
Total RMAs in Database: 122
Visible in Breakdown:    82 (67.2%)
Hidden from Breakdown:   40 (32.8%)
```

## Why These Models?

### "Unknown" / "unknown"
- sys_info.txt file missing or malformed
- GPU_Model field empty or not found
- Cannot determine actual GPU type
- **Reason to hide:** Not useful for model-specific analysis

### "BMC_IP:"
- Parsing error in sys_info.txt
- Invalid GPU_Model value
- Data quality issue
- **Reason to hide:** Invalid data, not a real GPU model

## Future Considerations

### Adding More Filters
To filter additional GPU models, update the exclusion list:

```python
if gpu_model not in ['unknown', 'Unknown', 'BMC_IP:', 'N/A', 'ERROR']:
```

### Showing Unknown Separately
If needed, could add a separate "Unknown/Other" row:

```python
unknown_count = sum(
    data['count'] for gpu_model, data in original_breakdown.items()
    if gpu_model in ['unknown', 'Unknown', 'BMC_IP:']
)
if unknown_count > 0:
    stats['gpu_breakdown']['Unknown/Other'] = {
        'count': unknown_count,
        'failures': {...}
    }
```

## Files Modified

1. `rd1web/pxe/views/rma_statistics.py`
   - Updated `rma_statistics()` view
   - Updated `rma_statistics_api()` endpoint
   - Added GPU model filtering logic

## Testing

### Before Filter
```sql
SELECT gpu_model, COUNT(*) FROM pxe_rmateststatistic 
GROUP BY gpu_model ORDER BY COUNT(*) DESC;

Results: 9 distinct GPU models including unknowns
```

### After Filter
```python
# View returns only 6 valid GPU models
filtered_breakdown = {...}  # B200, H100, H200, MI300X, MI325, MI355
```

## Validation

✅ Filtering logic applied to both view and API
✅ No linter errors
✅ Records still in database (not deleted)
✅ Total counts still accurate
✅ Only affects display, not data collection
✅ 40 records (32.8%) filtered from breakdown display

## Summary

**Change:** GPU models "unknown", "Unknown", and "BMC_IP:" are now hidden from the GPU breakdown table.

**Impact:**
- Cleaner UI with only valid GPU models
- 40 records filtered from display
- Data still tracked in database
- Total statistics unaffected

**Status:** ✅ Complete - GPU breakdown now shows only valid GPU models

---

**The breakdown table will now only display identifiable GPU models, making the data more meaningful and easier to analyze!** 🎯

