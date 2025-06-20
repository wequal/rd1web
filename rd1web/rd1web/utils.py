from typing import Any


def get_client_ip(request: Any) -> str:
    """Return the real client IP address for a Django request, taking reverse proxies into account."""
    x_forwarded_for = request.META.get("HTTP_X_FORWARDED_FOR")
    if x_forwarded_for:
        # The first address in the list is the original client
        return x_forwarded_for.split(",")[0].strip()
    return request.META.get("REMOTE_ADDR", "")


def get_user_agent(request: Any) -> str:
    """Return the user-agent header of the request (empty string if missing)."""
    return request.META.get("HTTP_USER_AGENT", "") 