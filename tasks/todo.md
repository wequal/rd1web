# RMA PXE Cooling Field Update Plan

## Task: Update RMA PXE HTML template to include cooling field

### Background:
- The RMA form (`RmaForm` in `form.py`) has been updated with a `cooling` field with choices: LC and AC
- The view (`rma_pxe.py`) is already handling the cooling field in the form processing
- The HTML template (`rma_pxe.html`) needs to be updated to display the cooling field

### Tasks:
- [x] Add cooling field to the RMA PXE HTML template
- [x] Position the cooling field appropriately in the form layout
- [x] Ensure consistent styling with other form fields
- [x] Add proper icons and labels for the cooling field
- [x] Update the info panel to include cooling information
- [x] Test the form to ensure proper functionality

### Implementation Details:
- Add the cooling field after the tests field (around line 126)
- Use consistent styling with other choice fields
- Include proper FontAwesome icon (thermometer or snowflake)
- Add helpful description text
- Update the sidebar info panel with cooling information

### Minimal Impact:
- Only adding new form field display
- No changes to existing functionality
- No backend changes needed (already implemented)