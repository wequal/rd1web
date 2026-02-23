from django.shortcuts import render, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db.models import Q
from django.core.paginator import Paginator
from django.db import transaction
import logging

from ..models import RmaPcieDb
from ..form import RmaPcieDbForm, RmaPcieDbSearchForm
from ..remote_config import remote_dict

logger = logging.getLogger(__name__)


def change(golden_number, bmc_mac, bmc_ip):
    remote_dict["rma"].run(
        f"/srv/share/scripts/rma/rma_fixed_ip {golden_number} {bmc_mac} {bmc_ip} change"
    )


def delete(golden_number, bmc_mac, bmc_ip):
    remote_dict["rma"].run(
        f"/srv/share/scripts/rma/rma_fixed_ip {golden_number} {bmc_mac} {bmc_ip} delete"
    )


@login_required
def rma_pcie_db_list(request):
    """Main view for PCIE DB page with search and pagination (login-only)."""

    search_form = RmaPcieDbSearchForm(request.GET)
    queryset = RmaPcieDb.objects.all()

    if search_form.is_valid():
        search_query = search_form.cleaned_data.get("search")
        if search_query:
            queryset = queryset.filter(
                Q(bmc_mac__icontains=search_query)
                | Q(bmc_ip__icontains=search_query)
                | Q(bmc_password__icontains=search_query)
                | Q(lan0_mac__icontains=search_query)
                | Q(lan1_mac__icontains=search_query)
                | Q(golden_number__icontains=search_query)
            )

    paginator = Paginator(queryset, 20)
    page_number = request.GET.get("page")
    page_obj = paginator.get_page(page_number)

    add_form = RmaPcieDbForm()

    context = {
        "entries": page_obj,
        "search_form": search_form,
        "add_form": add_form,
        "total_entries": queryset.count(),
        # shared-template configuration
        "active_db": "pcie",
        "db_page_title": "PCIE DB",
        "db_table_title": "PCIE Database",
        "empty_table_message": "No PCIE DB entries found. Click Add New Entry to get started.",
        "can_delete": request.user.has_perm("pxe.can_delete_rma_pcie_db"),
        "show_is_golden": False,
        "lan1_required": False,
        # endpoint names (used by template)
        "add_url_name": "rma_pcie_db_add",
        "edit_url_name": "rma_pcie_db_edit",
        "delete_url_name": "rma_pcie_db_delete",
        "get_url_name": "rma_pcie_db_get",
        "api_url_name": "rma_pcie_db_api",
    }

    return render(request, "features/rma_testing_db.html", context)


@login_required
@require_http_methods(["POST"])
def rma_pcie_db_add(request):
    form = RmaPcieDbForm(request.POST)
    if form.is_valid():
        try:
            entry = form.save()
            transaction.commit(change(entry.golden_number, entry.bmc_mac, entry.bmc_ip))
            messages.success(
                request, f"Successfully added PCIE entry for BMC MAC: {entry.bmc_mac}"
            )
            return JsonResponse(
                {
                    "success": True,
                    "message": "Entry added successfully",
                    "entry": {
                        "id": entry.id,
                        "bmc_mac": entry.bmc_mac,
                        "bmc_ip": entry.bmc_ip,
                        "bmc_password": entry.bmc_password,
                        "lan0_mac": entry.lan0_mac,
                        "lan1_mac": entry.lan1_mac,
                        "golden_number": entry.golden_number,
                    },
                }
            )
        except Exception as e:
            logger.error(f"Error adding PCIE DB entry: {e}")
            return JsonResponse(
                {"success": False, "message": f"Error adding entry: {str(e)}"}
            )
    return JsonResponse(
        {
            "success": False,
            "message": "Form validation failed",
            "errors": form.errors,
        }
    )


@login_required
@require_http_methods(["POST"])
def rma_pcie_db_edit(request, entry_id):
    entry = get_object_or_404(RmaPcieDb, id=entry_id)
    form = RmaPcieDbForm(request.POST, instance=entry)
    if form.is_valid():
        try:
            updated_entry = form.save()
            transaction.commit(
                change(updated_entry.golden_number, updated_entry.bmc_mac, updated_entry.bmc_ip)
            )
            messages.success(
                request, f"Successfully updated PCIE entry for BMC MAC: {updated_entry.bmc_mac}"
            )
            return JsonResponse(
                {
                    "success": True,
                    "message": "Entry updated successfully",
                    "entry": {
                        "id": updated_entry.id,
                        "bmc_mac": updated_entry.bmc_mac,
                        "bmc_ip": updated_entry.bmc_ip,
                        "bmc_password": updated_entry.bmc_password,
                        "lan0_mac": updated_entry.lan0_mac,
                        "lan1_mac": updated_entry.lan1_mac,
                        "golden_number": updated_entry.golden_number,
                    },
                }
            )
        except Exception as e:
            logger.error(f"Error updating PCIE DB entry: {e}")
            return JsonResponse(
                {"success": False, "message": f"Error updating entry: {str(e)}"}
            )
    return JsonResponse(
        {
            "success": False,
            "message": "Form validation failed",
            "errors": form.errors,
        }
    )


@login_required
@permission_required("pxe.can_delete_rma_pcie_db", raise_exception=True)
@require_http_methods(["POST"])
def rma_pcie_db_delete(request, entry_id):
    entry = get_object_or_404(RmaPcieDb, id=entry_id)
    try:
        bmc_mac = entry.bmc_mac
        entry.delete()
        transaction.commit(delete(entry.golden_number, entry.bmc_mac, entry.bmc_ip))
        messages.success(request, f"Successfully deleted PCIE entry for BMC MAC: {bmc_mac}")
        return JsonResponse({"success": True, "message": "Entry deleted successfully"})
    except Exception as e:
        logger.error(f"Error deleting PCIE DB entry: {e}")
        return JsonResponse({"success": False, "message": f"Error deleting entry: {str(e)}"})


@login_required
@require_http_methods(["GET"])
def rma_pcie_db_get(request, entry_id):
    entry = get_object_or_404(RmaPcieDb, id=entry_id)
    return JsonResponse(
        {
            "success": True,
            "entry": {
                "id": entry.id,
                "bmc_mac": entry.bmc_mac,
                "bmc_ip": entry.bmc_ip,
                "bmc_password": entry.bmc_password,
                "lan0_mac": entry.lan0_mac,
                "lan1_mac": entry.lan1_mac,
                "golden_number": entry.golden_number,
            },
        }
    )


@login_required
@require_http_methods(["GET"])
def rma_pcie_db_api(request):
    search_value = request.GET.get("search[value]", "")
    start = int(request.GET.get("start", 0))
    length = int(request.GET.get("length", 20))

    queryset = RmaPcieDb.objects.all()
    if search_value:
        queryset = queryset.filter(
            Q(bmc_mac__icontains=search_value)
            | Q(bmc_ip__icontains=search_value)
            | Q(bmc_password__icontains=search_value)
            | Q(lan0_mac__icontains=search_value)
            | Q(lan1_mac__icontains=search_value)
            | Q(golden_number__icontains=search_value)
        )

    total_records = RmaPcieDb.objects.count()
    filtered_records = queryset.count()

    entries = queryset[start : start + length]
    data = []
    for entry in entries:
        data.append(
            {
                "id": entry.id,
                "bmc_mac": entry.bmc_mac,
                "bmc_ip": entry.bmc_ip,
                "bmc_password": entry.bmc_password,
                "lan0_mac": entry.lan0_mac,
                "lan1_mac": entry.lan1_mac,
                "golden_number": entry.golden_number,
            }
        )

    return JsonResponse(
        {
            "draw": int(request.GET.get("draw", 1)),
            "recordsTotal": total_records,
            "recordsFiltered": filtered_records,
            "data": data,
        }
    )

