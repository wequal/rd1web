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