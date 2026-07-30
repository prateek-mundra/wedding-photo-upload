"""
Minimal auth for admin-only endpoints (gallery listing).

Guests uploading never hit this — only the admin/photographer viewing the
gallery does. Deliberately simple (one shared token) since this is a
single-event system, not a multi-tenant product.
"""

from fastapi import Header, HTTPException, status

from config import get_settings


def require_admin(x_admin_token: str = Header(default="")) -> None:
    settings = get_settings()

    if not settings.admin_token:
        # Fail closed: if you haven't set a token in .env, admin routes are
        # locked rather than silently open.
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin access is not configured. Set ADMIN_TOKEN in .env.",
        )

    if x_admin_token != settings.admin_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid or missing admin token")
