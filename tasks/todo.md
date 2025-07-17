### Plan to Improve the MAC to IP Feature

- [x] **Backend Optimizations (`rd1web/pxe/views/mac_ip_view.py`)**
    - [x] Refactor `manual_scan_worker` to use bulk database operations (`bulk_create`, `bulk_update`) for better performance.
    - [x] Improve `arp-scan` subprocess error handling by checking the `returncode` and logging `stderr`.
    - [x] Use the `tempfile` module for creating secure temporary files for scan output.
- [x] **Frontend Enhancements (`rd1web/templates/features/mac_ip_results.html`)**
    - [x] Replace full-page reload on scan completion with a dynamic, in-place update of the results table.
    - [x] Fetch new data from the `/api/mac-ip/` endpoint and re-render the table body.
    - [x] Add a visual indicator to the user that the scan is complete and the table has been updated.
- [x] **Enhance MAC Address Search (`rd1web/pxe/views/mac_ip_view.py`)**
    - [x] Modify `mac_ip_results` to handle multiple MAC address formats (e.g., with colons, dashes, or no separators).
    - [x] Use database functions to normalize stored MAC addresses for flexible searching. 

### Plan to Switch Unique Identifier to MAC Address

- [x] **Update Model (`rd1web/pxe/models.py`)**
    - [x] Change unique constraint from (`ip_address`, `subnet_source`) to (`mac_address`, `subnet_source`).
- [x] **Update Scan Logic (`rd1web/pxe/views/mac_ip_view.py`)**
    - [x] Adjust pre-fetch and matching to use MAC instead of IP.
- [x] **Generate and Apply Migration**
    - [x] Run `makemigrations` and `migrate` to update the database schema. 

### Plan to Enhance MAC Address Search Formats

- [x] **Analyze Current Implementation (`rd1web/pxe/views/mac_ip_view.py`)**
    - [x] Review current search logic in `mac_ip_results` function (lines 331-371)
    - [x] Understand current normalization approach that only handles colons
    
- [x] **Update Search Normalization Logic**
    - [x] Add support for multiple MAC addresses separated by space or comma
    - [x] Modify the search query normalization to handle both colons and dashes
    - [x] Update the database annotation to remove both `:` and `-` separators
    - [x] Ensure backward compatibility with existing formats
    
- [ ] **Test MAC Address Format Support**
    - [ ] Verify support for "00:09:0f:09:ac:12" (current format with colons)
    - [ ] Verify support for "00090f09ac12" (no separators - already works)  
    - [ ] Verify support for "0009-0f-09-ac-12" (new format with dashes)
    - [ ] Test multiple MAC addresses: "00:09:0f:09:ac:12 00090f09ac13" and "00:09:0f:09:ac:12,0009-0f-09-ac-13"
    - [ ] Test mixed case scenarios and edge cases
    
- [x] **Update Documentation**
    - [x] Update the search placeholder text to mention supported formats and multiple MAC support
    - [ ] Add help text showing example formats if needed 

### Plan to Fix Django Admin UserActivity Error

**Problem:** Django admin crashes when accessing UserActivity page due to `AttributeError: 'NoneType' object has no attribute 'username'` in the model's `__str__` method.

**Root Cause:** The UserActivity model's user field can be null (`null=True, blank=True`), but the `__str__` method tries to access `self.user.username` without checking if `self.user` exists.

**Tasks:**

- [ ] **Fix UserActivity Model (`rd1web/authentication/models.py`)**
    - [ ] Update the `__str__` method in UserActivity model to handle null user gracefully
    - [ ] Use conditional check to display "Anonymous" or similar when user is None
    - [ ] Ensure minimal impact to existing functionality

- [ ] **Test Fix**
    - [ ] Verify Django admin UserActivity page loads without errors
    - [ ] Confirm that records with null users display properly
    - [ ] Test that normal records with users still display correctly

- [ ] **Validation**
    - [ ] Run the Django development server and access admin
    - [ ] Navigate to UserActivity admin page to confirm no more errors
    - [ ] Check both null and non-null user records display properly 