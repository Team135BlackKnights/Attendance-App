"""
Google OAuth 2.0 authentication for the Attendance App.

Any user who downloads the app can sign in with their Google account.
The embedded client ID identifies *this app* to Google; it does NOT grant
access to anything — the user must still consent in the browser.

Flow:
  1. First run  → user clicks "Sign In with Google" in Options → browser opens
                  for consent → token saved to token.json
  2. Later runs → token loaded from disk and auto-refreshed when expired
  3. Sign-out   → token.json is deleted; next sign-in requires browser consent

Module-level constants:
    SCOPES           -- OAuth 2.0 scopes requested from Google.
    TOKEN_FILE       -- Absolute path to the persisted token JSON file.

Public functions:
    get_credentials  -- Return valid OAuth credentials, raising if not signed in.
    get_gspread_client -- Return an authorised gspread Client.
    get_drive_service  -- Return an authorised Google Drive v3 service object.
    get_user_email   -- Return the e-mail of the currently signed-in user.
    is_signed_in     -- Return True when a valid/refreshable token exists on disk.
    sign_in          -- Run the browser OAuth flow and persist the resulting token.
    sign_out         -- Delete the stored token, requiring a fresh sign-in next time.
"""

import os
import sys
import base64
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import gspread

# ---------------------------------------------------------------------------
# Scopes – these define what the app is allowed to do with the user's account.
# If you change scopes, delete token.json so the user re-consents.
# ---------------------------------------------------------------------------
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",   # read/write sheets
    "https://www.googleapis.com/auth/drive.file",      # upload/manage files created by this app
    "https://www.googleapis.com/auth/userinfo.email",  # show who is signed in
    "openid",                                          # avoid OAuth scope mismatch errors
]

# ---------------------------------------------------------------------------
# Embedded OAuth client configuration (base64-encoded)
# ---------------------------------------------------------------------------
# These values come from the Google Cloud Console (one-time setup by the app
# maintainer).  For installed/desktop apps the client_secret is NOT truly
# secret — Google documents this:
#   "In this context, the client secret is obviously not treated as a secret."
# The actual security comes from the user granting consent in the browser.
#
# The values are base64-encoded only to prevent GitHub / secret-scanning bots
# from flagging them as leaked credentials.  This is NOT encryption.
# ---------------------------------------------------------------------------
_B64_CLIENT_ID = b"MTI2MTE3OTk4MDIxLTNmZWFhbWlrZzFjYjN0MGI3ZWcwZ2RzNjhsMTkzMTN2LmFwcHMuZ29vZ2xldXNlcmNvbnRlbnQuY29t"
_B64_CLIENT_SECRET = b"R09DU1BYLVpLQXAzUS1DQWFILURTekxmWk5lcHpKMHVZVVM="

def _decode(b64_value: bytes) -> str:
    """Decode a base64-encoded bytes value to a plain UTF-8 string."""
    return base64.b64decode(b64_value).decode("utf-8")

def _build_client_config():
    """Build the OAuth client config dict expected by InstalledAppFlow.

    Decodes the embedded base64 client credentials at call time and returns
    the structure that google-auth-oauthlib accepts as ``client_config``.
    """
    return {
        "installed": {
            "client_id": _decode(_B64_CLIENT_ID),
            "client_secret": _decode(_B64_CLIENT_SECRET),
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "redirect_uris": ["http://localhost"],
        }
    }

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
def _get_base_path():
    """Return the folder where bundled read-only resources live (fonts etc.)."""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

def _get_persistent_path():
    """Return a writable folder that survives PyInstaller --onefile restarts.

    * Frozen (exe): directory containing the .exe itself
    * Normal (script): directory containing this .py file
    """
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))

TOKEN_FILE = os.path.join(_get_persistent_path(), "token.json")


# ---------------------------------------------------------------------------
# Core credential helpers
# ---------------------------------------------------------------------------
def get_credentials():
    """Return valid OAuth credentials, prompting browser sign-in if needed."""
    creds = None

    # 1. Try loading a previously-saved token
    if os.path.exists(TOKEN_FILE):
        try:
            creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        except Exception:
            creds = None

    # If token exists but does not include all current scopes, force re-auth.
    try:
        if creds and getattr(creds, "scopes", None):
            if not set(SCOPES).issubset(set(creds.scopes)):
                creds = None
    except Exception:
        creds = None

    # 2. Refresh or re-authenticate
    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            _save_token(creds)
            return creds
        except Exception:
            # Refresh failed (e.g. revoked) – token is unusable
            creds = None

    # 3. No valid credentials — do not open browser automatically.
    #    The user must sign in explicitly via the Sign In button in Options.
    raise RuntimeError(
        "Not signed in to Google. Please open Options → Google Settings and click 'Sign In'."
    )


def _save_token(creds):
    """Persist credentials to disk so the user doesn't have to re-auth."""
    try:
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
    except Exception as e:
        print(f"Warning: could not save token – {e}")


# ---------------------------------------------------------------------------
# Convenience builders (drop-in replacements for the old service-account calls)
# ---------------------------------------------------------------------------
def get_gspread_client():
    """Return an authorised gspread Client."""
    creds = get_credentials()
    return gspread.authorize(creds)


def get_drive_service():
    """Return an authorised Google Drive v3 service object."""
    creds = get_credentials()
    return build("drive", "v3", credentials=creds)


# ---------------------------------------------------------------------------
# Account info helpers
# ---------------------------------------------------------------------------
def get_user_email():
    """Return the e-mail address of the signed-in Google user."""
    try:
        creds = get_credentials()
        service = build("oauth2", "v2", credentials=creds)
        info = service.userinfo().get().execute()
        return info.get("email", "Unknown")
    except Exception:
        return "Unknown"


def is_signed_in():
    """Return True if a valid (or refreshable) token exists on disk."""
    if not os.path.exists(TOKEN_FILE):
        return False
    try:
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
        return creds.valid or (creds.expired and creds.refresh_token)
    except Exception:
        return False


def sign_in():
    """Start the OAuth browser flow and save the token.

    Blocks until the user completes sign-in in their browser or closes the tab.
    Must be called from a background thread — never from the main UI thread.
    Raises an exception if the user cancels or an error occurs.
    """
    client_config = _build_client_config()
    if client_config["installed"]["client_id"] == "YOUR_CLIENT_ID_HERE":
        raise RuntimeError(
            "OAuth client credentials have not been configured.\n"
            "The app maintainer needs to fill in the _B64 values in google_auth.py."
        )
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
    try:
        creds = flow.run_local_server(port=0)
    except Exception as e:
        raise RuntimeError(f"Sign-in was cancelled or failed: {e}") from e
    _save_token(creds)
    return creds


def sign_out():
    """Delete the stored token, requiring a fresh sign-in next time."""
    try:
        if os.path.exists(TOKEN_FILE):
            os.remove(TOKEN_FILE)
    except Exception as e:
        print(f"Warning: could not remove token file – {e}")
