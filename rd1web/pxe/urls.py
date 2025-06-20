from django.urls import path
from django.views.generic import TemplateView
from . import views
from .views.index import index
from .views.pxe_input import pxe_input
from .views.ipmitool import ipmitool
from .views.log_view import log_view
from .views.view_file import view_file
from .views.system_details import system_details, system_list
from .views.kvm_sol import get_kvm_url, start_sol_session, get_system_network_info, debug_system_info, sol_terminal
from .views.pcie_file import serve_pcie_file
from .views.remote_control import (
    remote_control,
    remote_kvm,
    remote_start_sol,
    remote_sol_terminal,
)
from .views.archive import archive_system


urlpatterns = [
    path('', index, name='index'),
    path('pxe/', pxe_input, name='pxe'),
    path('ipmitool/', ipmitool, name='ipmitool'),
    path('systems/', system_list, name='system_list'),
    path('systems/<str:mac>/', system_details, name='system_details'),
    path('systems/<str:folder_name>/kvm/', get_kvm_url, name='get_kvm_url'),
    path('systems/<str:folder_name>/sol/', start_sol_session, name='start_sol_session'),
    path('systems/<str:folder_name>/sol/terminal/', sol_terminal, name='sol_terminal'),
    path('systems/<str:folder_name>/network/', get_system_network_info, name='get_system_network_info'),
    path('systems/<str:folder_name>/debug/', debug_system_info, name='debug_system_info'),
    path('systems/<str:folder_name>/pcie/<str:pcie_file>', serve_pcie_file, name='serve_pcie_file'),
    path('systems/<str:folder_name>/archive/', archive_system, name='archive_system'),
    path('logs/', log_view, name='log_root'),
    path('logs/<path:path>/', log_view, name='log'),
    path('view/<path:path>/', view_file, name='view_file'),
    path('remote-control/', remote_control, name='remote_control'),
    path('remote-control/kvm/', remote_kvm, name='remote_kvm'),
    path('remote-control/sol/', remote_start_sol, name='remote_start_sol'),
    path('remote-control/sol_terminal/', remote_sol_terminal, name='remote_sol_terminal'),
]