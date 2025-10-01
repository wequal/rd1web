# RMA GPU TEST Page Enhancement - Implementation Plan

## Overview
Enhance the RMA GPU TEST page with Golden Number availability tracking, user linking system, and improved UI layout.

## Requirements Summary
1. Remove RMA Testing Guide from RMA GPU TEST page
2. Layout: Left side = RMA GPU TEST Configuration, Right side = Golden status panel
3. Add 'link' column to RMA Testing DB (ForeignKey to User, can be null/empty)
4. Golden status displays all Golden Numbers with availability indicators:
   - Linked to user: show username + red circle icon
   - Available (not linked): show green circle icon
5. Users can link available goldens; only linked user can unlink their own golden
6. Add permission "can_force_unlink_golden" - users with this permission can unlink any golden
7. Change BMC IP field to dropdown - users only see BMC IPs linked to them

---

## Implementation Tasks

### Task 1: Update RMA Testing DB Model ✅
- [x] Add `linked_user` field as ForeignKey to User model (null=True, blank=True)
- [x] Add new permission `can_force_unlink_golden` to model Meta
- [x] Create and run migration for the model changes
- [x] Update admin interface to show linked_user field

**Files modified:**
- `rd1web/pxe/models.py` - Added linked_user field and permission
- Migration `0016_alter_rmatestingdb_options_rmatestingdb_linked_user.py` created and applied

**Expected changes:** Minimal impact - just adding one field and one permission to existing model

---

### Task 2: Update RMA PXE Form ✅
- [x] Change `bmc_ip` field from CharField to ChoiceField
- [x] Add method to dynamically populate BMC IP choices based on current user's linked entries
- [x] Update form initialization to accept user parameter

**Files modified:**
- `rd1web/pxe/form.py` - Modified RmaForm class with __init__ method

**Expected changes:** Minimal impact - only changing one field type in the form

---

### Task 3: Update RMA PXE View ✅
- [x] Pass current user to RmaForm initialization
- [x] Add logic to fetch golden status data for display
- [x] Add permission checks for force unlink
- [x] Pass golden entries and permission flag to template

**Files modified:**
- `rd1web/pxe/views/rma_pxe.py` - Updated rma_pxe view

**Expected changes:** Minimal impact - enhancing existing view with new functionality

---

### Task 4: Update RMA PXE Template Layout ✅
- [x] Remove "RMA Testing Guide" panel
- [x] Add "Golden Status" panel on right side (col-lg-4)
- [x] Display all golden numbers from RmaTestingDb
- [x] Show availability status with color-coded icons (green=available, red=linked)
- [x] Add link/unlink buttons based on user permissions
- [x] Maintain proper layout with Configuration card on left

**Files modified:**
- `rd1web/templates/features/rma_pxe.html` - Replaced guide panel with golden status panel

**Expected changes:** Minimal impact - replacing one panel with another, maintaining same structure

---

### Task 5: Add JavaScript for Golden Linking ✅
- [x] Add AJAX functions for link/unlink operations
- [x] Add real-time UI updates when linking/unlinking
- [x] Add confirmation dialogs for link/unlink operations
- [x] Add error handling and user feedback
- [x] Add CSRF token handling

**Files modified:**
- `rd1web/templates/features/rma_pxe.html` - Added JavaScript in scripts block

**Expected changes:** Minimal impact - only adding new JavaScript functionality

---

### Task 6: Update RMA Testing DB Views ✅
- [x] Add API endpoint for linking golden numbers
- [x] Add API endpoint for unlinking golden numbers
- [x] Add permission checks in views
- [x] Return JSON responses for AJAX calls
- [x] Add validation for already linked/unlinked status

**Files modified:**
- `rd1web/pxe/views/rma_testing_db.py` - Added golden_link and golden_unlink views

**Expected changes:** Minimal impact - adding new API endpoints

---

### Task 7: Update URL Configuration ✅
- [x] Import golden_link and golden_unlink views
- [x] Add URL routes for golden link/unlink API endpoints

**Files modified:**
- `rd1web/pxe/urls.py` - Added new URL patterns

**Expected changes:** Minimal impact - just adding new URL patterns

---

### Task 8: Testing
- [ ] Test BMC IP dropdown shows only user's linked entries
- [ ] Test golden linking/unlinking functionality
- [ ] Test permission system for force unlink
- [ ] Test UI layout and responsiveness
- [ ] Test with multiple users simultaneously

---

## Database Changes
**New field:** `RmaTestingDb.linked_user` (ForeignKey to User, null=True, blank=True)
**New permission:** `pxe.can_force_unlink_golden`

## UI Changes
- Remove RMA Testing Guide panel
- Add Golden Status panel showing:
  - Golden Number
  - Availability status (icon: green circle = available, red circle = linked)
  - Linked username (if applicable)
  - Link/Unlink button (based on permissions)

## Permission Logic
1. Any user can link an available (unlinked) golden number
2. Only the linked user can unlink their own golden number
3. Users with `can_force_unlink_golden` permission can unlink any golden number

## Estimated Impact
- **Low risk** - All changes are additive or non-breaking
- **Minimal impact** - Only affects RMA GPU TEST page and RMA Testing DB
- **No breaking changes** - Existing functionality remains intact

---

## Notes
- All changes follow Django best practices
- Maintains existing code structure
- Uses AJAX for smooth user experience
- Proper permission checks at both view and template levels
