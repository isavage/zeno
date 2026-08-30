import logging
from typing import Optional, Dict, Any
from authlib.integrations.starlette_client import OAuth
from starlette.requests import Request
from starlette.responses import RedirectResponse
from fastapi import HTTPException, status
from app.config import settings

logger = logging.getLogger(__name__)

oauth = OAuth()

# Configure Google OAuth if credentials present
if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
    oauth.register(
        name="google",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )

# Configure Microsoft OAuth if credentials present
if settings.MICROSOFT_CLIENT_ID and settings.MICROSOFT_CLIENT_SECRET:
    tenant = settings.MICROSOFT_TENANT_ID or "common"
    oauth.register(
        name="microsoft",
        client_id=settings.MICROSOFT_CLIENT_ID,
        client_secret=settings.MICROSOFT_CLIENT_SECRET,
        server_metadata_url=f"https://login.microsoftonline.com/{tenant}/v2.0/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile User.Read"},
    )

def is_email_authorized(email: Optional[str]) -> bool:
    """Verifies whether the email belongs to the authorized whitelist."""
    if not email:
        return False
    authorized = settings.authorized_emails_list
    if not authorized:
        # Authentication alone is never sufficient; the whitelist is mandatory.
        logger.warning("No AUTHORIZED_EMAILS configured in environment. Denying email %s.", email)
        return False
    return email.strip().lower() in authorized


def is_admin_email(email: Optional[str]) -> bool:
    """Return True when the email belongs to the configured admin list."""
    if not email:
        return False
    return email.strip().lower() in settings.admin_emails


def is_admin_user(user: Optional[Dict[str, Any]]) -> bool:
    """Return True when the authenticated session belongs to an admin user."""
    if not user:
        return False
    return is_admin_email(user.get("email"))

async def get_current_user(request: Request) -> Dict[str, Any]:
    """Dependency / Helper to retrieve current authenticated user from session."""
    user = request.session.get("user")
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated. Please sign in via Google or Microsoft."
        )
    return user


async def get_current_admin_user(request: Request) -> Dict[str, Any]:
    """Dependency / Helper to retrieve the current authenticated admin user."""
    user = await get_current_user(request)
    if not is_admin_user(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Admin access required for {user.get('email', 'unknown')}"
        )
    return user
