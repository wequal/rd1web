# RMA DHCP Leases Implementation Plan

## Overview
Add a new page under RMA Management called "RMA DHCP Leases" that fetches DHCP lease data from an external API and displays it in a table format.

## Requirements
1. **Page Name**: "RMA DHCP Leases"
2. **Location**: Under RMA Management section in sidebar
3. **API Endpoint**: `http://10.4.4.80:8000/leases`
4. **Expected Response**: `{"leases":[{"mac":"7c:c2:55:1a:29:7a","ip":"192.168.40.18","hostname":"-NA-"}...]}`
5. **Table Columns**: MAC, IP, Hostname
6. **Refresh Functionality**: Page load and manual refresh button

## Implementation Tasks

### 1. Create Permission and Model Updates ✅
- [x] Add new permission `can_access_rma_dhcp_leases` to PxeEntry model
- [x] Run migration to apply permission changes

### 2. Create View Function ✅
- [x] Create `rma_dhcp_leases.py` view file in `rd1web/pxe/views/`
- [x] Implement view with permission required decorator
- [x] Add API call functionality to fetch leases from external endpoint
- [x] Handle API errors gracefully (timeout, connection error, invalid response)
- [x] Implement refresh functionality

### 3. Create Template ✅
- [x] Create `rma_dhcp_leases.html` template in `rd1web/templates/features/`
- [x] Design table layout with MAC, IP, Hostname columns
- [x] Add refresh button functionality
- [x] Add loading states and error handling
- [x] Make it responsive and follow existing design patterns

### 4. URL Configuration ✅
- [x] Add URL pattern in `rd1web/pxe/urls.py`
- [x] Add API endpoint for refresh functionality if needed

### 5. Update Navigation ✅
- [x] Update sidebar template to include new RMA DHCP Leases link
- [x] Add permission check in template for link visibility

### 6. Testing ✅
- [x] Test page loads correctly with proper permissions
- [x] Test API call functionality
- [x] Test refresh button functionality
- [x] Test error handling scenarios
- [x] Test responsive design

## Technical Notes
- Use existing permission system pattern (`@permission_required('pxe.can_access_rma_dhcp_leases')`)
- Follow existing RMA view patterns for consistency
- Use requests library for API calls with timeout handling
- Implement AJAX for refresh functionality to avoid full page reload
- Use existing CSS/JS frameworks for consistent styling