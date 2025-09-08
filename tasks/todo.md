# RMA Management Implementation Plan

## Project Overview
Create RMA (Return Merchandise Authorization) management system with:
- Left sidebar RMA Management section (already added)
- RMA Logs page (template log view)
- RMA PXE page (similar to PXE Boot Manager but using RmaForm)

## Task List

### 1. Create RMA PXE View and URL Pattern
- [x] Create RMA PXE view function in views module
- [x] Add RMA PXE URL pattern to urls.py
- [x] Test RMA PXE functionality

### 2. Create RMA PXE Template
- [x] Create RMA PXE HTML template based on PXE template
- [x] Adapt form fields for RmaForm (Base SN, RMA Number, MAC, Image, Tests)
- [x] Update styling and labels for RMA context
- [x] Test template rendering

### 3. Create RMA Logs View and Template
- [x] Create RMA logs view function
- [x] Create RMA logs template (simple log viewing page)
- [x] Add RMA logs URL pattern
- [x] Test RMA logs functionality

### 4. Update URL Configuration
- [x] Add both rma_log and rma_pxe URLs to main urls.py
- [x] Ensure URL names match sidebar links
- [x] Test all URL routing

### 5. Testing and Validation
- [x] Test all RMA pages load correctly
- [x] Test RMA PXE form submission
- [x] Test navigation between pages
- [x] Check for any lint errors

## Implementation Notes
- RmaForm has fields: base_sn, rma_number, mac, image, remove, check, tests
- Use PXE template as base but simplify for RMA-specific fields
- RMA Logs will be a simple template log viewer page
- Keep minimal impact on existing codebase
- No complex logic changes needed

## Files to Create/Modify
- `rd1web/pxe/views/rma_pxe.py` (new)
- `rd1web/pxe/views/rma_logs.py` (new)  
- `rd1web/templates/features/rma_pxe.html` (new)
- `rd1web/templates/features/rma_logs.html` (new)
- `rd1web/pxe/urls.py` (modify)