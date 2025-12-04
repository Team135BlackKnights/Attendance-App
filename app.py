import os
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"
from flask import Flask, request, jsonify, redirect, session, url_for
import json
from datetime import datetime
import io
import traceback

from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "supersecret")  # required for session

# OAuth config
CLIENT_SECRETS_FILE = "client_secrets.json"  # downloaded from Google Cloud OAuth credentials
SCOPES = [
    "https://www.googleapis.com/auth/drive.file"
]
REDIRECT_URI = "http://localhost:8080/oauth2callback"  # must match OAuth redirect URI in Google Cloud

# Local storage for tokens (for demo; in prod, use a DB)
USER_TOKENS_FILE = "user_tokens.json"
if not os.path.exists(USER_TOKENS_FILE):
    with open(USER_TOKENS_FILE, "w") as f:
        json.dump({}, f)

DB_FILE = "attendance_db.json"   # local log copy (still kept for backup/local debugging)
SHEETS_INDEX_FILE = "sheets_db.json"  # local index of known spreadsheets (for convenience)
UPLOAD_TEMP_FOLDER = "uploaded_images_temp"
DEFAULT_IMAGE_FOLDER = "Attendance"  # parent folder name
DEFAULT_IMAGES_SUBFOLDER = "Images"  # images folder inside Attendance
DEFAULT_SHEET_TAB = "Attendance"
DEFAULT_DB_SHEET = "Attendance Database"
DEFAULT_HEADERS = ["ID", "Name", "Date", "Reason", "Image URL"]

os.makedirs(UPLOAD_TEMP_FOLDER, exist_ok=True)

# Initialize local files
for f, default in [(DB_FILE, []), (SHEETS_INDEX_FILE, [])]:
    if not os.path.exists(f):
        with open(f, "w") as fh:
            json.dump(default, fh)


def save_user_token(user_email, creds_dict):
    tokens = json.load(open(USER_TOKENS_FILE))
    tokens[user_email] = creds_dict
    with open(USER_TOKENS_FILE, "w") as f:
        json.dump(tokens, f, indent=2)


def load_user_token(user_email):
    tokens = json.load(open(USER_TOKENS_FILE))
    return tokens.get(user_email)


def get_user_credentials(user_email):
    token_dict = load_user_token(user_email)
    if not token_dict:
        return None
    creds = Credentials.from_authorized_user_info(token_dict, SCOPES)
    return creds


def get_drive_service(user_email):
    creds = get_user_credentials(user_email)
    if not creds or not creds.valid:
        return None
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def get_sheets_service(user_email):
    creds = get_user_credentials(user_email)
    if not creds or not creds.valid:
        return None
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


# --------------------------
# OAuth login flow
# --------------------------
@app.route("/login")
def login():
    """
    Start OAuth flow. Stores state in session to validate callback.
    """
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=REDIRECT_URI
    )
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true',
        prompt='consent'
    )
    # store state in session to validate on callback
    session['state'] = state
    app.logger.debug("Starting OAuth flow. state=%s auth_url=%s", state, authorization_url)
    return redirect(authorization_url)


@app.route("/oauth2callback")
def oauth2callback():
    """
    OAuth callback. Validates state and exchanges code for tokens.
    Returns descriptive error messages and logs full traceback for debugging.
    """
    # debug prints to help root-cause "unknown error"
    app.logger.debug("Oauth2 callback hit. request.url=%s", request.url)
    app.logger.debug("Session keys: %s", list(session.keys()))

    state = session.get('state')
    if not state:
        # important: missing state usually means session cookie not preserved
        err_msg = ("Missing 'state' in session. This means the session cookie wasn't preserved "
                   "between /login and /oauth2callback. Ensure your browser accepts cookies for "
                   "localhost and that the same host/port is used. If you navigated to the callback "
                   "directly (instead of via /login), don't do that — start at /login.")
        app.logger.error(err_msg)
        return f"OAuth error: {err_msg}", 400

    # Recreate the Flow with the same state and redirect URI
    flow = Flow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        state=state,
        redirect_uri=REDIRECT_URI
    )

    try:
        # exchange code for tokens. We pass the full callback URL received from Google.
        flow.fetch_token(authorization_response=request.url)
    except Exception as e:
        # log full traceback server-side for debugging
        tb = traceback.format_exc()
        app.logger.error("Error fetching token: %s\n%s", repr(e), tb)
        # return a useful error to browser so you don't get "unknown error"
        return jsonify({
            "status": "error",
            "message": "Failed to fetch token during OAuth callback.",
            "error": str(e),
            "traceback": tb.splitlines()[-5:]  # send last few lines for convenience
        }), 500

    creds = flow.credentials
    if not creds or not creds.token:
        app.logger.error("No credentials or token returned from flow: %r", creds)
        return jsonify({"status": "error", "message": "No credentials returned from OAuth flow."}), 500

    # For demo we accept user email via query param fallback; prefer to use session or client side
    user_email = request.args.get("email", None)
    # If email not supplied, optionally try to extract 'email' from id_token if present (best-effort)
    id_token_info = None
    try:
        # flow.credentials may include id_token if OpenID scope was requested. do not assume present.
        if getattr(creds, "id_token", None):
            id_token_info = creds.id_token  # note: this is raw JWT payload, may or may not include email
            # Attempt to get an 'email' claim (if present) — may be None
            # creds._id_token is not guaranteed; so we check the attribute directly
            # (we are not parsing JWT here; this is a best-effort read)
    except Exception:
        pass

    if not user_email:
        # fallback: use a default so token is stored under some key (better than losing creds)
        user_email = "user@example.com"

    # Save token dict for later API calls
    save_user_token(user_email, {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes
    })

    app.logger.info("OAuth completed for user_email=%s", user_email)
    return f"Authentication successful for {user_email}. You can now use the API."


# --------------------------
# Drive helpers
# --------------------------
def find_child_folder_by_name(drive_service, parent_folder_id, folder_name):
    """Find a folder by name. If parent_folder_id is provided, search inside it; otherwise search globally."""
    safe_name = folder_name.replace("'", "\\'")
    if parent_folder_id:
        q = f"name = '{safe_name}' and mimeType='application/vnd.google-apps.folder' and '{parent_folder_id}' in parents and trashed=false"
    else:
        q = f"name = '{safe_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false"
    res = drive_service.files().list(q=q, fields="files(id, name)").execute()
    files = res.get("files", [])
    return files[0] if files else None


def create_child_folder(drive_service, parent_folder_id, folder_name):
    body = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_folder_id:
        body["parents"] = [parent_folder_id]
    file = drive_service.files().create(body=body, fields="id, name").execute()
    return file


def ensure_attendance_structure(drive_service, parent_folder_id=None,
                                attendance_name=DEFAULT_IMAGE_FOLDER,
                                images_name=DEFAULT_IMAGES_SUBFOLDER):
    """
    Ensure an 'Attendance' folder exists under parent_folder_id (or root if None),
    and an 'Images' subfolder exists inside the Attendance folder.
    Returns a tuple: (attendance_folder_dict, images_folder_dict)
    """
    # Find or create Attendance parent folder (under parent_folder_id or root)
    attendance_folder = find_child_folder_by_name(drive_service, parent_folder_id, attendance_name)
    if not attendance_folder:
        attendance_folder = create_child_folder(drive_service, parent_folder_id, attendance_name)

    # Inside Attendance, find or create Images folder
    images_folder = find_child_folder_by_name(drive_service, attendance_folder["id"], images_name)
    if not images_folder:
        images_folder = create_child_folder(drive_service, attendance_folder["id"], images_name)

    return attendance_folder, images_folder


def upload_file_to_drive(drive_service, file_stream, filename, mimetype, folder_id=None, make_public=True, share_with_email=None):
    """Upload a file to Drive under folder_id, make public, optionally share."""
    metadata = {"name": filename}
    if folder_id:
        metadata["parents"] = [folder_id]

    media = MediaIoBaseUpload(file_stream, mimetype=mimetype, resumable=False)
    created = drive_service.files().create(body=metadata, media_body=media, fields="id, name, webViewLink, webContentLink").execute()
    file_id = created.get("id")

    # make public
    if make_public:
        try:
            drive_service.permissions().create(
                fileId=file_id,
                body={"type": "anyone", "role": "reader"},
                fields="id"
            ).execute()
        except Exception as e:
            print("Warning setting public permission:", e)

    # Share with owner_email
    if share_with_email:
        try:
            drive_service.permissions().create(
                fileId=file_id,
                body={"type": "user", "role": "writer", "emailAddress": share_with_email},
                fields="id",
                sendNotificationEmail=False
            ).execute()
        except Exception as e:
            print("Warning sharing file with owner_email:", e)

    # Get file metadata (webViewLink)
    meta = drive_service.files().get(fileId=file_id, fields="id, name, webViewLink, webContentLink").execute()
    return meta


# --------------------------
# Sheets helpers
# --------------------------
def find_spreadsheet_by_title(drive_service, title, parent_folder_id=None):
    """Search for spreadsheets by title in Drive (optionally inside parent folder)."""
    safe_title = title.replace("'", "\\'")
    if parent_folder_id:
        q = f"name = '{safe_title}' and mimeType = 'application/vnd.google-apps.spreadsheet' and '{parent_folder_id}' in parents and trashed=false"
    else:
        q = f"name = '{safe_title}' and mimeType = 'application/vnd.google-apps.spreadsheet' and trashed=false"
    res = drive_service.files().list(q=q, fields="files(id, name)").execute()
    files = res.get("files", [])
    return files[0] if files else None


def create_spreadsheet(sheets_service, title, tabs=None, share_with_email=None, parent_folder_id=None, user_email=None):
    """Create spreadsheet, add to parent folder, optionally share with owner."""
    body = {"properties": {"title": title}}
    if tabs:
        body["sheets"] = [{"properties": {"title": t}} for t in tabs]
    created = sheets_service.spreadsheets().create(body=body, fields="spreadsheetId, properties/title").execute()
    spreadsheet_id = created["spreadsheetId"]

    if parent_folder_id:
        try:
            drive = get_drive_service(user_email)
            drive.files().update(fileId=spreadsheet_id, addParents=parent_folder_id, fields="id, parents").execute()
        except Exception as e:
            print("Warning adding spreadsheet to parent folder:", e)

    if share_with_email:
        try:
            drive = get_drive_service(user_email)
            drive.permissions().create(
                fileId=spreadsheet_id,
                body={"type": "user", "role": "writer", "emailAddress": share_with_email},
                fields="id",
                sendNotificationEmail=False
            ).execute()
        except Exception as e:
            print("Warning sharing spreadsheet with owner_email:", e)

    return created


def get_sheet_titles(sheets_service, spreadsheet_id):
    meta = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets(properties(title,sheetId))").execute()
    sheets = meta.get("sheets", [])
    return [s["properties"]["title"] for s in sheets]


def create_subsheet_if_missing(sheets_service, spreadsheet_id, sheet_title):
    titles = get_sheet_titles(sheets_service, spreadsheet_id)
    if sheet_title in titles:
        return True
    body = {"requests": [{"addSheet": {"properties": {"title": sheet_title}}}]}
    sheets_service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()
    return True


def delete_subsheet_if_exists(sheets_service, spreadsheet_id, sheet_title):
    meta = sheets_service.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="sheets(properties(title,sheetId))").execute()
    sheets = meta.get("sheets", [])
    target_id = None
    for s in sheets:
        if s["properties"]["title"] == sheet_title:
            target_id = s["properties"]["sheetId"]
            break
    if target_id is None:
        return False, "Sheet not found"
    body = {"requests": [{"deleteSheet": {"sheetId": target_id}}]}
    sheets_service.spreadsheets().batchUpdate(spreadsheetId=spreadsheet_id, body=body).execute()
    return True, None


def column_index_to_letter(col_idx):
    letters = ""
    while col_idx > 0:
        col_idx, remainder = divmod(col_idx - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def find_next_available_row(sheets_service, spreadsheet_id, sheet_title, start_col_idx=1):
    start_col_letter = column_index_to_letter(start_col_idx)
    range_a1 = f"'{sheet_title}'!{start_col_letter}:{start_col_letter}"
    result = sheets_service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_a1).execute()
    values = result.get("values", [])
    return len(values) + 1


def append_row_at_column(sheets_service, spreadsheet_id, sheet_title, start_col_idx, row_values):
    next_row = find_next_available_row(sheets_service, spreadsheet_id, sheet_title, start_col_idx)
    start_col_letter = column_index_to_letter(start_col_idx)
    end_col_letter = column_index_to_letter(start_col_idx + len(row_values) - 1)
    range_a1 = f"'{sheet_title}'!{start_col_letter}{next_row}:{end_col_letter}{next_row}"
    body = {"values": [row_values]}
    sheets_service.spreadsheets().values().update(spreadsheetId=spreadsheet_id, range=range_a1,
                                                 valueInputOption="RAW", body=body).execute()
    return {"row": next_row, "range": range_a1}


def find_name_by_id(sheets_service, spreadsheet_id, sheet_title, target_id, id_col_idx=1, name_col_idx=2):
    id_col_letter = column_index_to_letter(id_col_idx)
    name_col_letter = column_index_to_letter(name_col_idx)
    range_a1 = f"'{sheet_title}'!{id_col_letter}:{name_col_letter}"
    result = sheets_service.spreadsheets().values().get(spreadsheetId=spreadsheet_id, range=range_a1).execute()
    values = result.get("values", [])
    for row in values:
        if not row:
            continue
        if len(row) >= 1 and str(row[0]) == str(target_id):
            return row[1] if len(row) > 1 else None
    return None


# --------------------------
# Local DB helpers
# --------------------------
def load_local_db(file):
    with open(file, "r") as f:
        return json.load(f)


def save_local_db(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=2)


# --------------------------
# API Endpoints
# --------------------------
@app.route("/api/upload_image", methods=["POST"])
def upload_image():
    user_email = request.form.get("user_email")
    if not user_email:
        return jsonify({"status": "error", "message": "user_email required"}), 400

    drive = get_drive_service(user_email)
    if not drive:
        return jsonify({"status": "error", "message": "Invalid or expired credentials. Please re-login."}), 401

    if "image" not in request.files:
        return jsonify({"status": "error", "message": "No image uploaded"}), 400

    img = request.files["image"]
    parent_folder_id = request.form.get("parent_folder_id")  # optional: where to place Attendance (or root)
    owner_email = request.form.get("owner_email")

    # Ensure Attendance parent and Images subfolder exist (under parent_folder_id or root)
    attendance_folder, images_folder = ensure_attendance_structure(drive, parent_folder_id, attendance_name=DEFAULT_IMAGE_FOLDER, images_name=DEFAULT_IMAGES_SUBFOLDER)
    if not attendance_folder or not images_folder:
        return jsonify({"status": "error", "message": "Failed to create/find Attendance or Images folder"}), 500

    filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{img.filename}"
    temp_path = os.path.join(UPLOAD_TEMP_FOLDER, filename)
    img.save(temp_path)

    with io.FileIO(temp_path, "rb") as fh:
        file_stream = io.BytesIO(fh.read())
    mimetype = img.mimetype or "application/octet-stream"

    # Upload directly into Attendance/Images folder
    file_meta = upload_file_to_drive(drive, file_stream, filename, mimetype, folder_id=images_folder["id"], make_public=True, share_with_email=owner_email)

    try:
        os.remove(temp_path)
    except Exception:
        pass

    return jsonify({"status": "success", "file": file_meta})


@app.route("/api/record_attendance", methods=["POST"])
def record_attendance():
    user_email = request.json.get("user_email")
    if not user_email:
        return jsonify({"status": "error", "message": "user_email required"}), 400

    drive = get_drive_service(user_email)
    sheets = get_sheets_service(user_email)
    if not drive or not sheets:
        return jsonify({"status": "error", "message": "Invalid or expired credentials. Please re-login."}), 401

    data = request.get_json()
    required = ["id", "name", "date"]
    if not data or not all(k in data for k in required):
        return jsonify({"status": "error", "message": "Missing required fields (id,name,date)"}), 400

    spreadsheet_id = data.get("spreadsheet_id")
    spreadsheet_title = data.get("spreadsheet_title", f"{data.get('owner_email','user')}_Attendance")
    sheet_tab = data.get("sheet_tab", DEFAULT_SHEET_TAB)
    owner_email = data.get("owner_email")
    start_col = int(data.get("start_col", 1))
    parent_folder_id = data.get("parent_folder_id")  # optional: where to place Attendance (or root)

    # Ensure Attendance parent and Images subfolder exist (under parent_folder_id or root)
    attendance_folder, images_folder = ensure_attendance_structure(drive, parent_folder_id, attendance_name=DEFAULT_IMAGE_FOLDER, images_name=DEFAULT_IMAGES_SUBFOLDER)
    parent_for_spreadsheet = attendance_folder["id"] if attendance_folder else parent_folder_id

    # Locate or create spreadsheet under Attendance parent
    if spreadsheet_id:
        # Optionally check existence
        try:
            _ = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="spreadsheetId").execute()
        except Exception as e:
            return jsonify({"status": "error", "message": f"Spreadsheet not found: {e}"}), 400
    else:
        found = find_spreadsheet_by_title(drive, spreadsheet_title, parent_folder_id=parent_for_spreadsheet)
        if found:
            spreadsheet_id = found["id"]
        else:
            created = create_spreadsheet(sheets, spreadsheet_title, tabs=[sheet_tab], share_with_email=owner_email, parent_folder_id=parent_for_spreadsheet, user_email=user_email)
            spreadsheet_id = created["spreadsheetId"]
            # Put default headers in first row at start_col
            headers_range = f"'{sheet_tab}'!{column_index_to_letter(start_col)}1:{column_index_to_letter(start_col+len(DEFAULT_HEADERS)-1)}1"
            sheets.spreadsheets().values().update(spreadsheetId=spreadsheet_id, range=headers_range,
                                                 valueInputOption="RAW", body={"values": [DEFAULT_HEADERS]}).execute()

    # Ensure sheet_tab exists
    create_subsheet_if_missing(sheets, spreadsheet_id, sheet_tab)

    # Build the record row (order matches DEFAULT_HEADERS)
    row = [data["id"], data["name"], data["date"], data.get("reason", ""), data.get("image_url", "")]
    append_info = append_row_at_column(sheets, spreadsheet_id, sheet_tab, start_col, row)

    # Log locally as backup
    records = load_local_db(DB_FILE)
    record = {
        "spreadsheet_id": spreadsheet_id,
        "sheet_tab": sheet_tab,
        "id": data["id"],
        "name": data["name"],
        "date": data["date"],
        "reason": data.get("reason"),
        "image_url": data.get("image_url"),
        "start_col": start_col,
        "row_written": append_info["row"],
        "range": append_info["range"],
        "timestamp": datetime.utcnow().isoformat()
    }
    records.append(record)
    save_local_db(DB_FILE, records)

    return jsonify({"status": "success", "record": record})


@app.route("/api/list_subsheets", methods=["GET"])
def list_subsheets():
    spreadsheet_id = request.args.get("spreadsheet_id")
    spreadsheet_title = request.args.get("spreadsheet_title")
    parent_folder_id = request.args.get("parent_folder_id")  # optional
    user_email = request.args.get("user_email")
    if not user_email:
        return jsonify({"status": "error", "message": "user_email required"}), 400

    drive = get_drive_service(user_email)
    sheets = get_sheets_service(user_email)
    if not drive or not sheets:
        return jsonify({"status": "error", "message": "Invalid or expired credentials. Please re-login."}), 401

    if not spreadsheet_id:
        if not spreadsheet_title:
            return jsonify({"status": "error", "message": "spreadsheet_id or spreadsheet_title required"}), 400
        # Try searching inside Attendance folder (if parent_folder_id provided or root)
        attendance_folder, images_folder = ensure_attendance_structure(drive, parent_folder_id, attendance_name=DEFAULT_IMAGE_FOLDER, images_name=DEFAULT_IMAGES_SUBFOLDER)
        search_parent = attendance_folder["id"] if attendance_folder else parent_folder_id
        found = find_spreadsheet_by_title(drive, spreadsheet_title, parent_folder_id=search_parent)
        if not found:
            return jsonify({"status": "error", "message": "Spreadsheet not found"}), 404
        spreadsheet_id = found["id"]

    try:
        titles = get_sheet_titles(sheets, spreadsheet_id)
        return jsonify({"status": "success", "sheets": titles})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 400


@app.route("/api/create_subsheet", methods=["POST"])
def create_subsheet():
    data = request.get_json()
    subsheet_name = data.get("subsheet_name")
    spreadsheet_id = data.get("spreadsheet_id")
    spreadsheet_title = data.get("spreadsheet_title")
    owner_email = data.get("owner_email")
    parent_folder_id = data.get("parent_folder_id")
    user_email = data.get("user_email")

    if not user_email:
        return jsonify({"status": "error", "message": "user_email required"}), 400

    if not subsheet_name:
        return jsonify({"status": "error", "message": "subsheet_name required"}), 400

    drive = get_drive_service(user_email)
    sheets = get_sheets_service(user_email)
    if not drive or not sheets:
        return jsonify({"status": "error", "message": "Invalid or expired credentials. Please re-login."}), 401

    attendance_folder, images_folder = ensure_attendance_structure(drive, parent_folder_id, attendance_name=DEFAULT_IMAGE_FOLDER, images_name=DEFAULT_IMAGES_SUBFOLDER)
    parent_for_spreadsheet = attendance_folder["id"] if attendance_folder else parent_folder_id

    if not spreadsheet_id:
        if not spreadsheet_title:
            return jsonify({"status": "error", "message": "spreadsheet_id or spreadsheet_title required"}), 400
        found = find_spreadsheet_by_title(drive, spreadsheet_title, parent_folder_id=parent_for_spreadsheet)
        if not found:
            created = create_spreadsheet(sheets, spreadsheet_title, tabs=[subsheet_name], share_with_email=owner_email, parent_folder_id=parent_for_spreadsheet, user_email=user_email)
            spreadsheet_id = created["spreadsheetId"]
            return jsonify({"status": "success", "spreadsheet_id": spreadsheet_id, "sheet": subsheet_name})
        spreadsheet_id = found["id"]

    create_subsheet_if_missing(sheets, spreadsheet_id, subsheet_name)
    return jsonify({"status": "success", "spreadsheet_id": spreadsheet_id, "sheet": subsheet_name})


@app.route("/api/delete_subsheet", methods=["POST"])
def delete_subsheet():
    data = request.get_json()
    subsheet_name = data.get("subsheet_name")
    spreadsheet_id = data.get("spreadsheet_id")
    spreadsheet_title = data.get("spreadsheet_title")
    parent_folder_id = data.get("parent_folder_id")
    user_email = data.get("user_email")

    if not user_email:
        return jsonify({"status": "error", "message": "user_email required"}), 400
    if not subsheet_name:
        return jsonify({"status": "error", "message": "subsheet_name required"}), 400

    drive = get_drive_service(user_email)
    sheets = get_sheets_service(user_email)
    if not drive or not sheets:
        return jsonify({"status": "error", "message": "Invalid or expired credentials. Please re-login."}), 401

    attendance_folder, images_folder = ensure_attendance_structure(drive, parent_folder_id, attendance_name=DEFAULT_IMAGE_FOLDER, images_name=DEFAULT_IMAGES_SUBFOLDER)
    parent_for_search = attendance_folder["id"] if attendance_folder else parent_folder_id

    if not spreadsheet_id:
        if not spreadsheet_title:
            return jsonify({"status": "error", "message": "spreadsheet_id or spreadsheet_title required"}), 400
        found = find_spreadsheet_by_title(drive, spreadsheet_title, parent_folder_id=parent_for_search)
        if not found:
            return jsonify({"status": "error", "message": "Spreadsheet not found"}), 404
        spreadsheet_id = found["id"]

    success, err = delete_subsheet_if_exists(sheets, spreadsheet_id, subsheet_name)
    if not success:
        return jsonify({"status": "error", "message": err}), 400
    return jsonify({"status": "success", "spreadsheet_id": spreadsheet_id, "deleted": subsheet_name})


@app.route("/api/write_row", methods=["POST"])
def write_row():
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    user_email = data.get("user_email")
    if not user_email:
        return jsonify({"status": "error", "message": "user_email required"}), 400

    row_values = data.get("row")
    sheet_tab = data.get("sheet_tab")
    if not row_values or not sheet_tab:
        return jsonify({"status": "error", "message": "row and sheet_tab required"}), 400

    start_col = int(data.get("start_col", 1))
    spreadsheet_id = data.get("spreadsheet_id")
    spreadsheet_title = data.get("spreadsheet_title")
    owner_email = data.get("owner_email")
    parent_folder_id = data.get("parent_folder_id")

    drive = get_drive_service(user_email)
    sheets = get_sheets_service(user_email)
    if not drive or not sheets:
        return jsonify({"status": "error", "message": "Invalid or expired credentials. Please re-login."}), 401

    attendance_folder, images_folder = ensure_attendance_structure(drive, parent_folder_id, attendance_name=DEFAULT_IMAGE_FOLDER, images_name=DEFAULT_IMAGES_SUBFOLDER)
    parent_for_spreadsheet = attendance_folder["id"] if attendance_folder else parent_folder_id

    if not spreadsheet_id:
        if not spreadsheet_title:
            return jsonify({"status": "error", "message": "spreadsheet_id or spreadsheet_title required"}), 400
        found = find_spreadsheet_by_title(drive, spreadsheet_title, parent_folder_id=parent_for_spreadsheet)
        if not found:
            created = create_spreadsheet(sheets, spreadsheet_title, tabs=[sheet_tab], share_with_email=owner_email, parent_folder_id=parent_for_spreadsheet, user_email=user_email)
            spreadsheet_id = created["spreadsheetId"]
        else:
            spreadsheet_id = found["id"]

    # ensure subsheet exists
    create_subsheet_if_missing(sheets, spreadsheet_id, sheet_tab)
    append_info = append_row_at_column(sheets, spreadsheet_id, sheet_tab, start_col, row_values)

    return jsonify({"status": "success", "append_info": append_info})


@app.route("/api/write_id_name", methods=["POST"])
def write_id_name():
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400

    user_email = data.get("user_email")
    if not user_email:
        return jsonify({"status": "error", "message": "user_email required"}), 400

    if "id" not in data or "name" not in data:
        return jsonify({"status": "error", "message": "id and name required"}), 400

    sheet_tab = data.get("sheet_tab", DEFAULT_DB_SHEET)
    start_col = int(data.get("start_col", 1))
    spreadsheet_id = data.get("spreadsheet_id")
    spreadsheet_title = data.get("spreadsheet_title", f"{data.get('owner_email','user')}_AttendanceDB")
    owner_email = data.get("owner_email")
    parent_folder_id = data.get("parent_folder_id")

    drive = get_drive_service(user_email)
    sheets = get_sheets_service(user_email)
    if not drive or not sheets:
        return jsonify({"status": "error", "message": "Invalid or expired credentials. Please re-login."}), 401

    attendance_folder, images_folder = ensure_attendance_structure(drive, parent_folder_id, attendance_name=DEFAULT_IMAGE_FOLDER, images_name=DEFAULT_IMAGES_SUBFOLDER)
    parent_for_spreadsheet = attendance_folder["id"] if attendance_folder else parent_folder_id

    if not spreadsheet_id:
        found = find_spreadsheet_by_title(drive, spreadsheet_title, parent_folder_id=parent_for_spreadsheet)
        if not found:
            created = create_spreadsheet(sheets, spreadsheet_title, tabs=[sheet_tab], share_with_email=owner_email, parent_folder_id=parent_for_spreadsheet, user_email=user_email)
            spreadsheet_id = created["spreadsheetId"]
            # Add headers
            headers_range = f"'{sheet_tab}'!{column_index_to_letter(start_col)}1:{column_index_to_letter(start_col+1)}1"
            sheets.spreadsheets().values().update(spreadsheetId=spreadsheet_id, range=headers_range,
                                                 valueInputOption="RAW", body={"values": [["ID", "Name"]]}).execute()
        else:
            spreadsheet_id = found["id"]

    create_subsheet_if_missing(sheets, spreadsheet_id, sheet_tab)
    append_info = append_row_at_column(sheets, spreadsheet_id, sheet_tab, start_col, [data["id"], data["name"]])

    return jsonify({"status": "success", "append_info": append_info})


@app.route("/api/find_id", methods=["GET"])
def find_id():
    spreadsheet_id = request.args.get("spreadsheet_id")
    spreadsheet_title = request.args.get("spreadsheet_title")
    sheet_tab = request.args.get("sheet_tab")
    target_id = request.args.get("id")
    id_col_idx = int(request.args.get("id_col_idx", 1))
    name_col_idx = int(request.args.get("name_col_idx", 2))
    parent_folder_id = request.args.get("parent_folder_id")
    user_email = request.args.get("user_email")

    if not user_email:
        return jsonify({"status": "error", "message": "user_email required"}), 400
    if not sheet_tab or not target_id:
        return jsonify({"status": "error", "message": "sheet_tab and id required"}), 400

    drive = get_drive_service(user_email)
    sheets = get_sheets_service(user_email)
    if not drive or not sheets:
        return jsonify({"status": "error", "message": "Invalid or expired credentials. Please re-login."}), 401

    attendance_folder, images_folder = ensure_attendance_structure(drive, parent_folder_id, attendance_name=DEFAULT_IMAGE_FOLDER, images_name=DEFAULT_IMAGES_SUBFOLDER)
    parent_for_search = attendance_folder["id"] if attendance_folder else parent_folder_id

    if not spreadsheet_id:
        if not spreadsheet_title:
            return jsonify({"status": "error", "message": "spreadsheet_id or spreadsheet_title required"}), 400
        found = find_spreadsheet_by_title(drive, spreadsheet_title, parent_folder_id=parent_for_search)
        if not found:
            return jsonify({"status": "error", "message": "Spreadsheet not found"}), 404
        spreadsheet_id = found["id"]

    name = find_name_by_id(sheets, spreadsheet_id, sheet_tab, target_id, id_col_idx, name_col_idx)
    if name is None:
        return jsonify({"status": "not_found", "id": target_id}), 404
    return jsonify({"status": "success", "id": target_id, "name": name})


@app.route("/", methods=["GET"])
def home():
    return "Attendance API is running!"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 80)), debug=True)
    print("it is working")
