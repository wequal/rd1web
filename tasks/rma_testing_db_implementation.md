# RMA Testing DB Implementation Plan

## Overview
Create a new page under the left sidebar called "RMA Testing DB" that shows an editable database table for users with proper permission controls.

## Requirements
1. **Database Structure**: BMC MAC (unique identifier), BMC IP, BMC unique password, LAN0 MAC, LAN1 MAC
2. **Permission System**: Only Django ADMIN users can grant RMA management permissions in admin panel
3. **Access Control**: Only users with RMA management rights can see this page
4. **Page Name**: "RMA Testing DB"
5. **Location**: Under left sidebar RMA Management section

## Implementation Tasks

### 1. Database Model Creation ✅
- [x] Create RmaTestingDb model in `rd1web/pxe/models.py`
- [x] BMC MAC as CharField with unique constraint
- [x] BMC IP as GenericIPAddressField
- [x] BMC password as CharField
- [x] LAN0 MAC as CharField
- [x] LAN1 MAC as CharField
- [x] Add validation for MAC address formats

### 2. Permission System ✅
- [x] Create custom permission 'can_access_rma_testing_db'
- [x] Set up permission checking in views
- [x] Ensure only superusers/admins can grant this permission

### 3. Forms and Validation ✅
- [x] Create RmaTestingDbForm in `rd1web/pxe/form.py`
- [x] Add MAC address format validation
- [x] Add IP address validation
- [x] Create inline editing forms for table

### 4. View Implementation ✅
- [x] Create view function with permission required decorator
- [x] Implement CRUD operations (Create, Read, Update, Delete)
- [x] Add AJAX endpoints for inline editing
- [x] Add proper error handling

### 5. Template Creation ✅
- [x] Create HTML template with editable table
- [x] Use DataTables or similar for interactive table
- [x] Add form modals for add/edit operations
- [x] Implement responsive design

### 6. URL Configuration ✅
- [x] Add URL pattern in `rd1web/pxe/urls.py`
- [x] Set up API endpoints for AJAX operations

### 7. Navigation Update ✅
- [x] Update sidebar template to include new link
- [x] Add permission check in template for link visibility
- [x] Position under RMA Management section

### 8. Admin Panel Integration ✅
- [x] Register model in Django admin
- [x] Create admin interface for permission management
- [x] Add admin actions for bulk operations

### 9. Database Migration ✅
- [x] Create model migration
- [x] Create permission migration
- [x] Run migrations

### 10. Testing ✅
- [x] Test permission system
- [x] Test CRUD operations
- [x] Test validation
- [x] Test access control

## File Changes Required

### New Files
- `rd1web/pxe/views/rma_testing_db.py` - View logic
- `rd1web/templates/features/rma_testing_db.html` - Template
- `rd1web/pxe/migrations/000X_add_rma_testing_db.py` - Model migration
- `rd1web/pxe/migrations/000X_add_rma_permission.py` - Permission migration

### Modified Files
- `rd1web/pxe/models.py` - Add RmaTestingDb model
- `rd1web/pxe/form.py` - Add RmaTestingDbForm
- `rd1web/pxe/urls.py` - Add URL patterns
- `rd1web/pxe/admin.py` - Register model
- `rd1web/templates/partials/sidebar.html` - Add navigation link

## Technical Details

### Model Structure
```python
class RmaTestingDb(models.Model):
    bmc_mac = models.CharField(max_length=17, unique=True)  # xx:xx:xx:xx:xx:xx
    bmc_ip = models.GenericIPAddressField()
    bmc_password = models.CharField(max_length=255)
    lan0_mac = models.CharField(max_length=17)
    lan1_mac = models.CharField(max_length=17)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
```

### Permission System
- Custom permission: `pxe.can_access_rma_testing_db`
- View decorator: `@permission_required('pxe.can_access_rma_testing_db')`
- Template conditional: `{% if perms.pxe.can_access_rma_testing_db %}`

### URL Structure
- Main page: `/rma/testing-db/`
- API endpoints: `/api/rma/testing-db/`
- CRUD operations: `/api/rma/testing-db/<id>/`

This plan ensures minimal impact to the existing codebase while implementing all requested features with proper security controls.

---

## IMPLEMENTATION COMPLETED ✅

### Summary of Changes Made

**✅ All 10 implementation tasks have been completed successfully!**

#### Database & Models
- **New Model**: `RmaTestingDb` with BMC MAC (unique), BMC IP, BMC Password, LAN0 MAC, LAN1 MAC
- **Validation**: Custom MAC address validation with normalization 
- **Migration**: Applied migration `0009_rmatestingdb.py` successfully

#### Permission System
- **Custom Permission**: `pxe.can_access_rma_testing_db` created and configured
- **Access Control**: Only users with permission can see the page
- **Admin Control**: Only Django superusers can grant permissions in admin panel

#### User Interface
- **New Page**: `/rma/testing-db/` with modern DataTables interface
- **CRUD Operations**: Full Create, Read, Update, Delete functionality via AJAX
- **Responsive Design**: Mobile-friendly table with Bootstrap 5 styling
- **Security Features**: Password masking, click-to-copy functionality

#### Navigation & Access
- **Sidebar Link**: "RMA Testing DB" added under RMA Management section
- **Permission Check**: Link only visible to users with proper permissions
- **URL Structure**: Clean RESTful URLs for all operations

#### Admin Integration
- **Django Admin**: Full admin interface with restricted access to superusers only
- **Security**: Password truncation in admin view for security
- **Organization**: Proper fieldsets and search functionality

### Next Steps for User

1. **Grant Permission**: Login to Django Admin (`/admin/`) as superuser
2. **User Management**: Navigate to Users → Select user → User permissions → Add `pxe | rma testing db entry | Can access RMA Testing DB`
3. **Access Page**: User can now see "RMA Testing DB" in the left sidebar
4. **Start Using**: Begin adding BMC configurations for RMA testing

### Key Features

- **Secure**: Permission-based access control
- **User-Friendly**: Modern, responsive interface with AJAX operations
- **Validated**: MAC address format validation and normalization
- **Scalable**: Pagination, search, and export functionality
- **Maintainable**: Clean code following Django best practices
- **Minimal Impact**: Zero changes to existing functionality

**The RMA Testing DB feature is now fully functional and ready for use!** 🎉
