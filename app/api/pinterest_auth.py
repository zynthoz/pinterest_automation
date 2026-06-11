"""Pinterest OAuth API routes."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.services.pinterest import PinterestClient, PinterestAPIError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/pinterest")
def pinterest_auth_redirect(request: Request):
    """Redirect user to Pinterest OAuth authorization page."""
    if not settings.pinterest_app_id:
        raise HTTPException(status_code=400, detail="PINTEREST_APP_ID not configured")

    redirect_uri = str(request.url_for("pinterest_auth_callback"))
    client = PinterestClient()
    auth_url = client.get_oauth_url(redirect_uri=redirect_uri)

    return {"auth_url": auth_url}


@router.get("/pinterest/callback", name="pinterest_auth_callback")
def pinterest_auth_callback(code: str, state: str = "pin_auth", request: Request = None):
    """
    Handle Pinterest OAuth callback.

    Exchanges the authorization code for access + refresh tokens.
    Tokens should be saved to .env manually for now.
    """
    redirect_uri = str(request.url_for("pinterest_auth_callback"))

    try:
        client = PinterestClient()
        tokens = client.exchange_code(code=code, redirect_uri=redirect_uri)

        access_token = tokens.get("access_token", "")
        refresh_token = tokens.get("refresh_token", "")

        logger.info("Pinterest OAuth successful!")

        # In a single-user local tool, display the tokens for manual .env update
        return {
            "message": "Pinterest connected successfully!",
            "instructions": "Add these tokens to your .env file:",
            "PINTEREST_ACCESS_TOKEN": access_token,
            "PINTEREST_REFRESH_TOKEN": refresh_token,
        }

    except Exception as e:
        logger.error("Pinterest OAuth failed: %s", e)
        raise HTTPException(status_code=400, detail=f"OAuth failed: {e}")


@router.get("/pinterest/boards")
def list_boards():
    """List all Pinterest boards for the connected account."""
    if not settings.pinterest_access_token:
        raise HTTPException(status_code=400, detail="Pinterest not connected — no access token")

    try:
        client = PinterestClient()
        boards = client.list_boards()
        client.close()
        return {"boards": boards}
    except PinterestAPIError as e:
        raise HTTPException(status_code=e.status_code, detail=str(e))


@router.get("/pinterest/status")
def pinterest_status():
    """Check if Pinterest is connected."""
    connected = bool(settings.pinterest_access_token)
    return {
        "connected": connected,
        "board_id": settings.pinterest_board_id if connected else None,
    }
