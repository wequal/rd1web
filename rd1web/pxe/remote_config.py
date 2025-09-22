"""
Remote connection configuration for PXE services.

This module centralizes all remote server connection configurations
used by both rma_pxe.py and pxe_input.py views.
"""

from fabric import Connection

# Centralized remote connection dictionary
# Contains all remote server connections used across PXE services
remote_dict = {
    # RMA server connection
    'rma': Connection(host="root@10.4.4.80", connect_kwargs={"password": "superrd1"}),
    
    # PXE input location connections
    'us_b3': Connection(host="root@172.31.60.129", connect_kwargs={"password": "superrd1"}),
    'us_b1': Connection(host="root@172.31.58.142", connect_kwargs={"password": "superrd1"}),
    'tw': Connection(host="root@10.135.179.104", connect_kwargs={"password": "superrd1"})
}
