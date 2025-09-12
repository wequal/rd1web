# RMA Log Page with Pagination and Lazy Loading

## Task: Add pagination and lazy loading to RMA directories

### Background:
- RMA log page simplified to show only directories with search functionality
- User requested pagination for better performance with many directories
- Need lazy loading to improve page responsiveness

### Tasks:
- [x] Add pagination support for RMA directories listing
- [x] Implement lazy loading for directory table
- [x] Update RMA logs view to support pagination (20 items per page)
- [x] Update template with pagination controls
- [x] Add AJAX support for lazy loading
- [x] Add loading spinner for better UX
- [x] Implement debounced search (500ms delay)
- [x] Add proper error handling for AJAX requests
- [x] Add download button next to view button in directory browser
- [x] Implement download functionality with ?download=1 parameter
- [x] Style button groups for better UI presentation

### Implementation Details:
- Update `check_rma_logs_availability()` to scan /srv/rma for directories matching pattern {base_sn}_{rma_number}
- Modify `get_recent_rma_logs()` to read from RMA-specific directories
- Use existing log_view pattern: add RMA-specific URL routing like 'rma/logs/<path:path>/'
- Reuse existing view_file functionality for file viewing and downloading
- Update template to show RMA directories as browsable items using existing log browser UI
- Leverage existing file type detection and display capabilities from log_view.py

### Minimal Impact:
- Only changing log source location and structure
- No changes to existing UI layout
- Maintaining backward compatibility for error cases