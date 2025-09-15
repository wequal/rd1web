import threading
from django.utils import timezone
from django.core.cache import cache
from django.db import transaction, models, connection
from django.contrib.auth.models import User, AnonymousUser
from .models import UserSession, UserActivity, UserStats
from rd1web.utils import get_client_ip, get_user_agent
from django.utils.deprecation import MiddlewareMixin
from django.utils.functional import SimpleLazyObject
from django.contrib.auth import get_user


class OptimizedAuthenticationMiddleware(MiddlewareMixin):
    # Add paths to be excluded from this middleware
    EXCLUDE_PATHS = [
        '/ipmitool/firmware/sequence_status/'
    ]

    def __call__(self, request):
        # For excluded paths, we attach an AnonymousUser so that downstream
        # middleware that accesses request.user does not fail with an AttributeError.
        if request.path_info in self.EXCLUDE_PATHS:
            request.user = AnonymousUser()
            return self.get_response(request)

        # For all other paths, attach the user object to the request, just like
        # Django's default AuthenticationMiddleware. This is a lazy object,
        # so the database is only hit if request.user is actually accessed by the view.
        request.user = SimpleLazyObject(lambda: get_user(request))

        response = self.get_response(request)

        # The original logic of this middleware was to update the user's
        # last_activity timestamp. We'll do this after the response is prepared.
        if hasattr(request, 'user') and request.user.is_authenticated:
            now = timezone.now()

            # Check if last_activity attribute exists to avoid errors
            last_activity = getattr(request.user, 'last_activity', None)

            # Update last activity timestamp if more than 60 seconds have passed
            if last_activity and (now - last_activity).total_seconds() > 60:
                # Update in the database
                User.objects.filter(pk=request.user.pk).update(last_activity=now)
                # Also update the user object on the request
                request.user.last_activity = now

        return response

class OptimizedUserActivityMiddleware:
    """High-performance user activity tracking middleware"""
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.activity_queue = []
        self.queue_lock = threading.Lock()
        self.last_flush = timezone.now()
        
        # Start background thread for batch processing
        self.start_background_processor()

    def __call__(self, request):
        response = self.get_response(request)
        
        # Track activity for authenticated users (async)
        if request.user.is_authenticated:
            self.queue_activity(request)
        
        return response

    def queue_activity(self, request):
        """Queue activity for batch processing"""
        # Skip tracking for certain paths
        skip_paths = ['/static/', '/favicon.ico', '/admin/jsi18n/', '/api/', '/media/']
        if any(skip_path in request.path for skip_path in skip_paths):
            return
        
        # Skip AJAX requests for certain endpoints
        if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
            ajax_skip_paths = ['/systems/', '/logs/']
            if any(skip_path in request.path for skip_path in ajax_skip_paths):
                return
        
        # Determine action type
        action = self.determine_action(request.path)
        
        # Create activity data
        activity_data = {
            'user_id': request.user.id,
            'session_key': request.session.session_key,
            'action': action,
            'url_path': request.path[:500],  # Truncate long URLs
            'ip_address': get_client_ip(request),
            'user_agent': get_user_agent(request)[:500],  # Truncate long user agents
            'timestamp': timezone.now(),
        }
        
        # Add to queue for batch processing
        with self.queue_lock:
            self.activity_queue.append(activity_data)
        
        # Update session activity in cache (lightweight)
        self.update_session_cache(request)

    def update_session_cache(self, request):
        """Update session activity in cache (fast)"""
        session_key = request.session.session_key
        if session_key:
            cache_key = f"session_activity:{session_key}:{request.user.id}"
            cache.set(cache_key, timezone.now(), timeout=1800)  # 30 minutes

    def start_background_processor(self):
        """Start background thread for batch processing"""
        def processor():
            while True:
                try:
                    self.process_activity_queue()
                    threading.Event().wait(5)  # Process every 5 seconds
                except Exception as e:
                    print(f"Error in background processor: {e}")
        
        thread = threading.Thread(target=processor, daemon=True)
        thread.start()

    def process_activity_queue(self):
        """Process queued activities in batches"""
        if not self.activity_queue:
            return
        
        with self.queue_lock:
            activities_to_process = self.activity_queue.copy()
            self.activity_queue.clear()
        
        if not activities_to_process:
            return
        
        try:
            with transaction.atomic():
                # Batch create activities
                activity_objects = []
                user_stats_updates = {}
                session_updates = {}
                
                for activity_data in activities_to_process:
                    # Get or cache session
                    session_id = self.get_session_id(activity_data['session_key'], activity_data['user_id'])
                    
                    # Prepare activity object
                    activity_objects.append(UserActivity(
                        user_id=activity_data['user_id'],
                        session_id=session_id,
                        action=activity_data['action'],
                        description=self.get_activity_description(
                            activity_data['url_path'], 
                            activity_data['action']
                        ),
                        url_path=activity_data['url_path'],
                        ip_address=activity_data['ip_address'],
                        user_agent=activity_data['user_agent'],
                        timestamp=activity_data['timestamp'],
                        success=True
                    ))
                    
                    # Aggregate user stats updates
                    user_id = activity_data['user_id']
                    if user_id not in user_stats_updates:
                        user_stats_updates[user_id] = {
                            'page_views': 0,
                            'logins': 0,
                            'last_activity': activity_data['timestamp']
                        }
                    
                    user_stats_updates[user_id]['page_views'] += 1
                    if activity_data['action'] == 'login':
                        user_stats_updates[user_id]['logins'] += 1
                    
                    # Update last activity time
                    if activity_data['timestamp'] > user_stats_updates[user_id]['last_activity']:
                        user_stats_updates[user_id]['last_activity'] = activity_data['timestamp']
                    
                    # Aggregate session updates
                    session_key = activity_data['session_key']
                    if session_key:
                        if session_key not in session_updates:
                            session_updates[session_key] = activity_data['timestamp']
                        elif activity_data['timestamp'] > session_updates[session_key]:
                            session_updates[session_key] = activity_data['timestamp']
                
                # Bulk create activities
                if activity_objects:
                    UserActivity.objects.bulk_create(activity_objects, batch_size=100)
                
                # Bulk update user stats
                if user_stats_updates:
                    self.bulk_update_user_stats(user_stats_updates)
                
                # Bulk update sessions
                if session_updates:
                    self.bulk_update_sessions(session_updates)
                
        except Exception as e:
            print(f"Error processing activity queue: {e}")
        
        finally:
            # Manually close the database connection for this thread.
            # This is crucial for long-running background threads to prevent
            # connection leaks and to ensure connections are returned to the pool.
            connection.close()

    def get_session_id(self, session_key, user_id):
        """Get session ID with caching"""
        if not session_key:
            return None
        
        cache_key = f"session_id:{session_key}:{user_id}"
        session_id = cache.get(cache_key)
        
        if session_id is None:
            try:
                session = UserSession.objects.get(
                    session_key=session_key,
                    user_id=user_id,
                    is_active=True
                )
                session_id = session.id
                cache.set(cache_key, session_id, timeout=1800)  # 30 minutes
            except UserSession.DoesNotExist:
                session_id = None
        
        return session_id

    def bulk_update_user_stats(self, user_stats_updates):
        """Bulk update user statistics"""
        for user_id, stats in user_stats_updates.items():
            try:
                user_stats, created = UserStats.objects.get_or_create(
                    user_id=user_id,
                    defaults={
                        'total_logins': stats['logins'],
                        'total_page_views': stats['page_views'],
                        'last_activity_date': stats['last_activity']
                    }
                )
                
                if not created:
                    user_stats.total_page_views += stats['page_views']
                    user_stats.total_logins += stats['logins']
                    user_stats.last_activity_date = stats['last_activity']
                    user_stats.save(update_fields=['total_page_views', 'total_logins', 'last_activity_date'])
                    
            except Exception as e:
                print(f"Error updating user stats for user {user_id}: {e}")

    def bulk_update_sessions(self, session_updates):
        """Bulk update session last activity"""
        for session_key, last_activity in session_updates.items():
            try:
                UserSession.objects.filter(
                    session_key=session_key,
                    is_active=True
                ).update(last_activity=last_activity)
            except Exception as e:
                print(f"Error updating session {session_key}: {e}")

    def determine_action(self, path):
        """Optimized action determination with caching"""
        cache_key = f"action_type:{hash(path)}"
        action = cache.get(cache_key)
        
        if action is None:
            # Determine action type
            if path.startswith('/auth/login'):
                action = 'login'
            elif path.startswith('/auth/logout'):
                action = 'logout'
            elif path.startswith('/auth/change-password'):
                action = 'password_change'
            elif path.startswith('/auth/profile'):
                action = 'profile_view'
            elif path.startswith('/admin'):
                action = 'admin_access'
            elif path.startswith('/pxe'):
                action = 'pxe_config'
            elif path.startswith('/systems'):
                action = 'system_view'
            elif path.startswith('/ipmitool'):
                action = 'ipmitool_use'
            elif path.startswith('/rma/pxe'):
                action = 'rma_pxe'
            elif path.startswith('/rma/logs'):
                action = 'rma_log_view'
            elif path.startswith('/rma/view'):
                action = 'rma_file_view'
            elif path.startswith('/logs'):
                action = 'log_view'
            elif path.startswith('/view'):
                action = 'file_view'
            elif 'kvm' in path:
                action = 'kvm_access'
            elif 'sol' in path:
                action = 'sol_access'
            elif path.startswith('/mac-ip'):
                action = 'mac_ip_view'
            else:
                action = 'page_view'
            
            # Cache for 1 hour
            cache.set(cache_key, action, timeout=3600)
        
        return action

    def get_activity_description(self, path, action):
        """Cached activity descriptions"""
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
            'mac_ip_view': 'User viewed MAC-IP results',
            'rma_pxe': 'User accessed RMA PXE configuration',
            'rma_log_view': 'User viewed RMA logs',
            'rma_file_view': 'User viewed RMA file',
            'page_view': f'User visited {path}'
        }
        return descriptions.get(action, f'User visited {path}')


class OptimizedUserSessionMiddleware:
    """Optimized session management with caching"""
    
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Handle login sessions with caching
        if (request.user.is_authenticated and 
            request.path.startswith('/auth/login') and 
            request.method == 'POST'):
            self.create_user_session_cached(request)
        
        response = self.get_response(request)
        return response

    def create_user_session_cached(self, request):
        """Create user session with caching optimization"""
        try:
            session_key = request.session.session_key
            if not session_key:
                request.session.create()
                session_key = request.session.session_key
            
            # Deactivate existing sessions (optimized query)
            UserSession.objects.filter(
                user=request.user,
                is_active=True
            ).update(is_active=False, logout_time=timezone.now())
            
            # Create new session
            new_session = UserSession.objects.create(
                user=request.user,
                session_key=session_key,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request)[:500],  # Truncate long user agents
                login_time=timezone.now(),
                last_activity=timezone.now(),
                is_active=True
            )
            
            # Cache the new session
            cache_key = f"session_id:{session_key}:{request.user.id}"
            cache.set(cache_key, new_session.id, timeout=86400)  # 24 hours
            
        except Exception as e:
            print(f"Error creating user session: {e}") 