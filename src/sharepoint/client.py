"""
sharepoint/client.py — Microsoft Graph API client for SharePoint file operations.

Authentication: OAuth2 client_credentials flow (application permissions, no user login).
    Credentials from Azure AD app registration (FusionTek, ticket T20260508.0125).
    Permission granted: Files.ReadWrite.All (application type, admin consent).

Token endpoint: https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token
Graph base:     https://graph.microsoft.com/v1.0/

Credentials are loaded from environment variables (set in .env locally, Railway env vars
in production). Never hardcode or commit credentials.

    AZURE_CLIENT_ID     — Application (client) ID from Azure AD
    AZURE_TENANT_ID     — Directory (tenant) ID from Azure AD
    AZURE_CLIENT_SECRET — Client secret VALUE (not the secret ID/GUID)
    SHAREPOINT_SITE_URL — e.g. https://wahospitality.sharepoint.com/sites/Membership

⚠ If you get 401 Unauthorized on token fetch:
    FusionTek may have sent the secret *ID* (a GUID) instead of the secret *value*.
    The value is a long alphanumeric string shown only once at creation time.
    Ask Matt Moore for the "Value" field from:
        Azure AD → App registrations → Certificates & secrets → your secret row

SHAREPOINT FILE STRUCTURE (target layout — create manually or via this client):
    /Membership Automation/
        Monthly Metrics.xlsx        ← long-form cache table (Year/Month/Territory/Metric/Value)
        Drops.xlsx                  ← dropped account detail per account
        Closed Businesses.xlsx      ← closed business detail per account
        Admin Inputs.xlsx           ← goals only (sales/member/retention/penetration)

Usage:
    from src.sharepoint.client import SharePointClient

    client = SharePointClient.from_env()
    data = client.read_file("Membership Automation/Monthly Metrics.xlsx")
    client.write_file("Membership Automation/Monthly Metrics.xlsx", updated_bytes)
"""

import os
import time
from io import BytesIO
from typing import Dict, List, Optional
from urllib.parse import urlparse

import requests


GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_URL_TEMPLATE = "https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
SCOPE = "https://graph.microsoft.com/.default"

# Token cache TTL — Graph tokens are valid for ~1 hour; refresh 5 min early
_TOKEN_LIFETIME_SECONDS = 3300  # 55 minutes


class SharePointError(Exception):
    """Raised when the Graph API returns an error response."""
    pass


class SharePointClient:
    """
    Thin wrapper around Microsoft Graph API for SharePoint file operations.

    Handles:
    - Token acquisition and refresh (client_credentials grant)
    - SharePoint site ID resolution from site URL
    - Drive (document library) discovery
    - File read, write, list, delete

    All file paths are relative to the drive root (e.g. "Membership Automation/drops.xlsx").
    """

    def __init__(
        self,
        client_id: str,
        tenant_id: str,
        client_secret: str,
        site_url: str,
        drive_name: str = "Documents",
    ):
        """
        Args:
            client_id:     Azure AD Application (client) ID.
            tenant_id:     Azure AD Directory (tenant) ID.
            client_secret: Client secret VALUE (not the secret ID/GUID).
            site_url:      SharePoint site URL, e.g.
                           "https://warestaurant.sharepoint.com/sites/WHAMembership"
            drive_name:    Which document library to use. The WHA Membership site
                           has multiple libraries ("Documents", "Test Folder Marla")
                           — we target "Documents" where the Data Hub folder lives.
        """
        self._client_id = client_id
        self._tenant_id = tenant_id
        self._client_secret = client_secret
        self._site_url = site_url.rstrip("/")
        self._drive_name = drive_name

        self._session = requests.Session()
        self._token: Optional[str] = None
        self._token_expires_at: float = 0.0

        # Resolved lazily on first use
        self._site_id: Optional[str] = None
        self._drive_id: Optional[str] = None

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_env(cls) -> "SharePointClient":
        """
        Construct SharePointClient from environment variables.
        Loads .env if present (via python-dotenv).

        Reads the SHAREPOINT_* names first (what Kyle's credentials were stored
        under), falling back to AZURE_* names for backward compatibility:
            SHAREPOINT_CLIENT_ID    | AZURE_CLIENT_ID
            SHAREPOINT_TENANT_ID    | AZURE_TENANT_ID
            SHAREPOINT_CLIENT_SECRET| AZURE_CLIENT_SECRET
            SHAREPOINT_SITE_URL     (required)
        """
        try:
            from dotenv import load_dotenv
            from pathlib import Path
            # Explicit path so it works regardless of CWD (Streamlit, scripts, etc.)
            load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")
        except ImportError:
            pass  # dotenv optional — falls back to existing env vars

        def _env(*names):
            for n in names:
                v = os.environ.get(n)
                if v:
                    return v
            return None

        client_id = _env("SHAREPOINT_CLIENT_ID", "AZURE_CLIENT_ID")
        tenant_id = _env("SHAREPOINT_TENANT_ID", "AZURE_TENANT_ID")
        secret    = _env("SHAREPOINT_CLIENT_SECRET", "AZURE_CLIENT_SECRET")
        site_url  = _env("SHAREPOINT_SITE_URL")

        missing = [name for name, val in [
            ("SHAREPOINT_CLIENT_ID", client_id),
            ("SHAREPOINT_TENANT_ID", tenant_id),
            ("SHAREPOINT_CLIENT_SECRET", secret),
            ("SHAREPOINT_SITE_URL", site_url),
        ] if not val]
        if missing:
            raise SharePointError(
                f"Missing required environment variables: {', '.join(missing)}\n"
                "Set them in .env (local) or Railway environment variables (prod)."
            )

        return cls(
            client_id=client_id,
            tenant_id=tenant_id,
            client_secret=secret,
            site_url=site_url,
        )

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        """
        Return a valid access token, fetching or refreshing as needed.

        Uses client_credentials grant — no user interaction required.
        Token is cached for ~55 minutes (actual lifetime is 60 min).
        """
        now = time.monotonic()
        if self._token and now < self._token_expires_at:
            return self._token

        token_url = TOKEN_URL_TEMPLATE.format(tenant_id=self._tenant_id)
        resp = requests.post(token_url, data={
            "grant_type": "client_credentials",
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "scope": SCOPE,
        })

        if resp.status_code != 200:
            body = resp.text[:500]
            raise SharePointError(
                f"Token fetch failed ({resp.status_code}): {body}\n"
                "If you see 'AADSTS7000215: Invalid client secret', FusionTek sent\n"
                "the secret ID (GUID) instead of the secret VALUE. Ask Matt Moore\n"
                "for the 'Value' field from Azure AD → Certificates & secrets."
            )

        data = resp.json()
        self._token = data["access_token"]
        expires_in = data.get("expires_in", 3600)
        self._token_expires_at = now + min(expires_in - 300, _TOKEN_LIFETIME_SECONDS)
        return self._token

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/json",
        }

    # ------------------------------------------------------------------
    # Site + Drive resolution
    # ------------------------------------------------------------------

    def _resolve_site(self) -> str:
        """
        Resolve SharePoint site URL → Graph site ID.

        Graph API path: GET /sites/{hostname}:/{site-relative-path}
        E.g. site URL "https://wahospitality.sharepoint.com/sites/Membership"
             → GET /sites/wahospitality.sharepoint.com:/sites/Membership
        """
        if self._site_id:
            return self._site_id

        parsed = urlparse(self._site_url)
        hostname = parsed.netloc           # e.g. wahospitality.sharepoint.com
        path = parsed.path                 # e.g. /sites/Membership

        url = f"{GRAPH_BASE}/sites/{hostname}:{path}"
        resp = self._session.get(url, headers=self._headers())

        if resp.status_code != 200:
            raise SharePointError(
                f"Site resolution failed ({resp.status_code}): {resp.text[:400]}\n"
                f"Site URL used: {self._site_url}\n"
                "Check that SHAREPOINT_SITE_URL is correct and the app has access."
            )

        self._site_id = resp.json()["id"]
        return self._site_id

    def _resolve_drive(self) -> str:
        """
        Find the default document library drive for the site.

        Returns the first drive whose driveType is 'documentLibrary'.
        This is typically the "Documents" or "Shared Documents" library.
        """
        if self._drive_id:
            return self._drive_id

        site_id = self._resolve_site()
        url = f"{GRAPH_BASE}/sites/{site_id}/drives"
        resp = self._session.get(url, headers=self._headers())

        if resp.status_code != 200:
            raise SharePointError(
                f"Drive listing failed ({resp.status_code}): {resp.text[:400]}"
            )

        drives = resp.json().get("value", [])

        # Prefer the drive matching self._drive_name (the site has multiple
        # document libraries — we must pick "Documents", not "Test Folder Marla").
        for drive in drives:
            if drive.get("name") == self._drive_name:
                self._drive_id = drive["id"]
                return self._drive_id

        # Next: first documentLibrary drive
        for drive in drives:
            if drive.get("driveType") == "documentLibrary":
                self._drive_id = drive["id"]
                return self._drive_id

        # Last resort: first drive
        if drives:
            self._drive_id = drives[0]["id"]
            return self._drive_id

        raise SharePointError("No drives found on SharePoint site.")

    # ------------------------------------------------------------------
    # File operations
    # ------------------------------------------------------------------

    def read_file(self, path: str) -> bytes:
        """
        Download a file from SharePoint.

        Args:
            path: File path relative to drive root,
                  e.g. "Membership Automation/Monthly Metrics.xlsx"

        Returns:
            File contents as bytes. Pass to openpyxl via BytesIO:
                wb = openpyxl.load_workbook(BytesIO(client.read_file(path)))
        """
        drive_id = self._resolve_drive()
        url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{path}:/content"

        resp = self._session.get(url, headers=self._headers())
        if resp.status_code == 404:
            raise FileNotFoundError(f"File not found on SharePoint: {path}")
        if resp.status_code != 200:
            raise SharePointError(
                f"File read failed ({resp.status_code}): {resp.text[:400]}"
            )

        return resp.content

    def write_file(self, path: str, data: bytes) -> Dict:
        """
        Upload (create or overwrite) a file on SharePoint.

        Uses the Graph "upload small file" endpoint (supports up to 4 MB).
        For larger files, use the resumable upload session endpoint — not
        needed here since our xlsx files are well under 4 MB.

        Args:
            path: File path relative to drive root.
            data: File contents as bytes. Get from openpyxl:
                buf = BytesIO(); wb.save(buf); client.write_file(path, buf.getvalue())

        Returns:
            Graph API response dict (contains file metadata including id, size, etc.)
        """
        drive_id = self._resolve_drive()
        url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{path}:/content"

        # Override Content-Type for binary upload
        headers = {
            "Authorization": f"Bearer {self._get_token()}",
            "Content-Type": "application/octet-stream",
        }

        # Retry on HTTP 423 (resourceLocked). SharePoint briefly locks Office
        # files during server-side re-packing/indexing after a write, and also
        # if the file is momentarily open in an Office app. These locks usually
        # release within a few seconds, so retry with backoff before giving up.
        max_attempts = 4
        backoff = [2, 4, 8]  # seconds between attempts
        for attempt in range(max_attempts):
            resp = self._session.put(url, headers=headers, data=data)
            if resp.status_code in (200, 201):
                return resp.json()
            if resp.status_code == 423 and attempt < max_attempts - 1:
                time.sleep(backoff[attempt])
                continue
            break

        if resp.status_code == 423:
            raise SharePointError(
                "File write failed (423 locked): SharePoint has the file locked. "
                "Close it in Excel/Numbers and any SharePoint preview tab, then retry. "
                "If it persists, wait a minute for SharePoint to release the lock."
            )
        raise SharePointError(
            f"File write failed ({resp.status_code}): {resp.text[:400]}"
        )

    def file_exists(self, path: str) -> bool:
        """Check whether a file exists at the given path."""
        drive_id = self._resolve_drive()
        url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{path}"

        resp = self._session.get(url, headers=self._headers())
        return resp.status_code == 200

    def list_folder(self, folder_path: str = "") -> List[Dict]:
        """
        List files and folders at a path.

        Args:
            folder_path: Relative path to folder, or "" for drive root.

        Returns:
            List of item dicts with keys: name, id, size, lastModifiedDateTime,
            file (present if it's a file), folder (present if it's a folder).
        """
        drive_id = self._resolve_drive()
        if folder_path:
            url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{folder_path}:/children"
        else:
            url = f"{GRAPH_BASE}/drives/{drive_id}/root/children"

        resp = self._session.get(url, headers=self._headers())
        if resp.status_code == 404:
            return []
        if resp.status_code != 200:
            raise SharePointError(
                f"Folder listing failed ({resp.status_code}): {resp.text[:400]}"
            )

        return resp.json().get("value", [])

    def delete_file(self, path: str) -> None:
        """
        Delete a file from SharePoint.

        Args:
            path: File path relative to drive root.
        """
        drive_id = self._resolve_drive()
        url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{path}"

        resp = self._session.delete(url, headers=self._headers())
        if resp.status_code == 404:
            return  # Already gone — treat as success
        if resp.status_code != 204:
            raise SharePointError(
                f"File delete failed ({resp.status_code}): {resp.text[:400]}"
            )

    def create_folder(self, parent_path: str, folder_name: str) -> Dict:
        """
        Create a folder on SharePoint.

        Args:
            parent_path: Path of the parent folder (or "" for drive root).
            folder_name: Name of the new folder.

        Returns:
            Graph API response dict for the created folder item.
        """
        drive_id = self._resolve_drive()
        if parent_path:
            url = f"{GRAPH_BASE}/drives/{drive_id}/root:/{parent_path}:/children"
        else:
            url = f"{GRAPH_BASE}/drives/{drive_id}/root/children"

        headers = self._headers()
        resp = self._session.post(url, headers=headers, json={
            "name": folder_name,
            "folder": {},
            "@microsoft.graph.conflictBehavior": "replace",
        })

        if resp.status_code not in (200, 201):
            raise SharePointError(
                f"Folder creation failed ({resp.status_code}): {resp.text[:400]}"
            )

        return resp.json()

    # ------------------------------------------------------------------
    # Convenience: read/write openpyxl workbooks directly
    # ------------------------------------------------------------------

    def read_workbook(self, path: str):
        """
        Download a file and return it as an openpyxl Workbook.

        Args:
            path: File path relative to drive root.

        Returns:
            openpyxl.Workbook object (in-memory, not read-only).
        """
        import openpyxl
        data = self.read_file(path)
        return openpyxl.load_workbook(BytesIO(data))

    def write_workbook(self, path: str, wb) -> Dict:
        """
        Save an openpyxl Workbook and upload it to SharePoint.

        Args:
            path: File path relative to drive root.
            wb:   openpyxl.Workbook to save.

        Returns:
            Graph API response dict (file metadata).
        """
        buf = BytesIO()
        wb.save(buf)
        return self.write_file(path, buf.getvalue())

    # ------------------------------------------------------------------
    # Debug / verification
    # ------------------------------------------------------------------

    def verify_connection(self) -> Dict:
        """
        Test auth + site access. Returns site metadata dict on success.
        Raises SharePointError with a helpful message on failure.

        Use this to validate credentials before doing any real work:
            client = SharePointClient.from_env()
            info = client.verify_connection()
            print(f"Connected to: {info['displayName']}")
        """
        site_id = self._resolve_site()
        url = f"{GRAPH_BASE}/sites/{site_id}"
        resp = self._session.get(url, headers=self._headers())

        if resp.status_code != 200:
            raise SharePointError(
                f"Site verification failed ({resp.status_code}): {resp.text[:400]}"
            )

        data = resp.json()
        # Also confirm drive is accessible
        drive_id = self._resolve_drive()

        return {
            "site_id":      site_id,
            "drive_id":     drive_id,
            "display_name": data.get("displayName"),
            "web_url":      data.get("webUrl"),
        }
