# Admin Panel User Activity Timezone Fix

## Overview
Fix the admin panel user activity statistics to use LA timezone instead of UTC. Currently, "Most Active Users Today" resets at midnight UTC instead of midnight LA time.

## Problem
- Django setting: `TIME_ZONE = 'America/Los_Angeles'`
- Admin panel uses `timezone.now().date()` which returns UTC date
- Daily statistics reset at 5:00 PM LA time (PDT) or 4:00 PM LA time (PST) instead of midnight LA time

## Solution
Convert timezone-aware datetime to LA timezone before extracting the date.

## Tasks

- [x] 1. Update `changelist_view()` in UserActivityAdmin to use LA timezone
- [ ] 2. Test the fix to ensure daily stats reset at midnight LA time

## Files Modified
- ✅ rd1web/authentication/admin.py - Updated timezone calculation in changelist_view()

## Implementation Details

### Current Code (admin.py:82-86)
```python
# Get current date
now = timezone.now()
today = now.date()  # This uses UTC!
week_start = today - timedelta(days=today.weekday())
month_start = today.replace(day=1)
```

### Fixed Code
```python
# Get current date in LA timezone
now = timezone.now()
la_tz = zoneinfo.ZoneInfo('America/Los_Angeles')
today = now.astimezone(la_tz).date()  # Convert to LA timezone first
week_start = today - timedelta(days=today.weekday())
month_start = today.replace(day=1)
```

### Required Import
Add `zoneinfo` import at the top of the file:
```python
import zoneinfo
```

## Impact
- ✅ Minimal code change (one import, one line modification)
- ✅ Daily statistics will reset at midnight LA time
- ✅ Weekly and monthly statistics will also use LA timezone
- ✅ No database changes required
- ✅ Backward compatible

## Expected Result
After the fix:
- "Most Active Users Today" resets at 00:00 LA time (not UTC)
- All daily/weekly/monthly filters use LA timezone
- Admin panel displays consistent with local timezone setting
