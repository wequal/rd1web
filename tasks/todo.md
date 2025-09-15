# Task: Create Remote Dict Configuration File

## Analysis
Both `rma_pxe.py` and `pxe_input.py` contain hardcoded `remote_dict` dictionaries with fabric Connection objects for remote server access:

- **rma_pxe.py**: Contains connection to RMA server (172.31.35.191)
- **pxe_input.py**: Contains connections to multiple locations (us_b3, us_b1, tw) with different IP addresses

## Plan
Create a centralized configuration file to store remote connection information that can be shared between both files.

## Tasks
- [x] Create `/home/devin/rd1web-dev/rd1web/pxe/remote_config.py` file to store all remote connection configurations
- [x] Move remote_dict definitions from both files into the new configuration file
- [x] Update `rma_pxe.py` to import and use the centralized remote_dict
- [x] Update `pxe_input.py` to import and use the centralized remote_dict
- [x] Test that both files still work correctly after the changes

## Benefits
- Centralized configuration management
- Easier maintenance of connection details
- No code duplication
- Single source of truth for remote connections