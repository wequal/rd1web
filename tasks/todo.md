# RMA Logs Golden Column Enhancement

## Overview
Add a "Golden" column to the RMA logs page that displays the golden number associated with each RMA directory by reading the BMC IP from `bmc_ip.txt` and mapping it to the golden number in the RMA Testing DB.

## Implementation Plan

### Task 1: Add Golden Number Lookup Function
- [x] Create `get_golden_number()` function in `rd1web/pxe/views/rma_logs.py`
  - Read `bmc_ip.txt` from the RMA directory
  - Query RmaTestingDb model to find matching BMC IP
  - Return golden_number or 'N/A' if not found
  - Add caching to improve performance

### Task 2: Integrate Golden Number into Directory Data
- [x] Modify `get_rma_directories()` function to call `get_golden_number()`
- [x] Add `golden_number` field to the directory dictionary
- [x] Update both success and error cases to include golden number

### Task 3: Update Template (HTML)
- [x] Add "Golden" column header after "GPU Model" in `rma_logs.html`
- [x] Add golden number display in the table body
- [x] Update JavaScript to handle golden number in AJAX responses
- [x] Add golden number to the updateDirectoriesTable function

### Task 4: Performance Optimization
- [x] Add caching for BMC IP to golden number mappings
- [x] Use select_related/prefetch_related for database queries if needed
- [x] Cache the entire golden number lookup result per directory

### Task 5: Testing
- [ ] Verify golden number displays correctly for existing RMA directories
- [ ] Test with directories that have no `bmc_ip.txt` file
- [ ] Test with BMC IPs not in the database
- [ ] Verify page loading speed improvement

## Files to Modify
1. `/home/devin/rd1web-dev/rd1web/pxe/views/rma_logs.py` - Add golden number lookup logic
2. `/home/devin/rd1web-dev/rd1web/templates/features/rma_logs.html` - Add column to UI

## Performance Notes
- Use Django cache for BMC IP → Golden Number mapping (5 minute timeout)
- Golden number is included in basic directory data (no extra load time)
- Database query uses indexed bmc_ip field for fast lookups
