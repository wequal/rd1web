from django.urls import path
from django.views.generic import TemplateView
from asgiref.sync import async_to_sync
from . import views
from .views.index import index
from .views.pxe_input import pxe_input
from .views.ipmitool import ipmitool, get_firmware_sequence_status
from .views.firmware_update import check_firmware_status, system_reset, get_firmware_info_view
from .views.log_view import log_view
from .views.view_file import view_file
from .views.system_details import system_details, system_list
from .views.kvm_sol import get_kvm_url, start_sol_session, get_system_network_info, debug_system_info, sol_terminal, kvm_viewer
from .views.pcie_file import serve_pcie_file
from .views.remote_control import (
    remote_control,
    remote_kvm,
    remote_start_sol,
    remote_sol_terminal,
)
from .views.archive import archive_system
from .views.mac_ip_view import mac_ip_results, mac_ip_api, manual_scan, scan_status_api
from .views.rma_pxe import (
    rma_pxe, 
    get_eco_numbers_api, 
    get_rma_info_by_bmc, 
    golden_setting_api,
    get_pcie_models_api,
    get_pcie_eco_numbers_api
)
from .views.rma_general_test import rma_general_test
from .views.rma_logs import (
    rma_log,
    rma_view_file,
    rma_download_folder,
    rma_download_folder_async,
    rma_download_folder_status,
    rma_download_zip,
    rma_collect_mi3xx_alllog,
    rma_collect_mi3xx_alllog_status,
    rma_collect_mi3xx_alllog_from_form,
)
from .views.rma_general_logs import rma_general_log, rma_general_view_file
from .views.rma_testing_db import (
    rma_testing_db_list, 
    rma_testing_db_add, 
    rma_testing_db_edit, 
    rma_testing_db_delete, 
    rma_testing_db_get, 
    rma_testing_db_api,
    golden_link,
    golden_unlink
)
from .views.rma_dhcp_leases import rma_dhcp_leases, rma_dhcp_leases_refresh
from .views.rma_statistics import rma_statistics, rma_statistics_api, trigger_scan
from .views.firmware_inventory import (
    firmware_inventory_main,
    firmware_inventory_eco_list,
    firmware_inventory_eco_create,
    firmware_inventory_eco_detail,
    firmware_inventory_eco_delete,
    firmware_inventory_file_upload,
    firmware_inventory_file_delete,
    firmware_inventory_model_list,
    firmware_inventory_model_create,
    firmware_inventory_model_delete,
)
from .views.remote_fw_update import remote_fw_status
from .api.system_api import systems_summary, systems_category


urlpatterns = [
    path('', index, name='index'),
    path('pxe/', pxe_input, name='pxe'),
    path('ipmitool/', ipmitool, name='ipmitool'),
    path('ipmitool/firmware/status/', check_firmware_status, name='check_firmware_status'),
    path('ipmitool/firmware/sequence_status/', get_firmware_sequence_status, name='get_firmware_sequence_status'),
    path('ipmitool/firmware/info/', get_firmware_info_view, name='get_firmware_info'),
    path('ipmitool/system/reset/', system_reset, name='system_reset'),

    path('mac-ip/', mac_ip_results, name='mac_ip_results'),
    path('api/mac-ip/', mac_ip_api, name='mac_ip_api'),
    path('api/mac-ip/scan/', manual_scan, name='manual_scan'),
    path('api/mac-ip/scan/status/', scan_status_api, name='scan_status_api'),
    path('api/systems/summary/', systems_summary, name='systems_summary'),
    path('api/systems/<str:category>/', systems_category, name='systems_category'),
    path('systems/', system_list, name='system_list'),
    path('systems/<str:mac>/', system_details, name='system_details'),
    path('systems/<str:folder_name>/kvm/', get_kvm_url, name='get_kvm_url'),
    path('systems/<str:folder_name>/kvm/viewer/', kvm_viewer, name='kvm_viewer'),
    path('systems/<str:folder_name>/sol/', start_sol_session, name='start_sol_session'),
    path('systems/<str:folder_name>/sol/terminal/', sol_terminal, name='sol_terminal'),
    path('systems/<str:folder_name>/network/', get_system_network_info, name='get_system_network_info'),
    path('systems/<str:folder_name>/debug/', debug_system_info, name='debug_system_info'),
    path('systems/<str:folder_name>/pcie/<str:pcie_file>', serve_pcie_file, name='serve_pcie_file'),
    path('systems/<str:folder_name>/archive/', archive_system, name='archive_system'),
    path('logs/', log_view, name='log_root'),
    path('logs/<path:path>/', log_view, name='log'),
    path('view/<path:path>/', view_file, name='view_file'),

    path('remote-control/kvm/', remote_kvm, name='remote_kvm'),
    path('remote-control/sol/', remote_start_sol, name='remote_start_sol'),
    path('remote-control/sol_terminal/', remote_sol_terminal, name='remote_sol_terminal'),
    
    # RMA Management URLs
    path('rma/pxe/', rma_pxe, name='rma_pxe'),
    path('rma/general-test/', rma_general_test, name='rma_general_test'),
    path('rma/logs/', rma_log, name='rma_log'),
    path('rma/logs/<path:path>/', rma_log, name='rma_log_browse'),
    path('rma/view/<path:path>/', rma_view_file, name='rma_view_file'),
    path('rma/general-logs/', rma_general_log, name='rma_general_log'),
    path('rma/general-logs/<path:path>/', rma_general_log, name='rma_general_log_browse'),
    path('rma/general-view/<path:path>/', rma_general_view_file, name='rma_general_view_file'),
    path('rma/download-folder/<path:path>/', rma_download_folder, name='rma_download_folder'),
    path('rma/download-folder-async/<path:path>/', rma_download_folder_async, name='rma_download_folder_async'),
    path('rma/download-folder-status/<str:task_id>/', rma_download_folder_status, name='rma_download_folder_status'),
    path('rma/download-zip/<str:zip_filename>/', rma_download_zip, name='rma_download_zip'),
    path('rma/collect-mi3xx-alllog/<path:path>/', rma_collect_mi3xx_alllog, name='rma_collect_mi3xx_alllog'),
    path('rma/collect-mi3xx-alllog-status/<str:task_id>/', rma_collect_mi3xx_alllog_status, name='rma_collect_mi3xx_alllog_status'),
    path('rma/collect-mi3xx-alllog-from-form/', rma_collect_mi3xx_alllog_from_form, name='rma_collect_mi3xx_alllog_from_form'),
    path('rma/remote-fw-status/<str:task_id>/', remote_fw_status, name='remote_fw_status'),
    
    # Golden Number Link/Unlink URLs
    path('rma/golden/link/<int:entry_id>/', golden_link, name='golden_link'),
    path('rma/golden/unlink/<int:entry_id>/', golden_unlink, name='golden_unlink'),
    path('rma/golden/setting/<int:entry_id>/', golden_setting_api, name='golden_setting'),
    
    # RMA API URLs
    path('api/rma/eco-numbers/<str:image_type>/', get_eco_numbers_api, name='rma_eco_numbers_api'),
    path('api/rma/pcie/models/', get_pcie_models_api, name='rma_pcie_models_api'),
    path('api/rma/pcie/eco-numbers/<str:model>/', get_pcie_eco_numbers_api, name='rma_pcie_eco_numbers_api'),
    path('api/rma/get-rma-info/<str:bmc_ip>/', get_rma_info_by_bmc, name='get_rma_info_by_bmc'),
    
    # RMA Testing DB URLs
    path('rma/testing-db/', rma_testing_db_list, name='rma_testing_db'),
    path('rma/testing-db/add/', rma_testing_db_add, name='rma_testing_db_add'),
    path('rma/testing-db/edit/<int:entry_id>/', rma_testing_db_edit, name='rma_testing_db_edit'),
    path('rma/testing-db/delete/<int:entry_id>/', rma_testing_db_delete, name='rma_testing_db_delete'),
    path('rma/testing-db/get/<int:entry_id>/', rma_testing_db_get, name='rma_testing_db_get'),
    path('api/rma/testing-db/', rma_testing_db_api, name='rma_testing_db_api'),
    
    # RMA DHCP Leases URLs
    path('rma/dhcp-leases/', rma_dhcp_leases, name='rma_dhcp_leases'),
    path('rma/dhcp-leases/refresh/', rma_dhcp_leases_refresh, name='rma_dhcp_leases_refresh'),
    
    # RMA Statistics URLs
    path('rma/statistics/', rma_statistics, name='rma_statistics'),
    path('api/rma/statistics/', rma_statistics_api, name='rma_statistics_api'),
    path('api/rma/statistics/scan/', trigger_scan, name='rma_statistics_scan'),
    
    # Firmware Inventory URLs
    # IMPORTANT: More specific patterns must come BEFORE generic patterns
    path('rma/firmware-inventory/', firmware_inventory_main, name='firmware_inventory'),
    path('rma/firmware-inventory/file/<int:file_id>/delete/', firmware_inventory_file_delete, name='firmware_inventory_file_delete'),
    
    # PCIe Model Management
    path('rma/firmware-inventory/pcie/models/', firmware_inventory_model_list, name='firmware_inventory_model_list'),
    path('rma/firmware-inventory/pcie/models/create/', firmware_inventory_model_create, name='firmware_inventory_model_create'),
    path('rma/firmware-inventory/pcie/models/<str:model_name>/delete/', firmware_inventory_model_delete, name='firmware_inventory_model_delete'),
    
    # PCIe ECO Management (nested under model)
    path('rma/firmware-inventory/pcie/<str:model>/create-eco/', firmware_inventory_eco_create, {'product_type': 'pcie'}, name='firmware_inventory_pcie_eco_create'),
    path('rma/firmware-inventory/pcie/<str:model>/<str:eco_number>/delete/', firmware_inventory_eco_delete, {'product_type': 'pcie'}, name='firmware_inventory_pcie_eco_delete'),
    path('rma/firmware-inventory/pcie/<str:model>/<str:eco_number>/upload/', firmware_inventory_file_upload, {'product_type': 'pcie'}, name='firmware_inventory_pcie_file_upload'),
    path('rma/firmware-inventory/pcie/<str:model>/<str:eco_number>/', firmware_inventory_eco_detail, {'product_type': 'pcie'}, name='firmware_inventory_pcie_eco_detail'),
    path('rma/firmware-inventory/pcie/<str:model>/', firmware_inventory_eco_list, {'product_type': 'pcie'}, name='firmware_inventory_pcie_eco_list'),
    
    # Standard Product ECO Management
    path('rma/firmware-inventory/<str:product_type>/create-eco/', firmware_inventory_eco_create, name='firmware_inventory_eco_create'),
    path('rma/firmware-inventory/<str:product_type>/<str:eco_number>/delete/', firmware_inventory_eco_delete, name='firmware_inventory_eco_delete'),
    path('rma/firmware-inventory/<str:product_type>/<str:eco_number>/upload/', firmware_inventory_file_upload, name='firmware_inventory_file_upload'),
    path('rma/firmware-inventory/<str:product_type>/<str:eco_number>/', firmware_inventory_eco_detail, name='firmware_inventory_eco_detail'),
    path('rma/firmware-inventory/<str:product_type>/', firmware_inventory_eco_list, name='firmware_inventory_eco_list'),
]
