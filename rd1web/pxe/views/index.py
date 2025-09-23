from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required, permission_required

@login_required
@permission_required('pxe.can_use_dashboard', raise_exception=True)
def index(request):
    return render(request, 'index.html')

