# RMA GPU Test - Conditional Test Options Display

## Task: Show/Hide test options based on selected image

### Requirements:
- When image MI300X or MI325X is selected:
  - Show: Default, Pre GPU TEST, AGHFC Level 3
  - Hide: DCGM, FD2, GPU Field Diag
- When other images are selected:
  - Show: Default, Pre GPU TEST, DCGM, FD2, GPU Field Diag
  - Hide: AGHFC Level 3

### Implementation Plan:

- [x] 1. Add JavaScript function to handle image selection change
  - Listen for change event on image dropdown
  - Check if selected image is MI300X or MI325X
  - Show/hide appropriate test checkboxes

- [x] 2. Test the functionality
  - Verify hiding/showing works correctly
  - Verify form validation still works
  - Verify form submission includes only visible tests

- [x] 3. Add AGHFC Level 3 test option
  - Add HTML checkbox for AGHFC Level 3
  - Configure visibility based on image selection
  - Update validation logic

### Files Modified:
- `rd1web/templates/features/rma_pxe.html` - Added HTML checkbox and JavaScript logic
- `rd1web/pxe/form.py` - Added test choice (user modified)

### Changes Summary:
- Minimal JavaScript addition to control visibility of test options
- Added AGHFC Level 3 test option with conditional visibility
- No backend logic changes required
- No database changes required

---

## ✅ COMPLETED

### Implementation Details:

**What was changed:**
- Added JavaScript event handler in `rma_pxe.html` that listens to image selection changes
- When MI300X or MI325X is selected, the script:
  - Hides DCGM, FD2, and GPU Field Diag test options
  - Shows AGHFC Level 3 test option
  - Automatically unchecks hidden options if they were previously selected
  - Shows Default, Pre GPU TEST, and AGHFC Level 3 options
  - **Automatically checks the Default test checkbox**
- When other images (like Nvidia) are selected:
  - Shows DCGM, FD2, GPU Field Diag test options
  - Hides AGHFC Level 3 test option
  - Users can select any combination as before

**AGHFC Level 3 Test:**
- Added HTML checkbox with id `id_tests_5`
- Value: `level3_test`
- Label: "AGHFC Level 3" with warning icon
- Visible only for MI300X and MI325X images
- Not auto-checked (only Default is auto-checked)
- Included in validation logic (cannot be combined with Default)

**Key Features:**
- Automatic initialization on page load
- Clean, minimal code change
- No impact on existing functionality
- Automatic form cleanup (unchecks hidden options)
- Auto-selects Default test for MI300X and MI325X images
- Proper validation for all test combinations
