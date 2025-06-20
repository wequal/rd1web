from django.contrib.admin import helpers
from django.shortcuts import render
from django.conf import settings
from django.contrib.auth.decorators import login_required

@login_required
def index(request):
    return render(request, 'base.html')

