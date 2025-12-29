from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.db import transaction, connection
import os
import logging
import time

from ..models import FirmwareFile
from ..form import EcoFolderForm, ModelFolderForm, FirmwareInventoryUploadForm

logger = logging.getLogger(__name__)

# Base directory for firmware inventory
FIRMWARE_BASE_DIR = '/srv/share/firmwareinventory'

# Product types configuration
PRODUCT_TYPES = [
    {
        'code': 'H100_AC',
        'name': 'H100 AC',
        'description': 'H100 AC GPU Firmware',
        'has_retimers': True,
        'icon': 'fas fa-microchip',
        'color': 'primary'
    },
    {
        'code': 'H100_LC',
        'name': 'H100 LC',
        'description': 'H100 LC GPU Firmware',
        'has_retimers': True,
        'icon': 'fas fa-microchip',
        'color': 'info'
    },
    {
        'code': 'H200_AC',
        'name': 'H200 AC',
        'description': 'H200 AC GPU Firmware',
        'has_retimers': True,
        'icon': 'fas fa-microchip',
        'color': 'success'
    },
    {
        'code': 'H200_LC',
        'name': 'H200 LC',
        'description': 'H200 LC GPU Firmware',
        'has_retimers': True,
        'icon': 'fas fa-microchip',
        'color': 'warning'
    },
    {
        'code': 'B200_AC',
        'name': 'B200 AC',
        'description': 'B200 AC GPU Firmware',
        'has_retimers': False,
        'icon': 'fas fa-server',
        'color': 'danger'
    },
    {
        'code': 'B200_LC',
        'name': 'B200 LC',
        'description': 'B200 LC GPU Firmware',
        'has_retimers': False,
        'icon': 'fas fa-server',
        'color': 'secondary'
    },
    {
        'code': 'B300_AC',
        'name': 'B300 AC',
        'description': 'B300 AC GPU Firmware',
        'has_retimers': False,
        'icon': 'fas fa-server',
        'color': 'dark'
    },
    {
        'code': 'B300_LC',
        'name': 'B300 LC',
        'description': 'B300 LC GPU Firmware',
        'has_retimers': False,
        'icon': 'fas fa-server',
        'color': 'primary'
    },
    {
        'code': 'pcie',
        'name': 'PCIe GPU',
        'description': 'PCIe GPU Firmware (organized by model)',
        'has_retimers': False,
        'icon': 'fas fa-plug',
        'color': 'dark'
    },
]


def get_product_info(product_code):
    """Get product information by code"""
    for product in PRODUCT_TYPES:
        if product['code'] == product_code:
            return product
    return None


@login_required
@permission_required('pxe.can_access_firmware_inventory', raise_exception=True)
def firmware_inventory_model_list(request):
    """List all models under pcie product type"""
    
    product_type = 'pcie'
    product_info = get_product_info(product_type)
    
    # Get model folders from filesystem
    pcie_dir = os.path.join(FIRMWARE_BASE_DIR, product_type)
    models = []
    
    if os.path.exists(pcie_dir):
        try:
            from django.db.models import Count
            from datetime import datetime
            
            # Get all ECO counts per model in ONE query
            eco_counts = dict(
                FirmwareFile.objects.filter(product_type=product_type)
                .values('model')
                .annotate(count=Count('eco_number', distinct=True))
                .values_list('model', 'count')
            )
            
            for item in os.listdir(pcie_dir):
                item_path = os.path.join(pcie_dir, item)
                if os.path.isdir(item_path):
                    # Get ECO count from dictionary
                    eco_count = eco_counts.get(item, 0)
                    
                    # Get last modified time
                    mtime = os.path.getmtime(item_path)
                    last_modified = datetime.fromtimestamp(mtime)
                    
                    models.append({
                        'model_name': item,
                        'eco_count': eco_count,
                        'last_modified': last_modified,
                    })
            
            # Sort by model name
            models.sort(key=lambda x: x['model_name'])
            
            logger.info(f"Listed {len(models)} PCIe models")
            
        except Exception as e:
            logger.error(f"Error listing PCIe models: {e}")
            messages.error(request, f'Error listing PCIe models: {str(e)}')
            connection.close()
    
    context = {
        'product_type': product_type,
        'product_info': product_info,
        'models': models,
        'model_form': ModelFolderForm(),
    }
    
    return render(request, 'features/firmware_inventory_model_list.html', context)


@login_required
@permission_required('pxe.can_access_firmware_inventory', raise_exception=True)
@require_http_methods(["POST"])
def firmware_inventory_model_create(request):
    """Create a new model folder under pcie (AJAX endpoint)"""
    
    product_type = 'pcie'
    form = ModelFolderForm(request.POST)
    
    if form.is_valid():
        model_name = form.cleaned_data['model_name']
        
        # Create directory
        model_dir = os.path.join(FIRMWARE_BASE_DIR, product_type, model_name)
        
        try:
            if os.path.exists(model_dir):
                return JsonResponse({
                    'success': False,
                    'error': f'Model folder "{model_name}" already exists'
                }, status=400)
            
            os.makedirs(model_dir, exist_ok=True)
            logger.info(f"Created PCIe model folder: {model_dir} by user {request.user.username}")
            
            return JsonResponse({
                'success': True,
                'message': f'Model folder "{model_name}" created successfully',
                'model_name': model_name
            })
            
        except Exception as e:
            logger.error(f"Error creating model folder {model_dir}: {e}")
            return JsonResponse({
                'success': False,
                'error': f'Failed to create model folder: {str(e)}'
            }, status=500)
    else:
        errors = form.errors.as_json()
        return JsonResponse({
            'success': False,
            'error': 'Invalid form data',
            'errors': errors
        }, status=400)


@login_required
@permission_required('pxe.can_access_firmware_inventory', raise_exception=True)
@require_http_methods(["POST"])
def firmware_inventory_model_delete(request, model_name):
    """Delete an entire model folder and all its ECOs (AJAX endpoint)"""
    
    product_type = 'pcie'
    try:
        import shutil
        
        # Get the model directory path
        model_dir = os.path.join(FIRMWARE_BASE_DIR, product_type, model_name)
        
        if not os.path.exists(model_dir):
            return JsonResponse({
                'success': False,
                'error': f'Model folder "{model_name}" does not exist'
            }, status=404)
        
        # Delete all database records for this model
        deleted_count = FirmwareFile.objects.filter(
            product_type=product_type,
            model=model_name
        ).delete()[0]
        
        # Delete the model folder from filesystem
        try:
            shutil.rmtree(model_dir)
            logger.info(f"Deleted PCIe model folder: {model_dir} ({deleted_count} DB records) by user {request.user.username}")
        except Exception as e:
            logger.error(f"Error deleting model folder {model_dir}: {e}")
            return JsonResponse({
                'success': False,
                'error': f'Failed to delete model folder from filesystem: {str(e)}'
            }, status=500)
        
        return JsonResponse({
            'success': True,
            'message': f'Model folder "{model_name}" and all its contents deleted successfully'
        })
        
    except Exception as e:
        logger.error(f"Error deleting PCIe model folder {model_name}: {e}")
        connection.close()
        return JsonResponse({
            'success': False,
            'error': f'Failed to delete model folder: {str(e)}'
        }, status=500)


@login_required
@permission_required('pxe.can_access_firmware_inventory', raise_exception=True)
def firmware_inventory_main(request):
    """Main page displaying all product types as cards"""
    
    context = {
        'product_types': PRODUCT_TYPES,
    }
    
    return render(request, 'features/firmware_inventory_main.html', context)


@login_required
@permission_required('pxe.can_access_firmware_inventory', raise_exception=True)
def firmware_inventory_eco_list(request, product_type=None, model=None):
    """List all ECO folders for a specific product type (and model if pcie)"""
    
    # If no product_type provided, check if it's in the path or default to pcie if model exists
    if not product_type:
        if model:
            product_type = 'pcie'
        else:
            messages.error(request, 'Product type missing')
            return redirect('firmware_inventory')
            
    # Validate product type
    product_info = get_product_info(product_type)
    if not product_info:
        messages.error(request, f'Invalid product type: {product_type}')
        return redirect('firmware_inventory')
    
    # If pcie but no model specified, redirect to model list
    if product_type == 'pcie' and not model:
        return redirect('firmware_inventory_model_list')
    
    # Get ECO folders from filesystem
    if product_type == 'pcie':
        product_dir = os.path.join(FIRMWARE_BASE_DIR, product_type, model)
    else:
        product_dir = os.path.join(FIRMWARE_BASE_DIR, product_type)
        
    eco_folders = []
    
    if os.path.exists(product_dir):
        try:
            from django.db.models import Count
            from datetime import datetime
            
            # Get all file counts in ONE query (fixes N+1 problem)
            query_params = {'product_type': product_type}
            if product_type == 'pcie':
                query_params['model'] = model
                
            file_counts = dict(
                FirmwareFile.objects.filter(**query_params)
                .values('eco_number')
                .annotate(count=Count('id'))
                .values_list('eco_number', 'count')
            )
            
            for item in os.listdir(product_dir):
                item_path = os.path.join(product_dir, item)
                if os.path.isdir(item_path):
                    # Get file count from dictionary (no additional query)
                    file_count = file_counts.get(item, 0)
                    
                    # Get last modified time
                    mtime = os.path.getmtime(item_path)
                    last_modified = datetime.fromtimestamp(mtime)
                    
                    eco_folders.append({
                        'eco_number': item,
                        'file_count': file_count,
                        'last_modified': last_modified,
                    })
            
            # Sort by ECO number
            eco_folders.sort(key=lambda x: x['eco_number'])
            
            logger.info(f"Listed {len(eco_folders)} ECO folders for {product_type}{'/' + model if model else ''}")
            
        except Exception as e:
            logger.error(f"Error listing ECO folders for {product_type}: {e}")
            messages.error(request, f'Error listing ECO folders: {str(e)}')
            connection.close()  # Ensure connection is released on error
    
    context = {
        'product_type': product_type,
        'product_info': product_info,
        'model': model,
        'eco_folders': eco_folders,
        'eco_form': EcoFolderForm(),
    }
    
    return render(request, 'features/firmware_inventory_eco_list.html', context)


@login_required
@permission_required('pxe.can_access_firmware_inventory', raise_exception=True)
@require_http_methods(["POST"])
def firmware_inventory_eco_create(request, product_type=None, model=None):
    """Create a new ECO folder (AJAX endpoint)"""
    
    if not product_type and model:
        product_type = 'pcie'
        
    # Validate product type
    product_info = get_product_info(product_type)
    if not product_info:
        return JsonResponse({
            'success': False,
            'error': f'Invalid product type: {product_type}'
        }, status=400)
    
    # If pcie but no model specified
    if product_type == 'pcie' and not model:
        return JsonResponse({
            'success': False,
            'error': 'Model must be specified for PCIe product type'
        }, status=400)
    
    form = EcoFolderForm(request.POST)
    
    if form.is_valid():
        eco_number = form.cleaned_data['eco_number']
        
        # Create directory
        if product_type == 'pcie':
            eco_dir = os.path.join(FIRMWARE_BASE_DIR, product_type, model, eco_number)
        else:
            eco_dir = os.path.join(FIRMWARE_BASE_DIR, product_type, eco_number)
        
        try:
            if os.path.exists(eco_dir):
                return JsonResponse({
                    'success': False,
                    'error': f'ECO folder "{eco_number}" already exists'
                }, status=400)
            
            os.makedirs(eco_dir, exist_ok=True)
            logger.info(f"Created ECO folder: {eco_dir} by user {request.user.username}")
            
            return JsonResponse({
                'success': True,
                'message': f'ECO folder "{eco_number}" created successfully',
                'eco_number': eco_number
            })
            
        except Exception as e:
            logger.error(f"Error creating ECO folder {eco_dir}: {e}")
            return JsonResponse({
                'success': False,
                'error': f'Failed to create ECO folder: {str(e)}'
            }, status=500)
    else:
        errors = form.errors.as_json()
        return JsonResponse({
            'success': False,
            'error': 'Invalid form data',
            'errors': errors
        }, status=400)


@login_required
@permission_required('pxe.can_access_firmware_inventory', raise_exception=True)
def firmware_inventory_eco_detail(request, product_type=None, eco_number=None, model=None):
    """Manage firmware files in an ECO folder"""
    
    if not product_type and model:
        product_type = 'pcie'
        
    # Validate product type
    product_info = get_product_info(product_type)
    if not product_info:
        messages.error(request, f'Invalid product type: {product_type}')
        return redirect('firmware_inventory')
    
    # If pcie but no model specified
    if product_type == 'pcie' and not model:
        return redirect('firmware_inventory_model_list')
    
    # Verify ECO folder exists
    if product_type == 'pcie':
        eco_dir = os.path.join(FIRMWARE_BASE_DIR, product_type, model, eco_number)
    else:
        eco_dir = os.path.join(FIRMWARE_BASE_DIR, product_type, eco_number)
        
    if not os.path.exists(eco_dir):
        messages.error(request, f'ECO folder "{eco_number}" does not exist')
        if product_type == 'pcie':
            return redirect('firmware_inventory_pcie_eco_list', model=model)
        else:
            return redirect('firmware_inventory_eco_list', product_type=product_type)
    
    # Get existing firmware files from database
    query_params = {
        'product_type': product_type,
        'eco_number': eco_number
    }
    if product_type == 'pcie':
        query_params['model'] = model
        
    firmware_files = FirmwareFile.objects.filter(**query_params).select_related('uploaded_by').order_by('file_type')
    
    # Create upload form
    upload_form = FirmwareInventoryUploadForm(product_type=product_type)
    
    context = {
        'product_type': product_type,
        'product_info': product_info,
        'model': model,
        'eco_number': eco_number,
        'firmware_files': firmware_files,
        'upload_form': upload_form,
    }
    
    return render(request, 'features/firmware_inventory_eco_detail.html', context)


@login_required
@permission_required('pxe.can_access_firmware_inventory', raise_exception=True)
@require_http_methods(["POST"])
def firmware_inventory_file_upload(request, product_type=None, eco_number=None, model=None):
    """Handle firmware file uploads"""
    
    # Handle URL kwargs for PCIe routes
    if not product_type and model:
        product_type = 'pcie'
    
    # For standard routes, product_type and eco_number come from URL path
    # They should not be None at this point unless there's a routing issue
    if not product_type or not eco_number:
        messages.error(request, 'Missing required parameters for file upload')
        return redirect('firmware_inventory')
        
    # Validate product type
    product_info = get_product_info(product_type)
    if not product_info:
        messages.error(request, f'Invalid product type: {product_type}')
        return redirect('firmware_inventory')
        
    # If pcie but no model specified
    if product_type == 'pcie' and not model:
        messages.error(request, 'Model must be specified for PCIe upload')
        return redirect('firmware_inventory_model_list')
    
    # Verify ECO folder exists
    if product_type == 'pcie':
        eco_dir = os.path.join(FIRMWARE_BASE_DIR, product_type, model, eco_number)
    else:
        eco_dir = os.path.join(FIRMWARE_BASE_DIR, product_type, eco_number)
        
    if not os.path.exists(eco_dir):
        messages.error(request, f'ECO folder "{eco_number}" does not exist')
        if product_type == 'pcie':
            return redirect('firmware_inventory_pcie_eco_list', model=model)
        else:
            return redirect('firmware_inventory_eco_list', product_type=product_type)
    
    form = FirmwareInventoryUploadForm(request.POST, request.FILES, product_type=product_type)
    
    if form.is_valid():
        uploaded_count = 0
        errors = []
        saved_files_info = []
        
        # Define file type mapping
        file_type_mapping = {
            'gpu_file': ['GPU'],
            'retimer_5_file': ['retimer_5'],
        }
        
        # PHASE 1: Save files to disk
        for field_name, file_types in file_type_mapping.items():
            if field_name not in form.cleaned_data:
                continue
                
            uploaded_file = form.cleaned_data.get(field_name)
            if not uploaded_file:
                continue
            
            file_type = file_types[0]
            
            try:
                # Get file extension
                original_filename = uploaded_file.name
                _, file_extension = os.path.splitext(original_filename)
                
                # Generate new filename
                if product_type == 'pcie':
                    new_filename = f"pcie_{model}_{eco_number}_{file_type}{file_extension}"
                else:
                    new_filename = f"{product_type}_{eco_number}_{file_type}{file_extension}"
                    
                file_path = os.path.join(eco_dir, new_filename)
                
                # Save file to disk
                with open(file_path, 'wb+') as destination:
                    for chunk in uploaded_file.chunks():
                        destination.write(chunk)
                
                # Get file size
                file_size = os.path.getsize(file_path)
                
                # Store info for database update
                saved_files_info.append({
                    'file_type': file_type,
                    'filename': new_filename,
                    'original_filename': original_filename,
                    'file_path': file_path,
                    'file_size': file_size,
                })
                
                logger.info(f"Saved file to disk: {new_filename}")
                
            except Exception as e:
                error_msg = f"Error saving {file_type} to disk: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
        
        # Handle combined retimer_0_1_2_3_4_6_7_file
        combined_file = form.cleaned_data.get('retimer_0_1_2_3_4_6_7_file')
        if combined_file:
            # Create 7 copies for retimer_0, 1, 2, 3, 4, 6, 7
            for retimer_num in [0, 1, 2, 3, 4, 6, 7]:
                file_type = f'retimer_{retimer_num}'
                try:
                    # Get file extension
                    original_filename = combined_file.name
                    _, file_extension = os.path.splitext(original_filename)
                    
                    # Generate new filename
                    if product_type == 'pcie':
                        new_filename = f"pcie_{model}_{eco_number}_{file_type}{file_extension}"
                    else:
                        new_filename = f"{product_type}_{eco_number}_{file_type}{file_extension}"
                        
                    file_path = os.path.join(eco_dir, new_filename)
                    
                    # Save file to disk
                    combined_file.seek(0)
                    with open(file_path, 'wb+') as destination:
                        for chunk in combined_file.chunks():
                            destination.write(chunk)
                    
                    # Get file size
                    file_size = os.path.getsize(file_path)
                    
                    # Store info for database update
                    saved_files_info.append({
                        'file_type': file_type,
                        'filename': new_filename,
                        'original_filename': original_filename,
                        'file_path': file_path,
                        'file_size': file_size,
                    })
                    
                    logger.info(f"Saved file to disk: {new_filename}")
                    
                except Exception as e:
                    error_msg = f"Error saving {file_type} to disk: {str(e)}"
                    errors.append(error_msg)
                    logger.error(error_msg)
        
        # PHASE 2: Update database
        if saved_files_info:
            db_start_time = time.time()
            
            try:
                with transaction.atomic():
                    user = request.user
                    
                    # Single query to find existing files
                    file_types = [f['file_type'] for f in saved_files_info]
                    db_filter = {
                        'product_type': product_type,
                        'eco_number': eco_number,
                        'file_type__in': file_types
                    }
                    if product_type == 'pcie':
                        db_filter['model'] = model
                    else:
                        db_filter['model__isnull'] = True
                        
                    existing_files = {
                        (f.product_type, f.model, f.eco_number, f.file_type): f
                        for f in FirmwareFile.objects.filter(**db_filter).select_for_update()
                    }
                    
                    # Separate updates and creates
                    to_update = []
                    to_create = []
                    
                    for file_info in saved_files_info:
                        key = (product_type, model, eco_number, file_info['file_type'])
                        
                        if key in existing_files:
                            # Update existing record
                            firmware_file = existing_files[key]
                            firmware_file.filename = file_info['filename']
                            firmware_file.original_filename = file_info['original_filename']
                            firmware_file.file_path = file_info['file_path']
                            firmware_file.file_size = file_info['file_size']
                            firmware_file.uploaded_by = user
                            to_update.append(firmware_file)
                        else:
                            # Create new record
                            to_create.append(FirmwareFile(
                                product_type=product_type,
                                model=model,
                                eco_number=eco_number,
                                file_type=file_info['file_type'],
                                filename=file_info['filename'],
                                original_filename=file_info['original_filename'],
                                file_path=file_info['file_path'],
                                file_size=file_info['file_size'],
                                uploaded_by=user,
                            ))
                    
                    # Bulk operations
                    if to_update:
                        FirmwareFile.objects.bulk_update(
                            to_update,
                            ['filename', 'original_filename', 'file_path', 'file_size', 'uploaded_by', 'updated_at']
                        )
                    
                    if to_create:
                        FirmwareFile.objects.bulk_create(to_create)
                    
                    uploaded_count = len(to_update) + len(to_create)
                
                db_duration = time.time() - db_start_time
                logger.info(f"Firmware DB update: {db_duration*1000:.0f}ms for {uploaded_count} files by {user.username}")
                    
            except Exception as e:
                error_msg = f"Error updating database records: {str(e)}"
                errors.append(error_msg)
                logger.error(error_msg)
                connection.close()
        
        if uploaded_count > 0:
            messages.success(request, f'Successfully uploaded {uploaded_count} firmware file(s)')
        
        if errors:
            for error in errors:
                messages.error(request, error)
        
    else:
        # Display form errors properly
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f'{field}: {error}')
        if form.non_field_errors():
            for error in form.non_field_errors():
                messages.error(request, str(error))
    
    if product_type == 'pcie':
        return redirect('firmware_inventory_pcie_eco_detail', model=model, eco_number=eco_number)
    else:
        return redirect('firmware_inventory_eco_detail', product_type=product_type, eco_number=eco_number)


@login_required
@permission_required('pxe.can_access_firmware_inventory', raise_exception=True)
@require_http_methods(["POST"])
def firmware_inventory_file_delete(request, file_id):
    """Delete a firmware file (AJAX endpoint)"""
    
    try:
        firmware_file = get_object_or_404(FirmwareFile, id=file_id)
        
        # Delete file from filesystem
        if os.path.exists(firmware_file.file_path):
            try:
                os.remove(firmware_file.file_path)
                logger.info(f"Deleted firmware file: {firmware_file.file_path} by user {request.user.username}")
            except Exception as e:
                logger.error(f"Error deleting file {firmware_file.file_path}: {e}")
                return JsonResponse({
                    'success': False,
                    'error': f'Failed to delete file from filesystem: {str(e)}'
                }, status=500)
        
        # Delete database record
        filename = firmware_file.filename
        firmware_file.delete()
        
        return JsonResponse({
            'success': True,
            'message': f'File "{filename}" deleted successfully'
        })
        
    except Exception as e:
        logger.error(f"Error deleting firmware file ID {file_id}: {e}")
        connection.close()  # Ensure connection is released on error
        return JsonResponse({
            'success': False,
            'error': f'Failed to delete file: {str(e)}'
        }, status=500)


@login_required
@permission_required('pxe.can_access_firmware_inventory', raise_exception=True)
@require_http_methods(["POST"])
def firmware_inventory_eco_delete(request, product_type=None, eco_number=None, model=None):
    """Delete an entire ECO folder and all its firmware files (AJAX endpoint)"""
    
    if not product_type and model:
        product_type = 'pcie'
        
    try:
        import shutil
        
        # Validate product type
        product_info = get_product_info(product_type)
        if not product_info:
            return JsonResponse({
                'success': False,
                'error': f'Invalid product type: {product_type}'
            }, status=400)
        
        # Get the ECO directory path
        if product_type == 'pcie':
            if not model:
                return JsonResponse({
                    'success': False,
                    'error': 'Model must be specified for PCIe ECO deletion'
                }, status=400)
            eco_dir = os.path.join(FIRMWARE_BASE_DIR, product_type, model, eco_number)
        else:
            eco_dir = os.path.join(FIRMWARE_BASE_DIR, product_type, eco_number)
        
        if not os.path.exists(eco_dir):
            return JsonResponse({
                'success': False,
                'error': f'ECO folder "{eco_number}" does not exist'
            }, status=404)
        
        # Delete all database records for this ECO
        db_filter = {
            'product_type': product_type,
            'eco_number': eco_number
        }
        if product_type == 'pcie':
            db_filter['model'] = model
            
        deleted_count = FirmwareFile.objects.filter(**db_filter).delete()[0]
        
        # Delete the ECO folder from filesystem
        try:
            shutil.rmtree(eco_dir)
            logger.info(f"Deleted ECO folder: {eco_dir} ({deleted_count} DB records) by user {request.user.username}")
        except Exception as e:
            logger.error(f"Error deleting ECO folder {eco_dir}: {e}")
            return JsonResponse({
                'success': False,
                'error': f'Failed to delete ECO folder from filesystem: {str(e)}'
            }, status=500)
        
        return JsonResponse({
            'success': True,
            'message': f'ECO folder "{eco_number}" and {deleted_count} file record(s) deleted successfully'
        })
        
    except Exception as e:
        logger.error(f"Error deleting ECO folder {product_type}/{model+'/' if model else ''}{eco_number}: {e}")
        connection.close()  # Ensure connection is released on error
        return JsonResponse({
            'success': False,
            'error': f'Failed to delete ECO folder: {str(e)}'
        }, status=500)

