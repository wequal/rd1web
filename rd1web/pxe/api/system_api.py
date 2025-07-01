from django.http import JsonResponse
from django.views.decorators.http import require_GET
from django.contrib.auth.decorators import login_required
import json
from django_redis import get_redis_connection

from ..views.system_details import get_systems_data

# Redis connection (uses the default cache configured in settings)
redis_conn = get_redis_connection("default")

DEFAULT_TTL = 30  # seconds


def _cache_get_or_set(key: str, builder, ttl: int = DEFAULT_TTL):
    """Return JSON-serialisable data from Redis cache or generate and store."""
    try:
        if (cached := redis_conn.get(key)):
            return json.loads(cached)
    except Exception:
        # If Redis is down, proceed without caching
        pass

    data = builder()
    try:
        redis_conn.setex(key, ttl, json.dumps(data))
    except Exception:
        pass
    return data


@login_required
@require_GET
def systems_summary(request):
    """Return counts per category (burnin, dc, ac, other, archive)."""

    def builder():
        systems = get_systems_data()
        return {k: len(v) for k, v in systems.items()}

    data = _cache_get_or_set("systems:summary", builder)
    return JsonResponse(data, safe=False)


@login_required
@require_GET
def systems_category(request, category):
    """Paginated list of systems for a specific category."""
    category = category.lower()
    page = int(request.GET.get("page", 1))
    page_size = int(request.GET.get("page_size", 50))

    search_term = request.GET.get("search", "").lower()

    def builder():
        # Build full list for the requested category
        systems = get_systems_data()
        return systems.get(category, [])

    key = f"systems:{category}:full"
    full_list = _cache_get_or_set(key, builder)

    # Optional text filtering
    if search_term:
        full_list = [s for s in full_list if search_term in json.dumps(s).lower()]

    # Pagination
    start = (page - 1) * page_size
    end = start + page_size
    results = full_list[start:end]

    response = {
        "count": len(full_list),
        "page": page,
        "page_size": page_size,
        "results": results,
        "next": None,
    }

    if end < len(full_list):
        # Build next page URL
        next_qs = request.META.get("QUERY_STRING", "")
        # Replace page param
        if "page=" in next_qs:
            qs_parts = [p for p in next_qs.split("&") if not p.startswith("page=")]
            qs_parts.append(f"page={page + 1}")
            next_qs = "&".join(qs_parts)
        else:
            next_qs = (next_qs + "&" if next_qs else "") + f"page={page + 1}"
        response["next"] = request.path + ("?" + next_qs if next_qs else "")

    return JsonResponse(response, safe=False) 