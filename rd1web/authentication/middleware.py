from django.utils import timezone
from django.contrib.auth.models import User
from django.contrib.sessions.models import Session
from .models import UserSession, UserActivity, UserStats
from rd1web.utils import get_client_ip, get_user_agent

class UserActivityMiddleware:
    """Middleware to track user activities and sessions"""
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Process the request
        response = self.get_response(request)
        
        # Track activity for authenticated users
        if request.user.is_authenticated:
            self.track_user_activity(request)
            self.update_session_activity(request)
        
        return response

    def track_user_activity(self, request):
        """Track user activity"""
        try:
            # Determine activity type based on URL path
            action = self.determine_action(request.path)
            
            # Skip tracking for certain paths to avoid noise
            skip_paths = ['/static/', '/favicon.ico', '/admin/jsi18n/']
            if any(skip_path in request.path for skip_path in skip_paths):
                return
            
            # Get or create user session
            session_key = request.session.session_key
            user_session = None
            if session_key:
                try:
                    user_session = UserSession.objects.get(
                        session_key=session_key,
                        user=request.user,
                        is_active=True
                    )
                except UserSession.DoesNotExist:
                    pass
            
            # Create activity record
            UserActivity.objects.create(
                user=request.user,
                session=user_session,
                action=action,
                description=self.get_activity_description(request.path, action),
                url_path=request.path,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
                success=True
            )
            
            # Update user stats
            self.update_user_stats(request.user, action)
            
        except Exception as e:
            # Log error but don't break the request
            print(f"Error tracking user activity: {e}")

    def determine_action(self, path):
        """Determine the action type based on URL path"""
        if path.startswith('/auth/login'):
            return 'login'
        elif path.startswith('/auth/logout'):
            return 'logout'
        elif path.startswith('/auth/change-password'):
            return 'password_change'
        elif path.startswith('/auth/profile'):
            return 'profile_view'
        elif path.startswith('/admin'):
            return 'admin_access'
        elif path.startswith('/pxe'):
            return 'pxe_config'
        elif path.startswith('/systems'):
            return 'system_view'
        elif path.startswith('/ipmitool'):
            return 'ipmitool_use'
        elif path.startswith('/logs'):
            return 'log_view'
        elif path.startswith('/view'):
            return 'file_view'
        elif 'kvm' in path:
            return 'kvm_access'
        elif 'sol' in path:
            return 'sol_access'
        else:
            return 'page_view'

    def get_activity_description(self, path, action):
        """Generate a description for the activity"""
        descriptions = {
            'login': 'User logged in',
            'logout': 'User logged out',
            'password_change': 'User changed password',
            'profile_view': 'User viewed profile',
            'admin_access': 'User accessed admin panel',
            'pxe_config': 'User accessed PXE configuration',
            'system_view': 'User viewed system details',
            'ipmitool_use': 'User used IPMI tool',
            'log_view': 'User viewed log files',
            'file_view': 'User viewed file',
            'kvm_access': 'User accessed KVM',
            'sol_access': 'User accessed SOL',
            'page_view': f'User visited {path}'
        }
        return descriptions.get(action, f'User visited {path}')

    def update_session_activity(self, request):
        """Update session last activity time"""
        try:
            session_key = request.session.session_key
            if session_key:
                UserSession.objects.filter(
                    session_key=session_key,
                    user=request.user,
                    is_active=True
                ).update(last_activity=timezone.now())
        except Exception as e:
            print(f"Error updating session activity: {e}")

    def update_user_stats(self, user, action):
        """Update user statistics"""
        try:
            stats, created = UserStats.objects.get_or_create(
                user=user,
                defaults={
                    'total_logins': 0,
                    'total_page_views': 0,
                    'last_activity_date': timezone.now()
                }
            )
            
            if action == 'login':
                stats.total_logins += 1
            
            stats.total_page_views += 1
            stats.last_activity_date = timezone.now()
            stats.save()
            
        except Exception as e:
            print(f"Error updating user stats: {e}")

class UserSessionMiddleware:
    """Middleware to manage user sessions"""
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Track login sessions
        if request.user.is_authenticated and request.path.startswith('/auth/login') and request.method == 'POST':
            self.create_user_session(request)
        
        response = self.get_response(request)
        return response

    def create_user_session(self, request):
        """Create or update user session on login"""
        try:
            session_key = request.session.session_key
            if not session_key:
                request.session.create()
                session_key = request.session.session_key
            
            # Deactivate any existing active sessions for this user
            UserSession.objects.filter(
                user=request.user,
                is_active=True
            ).update(is_active=False, logout_time=timezone.now())
            
            # Create new session record
            UserSession.objects.create(
                user=request.user,
                session_key=session_key,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
                login_time=timezone.now(),
                last_activity=timezone.now(),
                is_active=True
            )
            
        except Exception as e:
            print(f"Error creating user session: {e}") 