# RMA GPU Test - Conditional Test Options Display

## Task: Show/Hide test options based on selected image

### Requirements:
- When image MI300X or MI325X is selected:
  - Show: Default, Pre GPU TEST
  - Hide: DCGM, FD2, GPU Field Diag
- When other images are selected:
  - Show all test options

### Implementation Plan:

- [x] 1. Add JavaScript function to handle image selection change
  - Listen for change event on image dropdown
  - Check if selected image is MI300X or MI325X
  - Show/hide appropriate test checkboxes

- [x] 2. Test the functionality
  - Verify hiding/showing works correctly
  - Verify form validation still works
  - Verify form submission includes only visible tests

### Files to Modify:
- `rd1web/templates/features/rma_pxe.html` - Add JavaScript logic in scripts block

### Changes Summary:
- Minimal JavaScript addition to control visibility of test options
- No backend changes required
- No database changes required

---

## ✅ COMPLETED

### Implementation Details:

**What was changed:**
- Added JavaScript event handler in `rma_pxe.html` that listens to image selection changes
- When MI300X or MI325X is selected, the script:
  - Hides DCGM, FD2, and GPU Field Diag test options
  - Automatically unchecks them if they were previously selected
  - Only shows Default and Pre GPU TEST options
  - **Automatically checks the Default test checkbox**
- When other images (like Nvidia) are selected:
  - All test options are visible
  - Users can select any combination as before

**Key Features:**
- Automatic initialization on page load
- Clean, minimal code change
- No impact on existing functionality
- Automatic form cleanup (unchecks hidden options)
- Auto-selects Default test for MI300X and MI325X images
