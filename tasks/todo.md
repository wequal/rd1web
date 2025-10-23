# RMA General TEST Implementation - TODO List

## Implementation Plan

This document tracks the implementation of the RMA General TEST page under RMA Management.

## Overview
Create a new page "RMA General TEST" under RMA Management, positioned after RMA GPU Test. This page is similar to RMA GPU TEST but adapted for general system testing with different parameters.

## Key Changes from RMA GPU TEST
1. **Base SN → System SN**: Field renamed, PXE script parameter changes from `base_sn=` to `sys_sn=`
2. **BMC IP → NIC MAC**: Replace dropdown with text input field that accepts and normalizes MAC addresses
3. **Tests**: Only "Default" test option (all other tests removed)
4. **Golden Status Panel**: Removed entirely
5. **Permission**: New permission `can_access_rma_general_test` (not assigned to anyone initially)
6. **Navigation**: Placed below RMA GPU TEST in sidebar

## Implementation Tasks

### 1. Database Model Updates ✅
- [x] Add `can_access_rma_general_test` permission to PxeEntry model in `rd1web/pxe/models.py`
- [x] Permission added between `can_access_rma_pxe` and `can_access_rma_dhcp_leases`

### 2. Forms Creation ✅
- [x] Create `RmaGeneralForm` class in `rd1web/pxe/form.py`
- [x] Add `system_sn` field (CharField, replaces base_sn)
- [x] Add `rma_number` field (CharField)
- [x] Add `nic_mac` field (CharField with MAC normalization)
- [x] Add `image` field (same choices as RmaForm)
- [x] Add `remove` and `check` BooleanFields
- [x] Implement MAC normalization in `clean_nic_mac()` method
- [x] MAC formats supported: `ac:1f:6b:35:6f:19`, `ac-1f-6b-35-6f-19`, `ac1f6b356f19`
- [x] Normalized format: `ac1f6b356f19` (lowercase, no separators)

### 3. View Implementation ✅
- [x] Create new view file `rd1web/pxe/views/rma_general_test.py`
- [x] Add `@login_required` and `@permission_required('pxe.can_access_rma_general_test')` decorators
- [x] Implement form submission handling with system_sn instead of base_sn
- [x] Parse and normalize nic_mac field
- [x] Pass normalized MAC to PXE script
- [x] PXE script command: `/srv/share/scripts/rma_pxe_generation {normalized_mac} {image} sys_sn={system_sn} {rma_number} default`
- [x] Store parameters with `sys_sn` key instead of `base_sn`
- [x] Implement Remove action
- [x] Implement Check action
- [x] No golden number logic

### 4. Template Creation ✅
- [x] Create `rd1web/templates/features/rma_general_test.html`
- [x] Copy base structure from `rma_pxe.html`
- [x] Update page title to "RMA General TEST"
- [x] Change field label "Base SN" to "System SN"
- [x] Change field label "BMC IP" to "NIC MAC"
- [x] Update NIC MAC to text input with placeholder showing acceptable formats
- [x] Show only "Default" test option (informational alert, no checkboxes)
- [x] Remove Golden Status panel entirely
- [x] Remove ECO Number section
- [x] Remove GPU Model section
- [x] Remove Cooling section
- [x] Remove Firmware Update checkbox
- [x] Update help modal text
- [x] Simplify JavaScript (no test validation complexity, no ECO/firmware logic, no golden linking)

### 5. URL Configuration ✅
- [x] Import `rma_general_test` view in `rd1web/pxe/urls.py`
- [x] Add URL pattern `path('rma/general-test/', rma_general_test, name='rma_general_test')`
- [x] Positioned after RMA PXE URL

### 6. Navigation Update ✅
- [x] Update `rd1web/templates/partials/sidebar.html`
- [x] Add navigation link after RMA GPU TEST
- [x] Use `perms.pxe.can_access_rma_general_test` permission check
- [x] Icon: `fas fa-vial`
- [x] Label: "RMA General TEST"

### 7. Database Migration ✅
- [x] Generate migration for new permission: `python3 rd1web/manage.py makemigrations`
  - Migration file created: `rd1web/pxe/migrations/0022_alter_pxeentry_options.py`
- [x] Run migration: `python3 rd1web/manage.py migrate`
  - Applied successfully: `pxe.0022_alter_pxeentry_options`

## Testing Checklist

Once migration is complete, verify:
- [ ] Permission added to database
- [ ] Form validates and normalizes MAC addresses correctly
  - Test: `ac:1f:6b:35:6f:19` → `ac1f6b356f19`
  - Test: `ac-1f-6b-35-6f-19` → `ac1f6b356f19`
  - Test: `ac1f6b356f19` → `ac1f6b356f19`
  - Test: `AC:1F:6B:35:6F:19` → `ac1f6b356f19`
- [ ] PXE entries created with correct parameters (sys_sn instead of base_sn)
- [ ] Remove action works correctly
- [ ] Check action works correctly
- [ ] Sidebar link appears only for users with permission
- [ ] Page accessible only with permission (403 otherwise)
- [ ] No code duplication between GPU TEST and General TEST
- [ ] PXE script receives correct parameters: `{mac} {image} sys_sn={system_sn} {rma_number} default`

## Files Modified/Created

### Modified Files:
1. `rd1web/pxe/models.py` - Added permission
2. `rd1web/pxe/form.py` - Added RmaGeneralForm
3. `rd1web/pxe/urls.py` - Added URL pattern and import
4. `rd1web/templates/partials/sidebar.html` - Added navigation link

### Created Files:
1. `rd1web/pxe/views/rma_general_test.py` - New view file
2. `rd1web/templates/features/rma_general_test.html` - New template
3. `tasks/todo.md` - This file

## Notes

- Permission is not assigned to any users by default - must be manually granted via Django admin
- MAC address normalization removes all separators (`:` and `-`) and converts to lowercase
- PXE script parameter format changed from `{base_sn}` to `sys_sn={system_sn}` (includes prefix)
- Tests parameter is always `default` (no user selection needed)
- No golden number dependency or status panel in this version
- All form styling matches existing RMA GPU TEST page for consistency
