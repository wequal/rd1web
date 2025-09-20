from django.urls import path
from django.views.generic import TemplateView
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
from .views.rma_pxe import rma_pxe
from .views.rma_logs import rma_log, rma_view_file
from .views.rma_testing_db import (
    rma_testing_db_list, 
    rma_testing_db_add, 
    rma_testing_db_edit, 
    rma_testing_db_delete, 
    rma_testing_db_get, 
    rma_testing_db_api
)
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
    path('rma/logs/', rma_log, name='rma_log'),
    path('rma/logs/<path:path>/', rma_log, name='rma_log_browse'),
    path('rma/view/<path:path>/', rma_view_file, name='rma_view_file'),
    
    # RMA Testing DB URLs
    path('rma/testing-db/', rma_testing_db_list, name='rma_testing_db'),
    path('rma/testing-db/add/', rma_testing_db_add, name='rma_testing_db_add'),
    path('rma/testing-db/edit/<int:entry_id>/', rma_testing_db_edit, name='rma_testing_db_edit'),
    path('rma/testing-db/delete/<int:entry_id>/', rma_testing_db_delete, name='rma_testing_db_delete'),
    path('rma/testing-db/get/<int:entry_id>/', rma_testing_db_get, name='rma_testing_db_get'),
    path('api/rma/testing-db/', rma_testing_db_api, name='rma_testing_db_api'),
]