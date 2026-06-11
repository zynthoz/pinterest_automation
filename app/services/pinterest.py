"""Pinterest API v5 client for pin creation and management.

Handles OAuth flow, video upload, pin creation, and token refresh.
API docs: https://developers.pinterest.com/docs/api/v5/
"""

import logging
import time

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

PINTEREST_API_BASE = "https://api.pinterest.com/v5"
PINTEREST_OAUTH_BASE = "https://www.pinterest.com/oauth"


class PinterestAPIError(Exception):
    """Raised when the Pinterest API returns an error."""

    def __init__(self, status_code: int, message: str, response_body: dict | None = None):
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(f"Pinterest API {status_code}: {message}")


class PinterestClient:
    """Client for Pinterest API v5."""

    def __init__(
        self,
        access_token: str | None = None,
        app_id: str | None = None,
        app_secret: str | None = None,
    ):
        self.access_token = access_token or settings.pinterest_access_token
        self.app_id = app_id or settings.pinterest_app_id
        self.app_secret = app_secret or settings.pinterest_app_secret
        self._client = httpx.Client(
            base_url=PINTEREST_API_BASE,
            timeout=60,
            headers=self._auth_headers(),
        )

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.access_token}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str, **kwargs) -> dict:
        """Make an authenticated API request with error handling."""
        resp = self._client.request(method, path, **kwargs)

        if resp.status_code == 429:
            # Rate limited — extract retry-after header
            retry_after = int(resp.headers.get("Retry-After", 60))
            logger.warning("Pinterest rate limited. Waiting %ds...", retry_after)
            raise PinterestAPIError(429, f"Rate limited. Retry after {retry_after}s")

        if resp.status_code == 401:
            raise PinterestAPIError(401, "Unauthorized — access token may be expired")

        if resp.status_code >= 400:
            body = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            msg = body.get("message", resp.text[:200])
            raise PinterestAPIError(resp.status_code, msg, body)

        return resp.json()

    # ─── OAuth Flow ─────────────────────────────────────────────

    def get_oauth_url(self, redirect_uri: str, state: str = "pin_auth") -> str:
        """Generate the Pinterest OAuth authorization URL."""
        scopes = "boards:read,pins:read,pins:write,boards:write"
        return (
            f"{PINTEREST_OAUTH_BASE}/"
            f"?client_id={self.app_id}"
            f"&redirect_uri={redirect_uri}"
            f"&response_type=code"
            f"&scope={scopes}"
            f"&state={state}"
        )

    def exchange_code(self, code: str, redirect_uri: str) -> dict:
        """Exchange OAuth authorization code for access + refresh tokens."""
        resp = httpx.post(
            f"{PINTEREST_OAUTH_BASE}/token",
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
            },
            auth=(self.app_id, self.app_secret),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self.access_token = data["access_token"]
        self._client.headers.update(self._auth_headers())
        return data

    def refresh_access_token(self, refresh_token: str | None = None) -> dict:
        """Refresh an expired access token."""
        token = refresh_token or settings.pinterest_refresh_token
        resp = httpx.post(
            f"{PINTEREST_OAUTH_BASE}/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": token,
            },
            auth=(self.app_id, self.app_secret),
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        self.access_token = data["access_token"]
        self._client.headers.update(self._auth_headers())
        return data

    # ─── Boards ─────────────────────────────────────────────────

    def list_boards(self) -> list[dict]:
        """List all boards for the authenticated user."""
        data = self._request("GET", "/boards")
        return data.get("items", [])

    # ─── Video Upload + Pin Creation ────────────────────────────

    def create_video_pin(
        self,
        video_path: str,
        board_id: str,
        title: str,
        description: str,
        link: str,
        alt_text: str | None = None,
    ) -> dict:
        """
        Upload a video and create a pin in one workflow.

        Steps:
            1. Register media upload → get upload_id + upload_url
            2. Upload video binary to the upload URL
            3. Create pin referencing the media_id
            4. Poll for media processing completion

        Returns:
            Pinterest API pin response dict
        """
        # Step 1: Register media upload
        logger.info("Registering video upload with Pinterest...")
        register_resp = self._request(
            "POST",
            "/media",
            json={"media_type": "video"},
        )
        upload_id = register_resp["media_id"]
        upload_url = register_resp["upload_url"]

        # Step 2: Upload video binary
        logger.info("Uploading video to Pinterest (media_id: %s)...", upload_id)
        with open(video_path, "rb") as f:
            upload_resp = httpx.put(
                upload_url,
                content=f.read(),
                headers={
                    "Content-Type": "application/octet-stream",
                },
                timeout=300,  # videos can be large
            )
            upload_resp.raise_for_status()

        # Step 3: Wait for media processing
        logger.info("Waiting for Pinterest to process video...")
        media_id = self._wait_for_media(upload_id)

        # Step 4: Create the pin
        pin_data = {
            "board_id": board_id,
            "title": title[:100],
            "description": description[:500],
            "link": link,
            "media_source": {
                "source_type": "video_id",
                "media_id": media_id,
            },
        }
        if alt_text:
            pin_data["alt_text"] = alt_text[:500]

        logger.info("Creating pin on board %s...", board_id)
        pin_resp = self._request("POST", "/pins", json=pin_data)
        logger.info("Pin created! ID: %s", pin_resp.get("id"))
        return pin_resp

    def _wait_for_media(
        self,
        media_id: str,
        timeout_seconds: int = 300,
        poll_interval: int = 10,
    ) -> str:
        """Poll until media processing is complete."""
        start = time.time()
        while time.time() - start < timeout_seconds:
            status_resp = self._request("GET", f"/media/{media_id}")
            status = status_resp.get("status", "")

            if status == "succeeded":
                logger.info("Video processing complete (media_id: %s)", media_id)
                return media_id
            elif status == "failed":
                raise PinterestAPIError(
                    500,
                    f"Video processing failed: {status_resp.get('failure_reason', 'unknown')}",
                )

            logger.debug("Media status: %s — waiting %ds...", status, poll_interval)
            time.sleep(poll_interval)

        raise PinterestAPIError(
            408,
            f"Video processing timed out after {timeout_seconds}s",
        )

    # ─── Pin Management ────────────────────────────────────────

    def get_pin(self, pin_id: str) -> dict:
        """Get a single pin by ID."""
        return self._request("GET", f"/pins/{pin_id}")

    def delete_pin(self, pin_id: str) -> None:
        """Delete a pin."""
        self._client.delete(f"/pins/{pin_id}")
        logger.info("Deleted pin: %s", pin_id)

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()
