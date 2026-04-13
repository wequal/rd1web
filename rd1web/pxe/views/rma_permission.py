"""RMA Permission page: grant or revoke can_access_rma_pxe for other users."""
from urllib.parse import urlencode

from django.contrib import messages
from django.contrib.auth.decorators import login_required, permission_required
from django.contrib.auth.models import Permission, User
from django.db.models import Q
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods


def _rma_pxe_perm():
    return Permission.objects.get(
        content_type__app_label='pxe',
        codename='can_access_rma_pxe',
    )


def _redirect_preserve_q(request, q):
    base = reverse('rma_permission')
    if q:
        return redirect(f'{base}?{urlencode({"q": q})}')
    return redirect(base)


@login_required
@permission_required('pxe.can_manage_rma_permission', raise_exception=True)
@require_http_methods(['GET', 'POST'])
def rma_permission(request):
    perm = _rma_pxe_perm()
    q = ''

    if request.method == 'POST':
        q = (request.POST.get('q') or '').strip()
        user_id = request.POST.get('user_id')
        grant_raw = request.POST.get('grant')

        try:
            target = User.objects.get(pk=user_id)
        except (User.DoesNotExist, ValueError, TypeError):
            messages.error(request, 'User not found.')
            return _redirect_preserve_q(request, q)

        if target.pk == request.user.pk:
            messages.warning(
                request,
                'You cannot change your own RMA test permission from this page.',
            )
            return _redirect_preserve_q(request, q)

        if target.is_superuser:
            messages.warning(
                request,
                'Superuser accounts bypass permission checks; their access is not changed here.',
            )
            return _redirect_preserve_q(request, q)

        if grant_raw not in ('0', '1'):
            messages.error(request, 'Invalid request.')
            return _redirect_preserve_q(request, q)

        grant = grant_raw == '1'
        if grant:
            target.user_permissions.add(perm)
            messages.success(
                request,
                f'RMA test permission granted for user "{target.username}".',
            )
        else:
            target.user_permissions.remove(perm)
            messages.success(
                request,
                f'RMA test permission revoked for user "{target.username}".',
            )
        return _redirect_preserve_q(request, q)

    q = (request.GET.get('q') or '').strip()
    users = []
    rows = []
    if q:
        users = (
            User.objects.filter(Q(username__icontains=q) | Q(email__icontains=q))
            .order_by('username')
            .distinct()
            .prefetch_related('user_permissions')[:50]
        )
        perm_pk = perm.pk
        for u in users:
            is_self = u.pk == request.user.pk
            is_super = u.is_superuser
            explicit = any(p.pk == perm_pk for p in u.user_permissions.all())
            rows.append(
                {
                    'user': u,
                    'explicit': explicit,
                    'is_self': is_self,
                    'is_super': is_super,
                }
            )

    return render(
        request,
        'features/rma_permission.html',
        {
            'q': q,
            'rows': rows,
        },
    )
