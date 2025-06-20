from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.csrf import csrf_protect
from django.http import JsonResponse
from django.utils import timezone
from .models import UserSession, UserActivity, UserStats
import json
from rd1web.utils import get_client_ip

@csrf_protect
def login_view(request):
    """User login view"""
    if request.user.is_authenticated:
        return redirect('index')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        
        if username and password:
            user = authenticate(request, username=username, password=password)
            if user is not None:
                login(request, user)
                
                # Create or update user session
                session_key = request.session.session_key
                if not session_key:
                    request.session.create()
                    session_key = request.session.session_key
                
                # Deactivate any existing active sessions for this user
                UserSession.objects.filter(
                    user=user,
                    is_active=True
                ).update(is_active=False, logout_time=timezone.now())
                
                # Create new session record
                UserSession.objects.create(
                    user=user,
                    session_key=session_key,
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    login_time=timezone.now(),
                    last_activity=timezone.now(),
                    is_active=True
                )
                
                # Log the login activity
                UserActivity.objects.create(
                    user=user,
                    action='login',
                    description='User logged in successfully',
                    url_path=request.path,
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    success=True
                )
                
                next_url = request.GET.get('next', '/')
                return redirect(next_url)
            else:
                # Log failed login attempt
                UserActivity.objects.create(
                    user=None,
                    action='login',
                    description=f'Failed login attempt for username: {username}',
                    url_path=request.path,
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    success=False
                )
                messages.error(request, 'Invalid username or password.')
        else:
            messages.error(request, 'Please provide both username and password.')
    
    return render(request, 'authentication/login.html')

@csrf_protect
def signup_view(request):
    """User registration view"""
    if request.user.is_authenticated:
        return redirect('index')
    
    if request.method == 'POST':
        username = request.POST.get('username')
        email = request.POST.get('email')
        password = request.POST.get('password')
        password_confirm = request.POST.get('password_confirm')
        first_name = request.POST.get('first_name', '')
        last_name = request.POST.get('last_name', '')
        
        # Validation
        if not all([username, password, password_confirm]):
            messages.error(request, 'Username, password, and password confirmation are required.')
        elif password != password_confirm:
            messages.error(request, 'Passwords do not match.')
        elif User.objects.filter(username=username).exists():
            messages.error(request, 'Username already exists.')
        elif email and User.objects.filter(email=email).exists():
            messages.error(request, 'Email already exists.')
        elif len(password) < 8:
            messages.error(request, 'Password must be at least 8 characters long.')
        elif len(username) < 3:
            messages.error(request, 'Username must be at least 3 characters long.')
        elif not username.replace('_', '').replace('-', '').isalnum():
            messages.error(request, 'Username can only contain letters, numbers, underscores, and hyphens.')
        else:
            try:
                # Create user
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password=password,
                    first_name=first_name,
                    last_name=last_name
                )
                messages.success(request, 'Account created successfully! Please log in.')
                return redirect('auth:login')
            except Exception as e:
                messages.error(request, f'Error creating account: {str(e)}')
    
    return render(request, 'authentication/signup.html')

@login_required
@csrf_protect
def change_password_view(request):
    """Change password view"""
    if request.method == 'POST':
        current_password = request.POST.get('current_password')
        new_password = request.POST.get('new_password')
        new_password_confirm = request.POST.get('new_password_confirm')
        
        # Validation
        if not all([current_password, new_password, new_password_confirm]):
            messages.error(request, 'All fields are required.')
        elif not request.user.check_password(current_password):
            messages.error(request, 'Current password is incorrect.')
        elif new_password != new_password_confirm:
            messages.error(request, 'New passwords do not match.')
        elif len(new_password) < 8:
            messages.error(request, 'New password must be at least 8 characters long.')
        elif current_password == new_password:
            messages.error(request, 'New password must be different from current password.')
        else:
            try:
                # Change password
                request.user.set_password(new_password)
                request.user.save()
                # Keep user logged in after password change
                update_session_auth_hash(request, request.user)
                
                # Log password change activity
                UserActivity.objects.create(
                    user=request.user,
                    action='password_change',
                    description='User changed password successfully',
                    url_path=request.path,
                    ip_address=get_client_ip(request),
                    user_agent=request.META.get('HTTP_USER_AGENT', ''),
                    success=True
                )
                
                messages.success(request, 'Password changed successfully!')
                return redirect('auth:change_password')
            except Exception as e:
                messages.error(request, f'Error changing password: {str(e)}')
    
    return render(request, 'authentication/change_password.html')

@login_required
def logout_view(request):
    """User logout view"""
    # Log the logout activity before logging out
    if request.user.is_authenticated:
        UserActivity.objects.create(
            user=request.user,
            action='logout',
            description='User logged out',
            url_path=request.path,
            ip_address=get_client_ip(request),
            user_agent=request.META.get('HTTP_USER_AGENT', ''),
            success=True
        )
        
        # Update session as inactive
        session_key = request.session.session_key
        if session_key:
            UserSession.objects.filter(
                session_key=session_key,
                user=request.user,
                is_active=True
            ).update(is_active=False, logout_time=timezone.now())
    
    logout(request)
    messages.info(request, 'You have been logged out successfully.')
    return redirect('auth:login')

@login_required
def profile_view(request):
    """User profile view"""
    return render(request, 'authentication/profile.html', {
        'user': request.user
    })
