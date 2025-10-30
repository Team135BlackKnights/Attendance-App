from flask import Flask, request, jsonify
import os
import json
from datetime import datetime
import io

# Google API imports
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload

app = Flask(__name__)

SERVICE_ACCOUNT_FILE = "service_account.json"
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/spreadsheets",
]

DB_FILE = "attendance_db.json"   # local log copy (still kept for backup/local debugging)
SHEETS_INDEX_FILE = "sheets_db.json"  # local index of known spreadsheets (for convenience)
UPLOAD_TEMP_FOLDER = "uploaded_images_temp"
DEFAULT_IMAGE_FOLDER = "Attendance Images"
DEFAULT_SHEET_TAB = "Attendance"
DEFAULT_DB_SHEET = "Attendance Database"
DEFAULT_HEADERS = ["ID", "Name", "Date", "Reason", "Image URL"]

os.makedirs(UPLOAD_TEMP_FOLDER, exist_ok=True)

# Initialize local files
for f, default in [(DB_FILE, []), (SHEETS_INDEX_FILE, [])]:
    if not os.path.exists(f):
        with open(f, "w") as fh:
            json.dump(default, fh)


def get_credentials():
    """Return service account credentials."""
    creds = Credentials.from_service_account_file(SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    return creds


def get_drive_service():
    creds = get_credentials()
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def get_sheets_service():
    creds = get_credentials()
    return build("sheets", "v4", credentials=creds, cache_discovery=False)


# --------------------------
# Drive helpers (scoped to parent folder)
# --------------------------
def find_child_folder_by_name(drive_service, parent_folder_id, folder_name):
    """Find a folder inside parent_folder_id with exact name. Return file dict or None."""
    if not parent_folder_id:
        return None
    safe_name = folder_name.replace("'", "\\'")
    q = f"name = '{safe_name}' and mimeType='application/vnd.google-apps.folder' and '{parent_folder_id}' in parents and trashed=false"
    res = drive_service.files().list(q=q, fields="files(id, name)").execute()
    files = res.get("files", [])
    return files[0] if files else None


def create_child_folder(drive_service, parent_folder_id, folder_name):
    body = {"name": folder_name, "mimeType": "application/vnd.google-apps.folder"}
    if parent_folder_id:
        body["parents"] = [parent_folder_id]
    file = drive_service.files().create(body=body, fields="id, name").execute()
    return file


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


def create_spreadsheet(sheets_service, title, tabs=None, share_with_email=None, parent_folder_id=None):
    """Create spreadsheet, add to parent folder, optionally share with owner."""
    body = {"properties": {"title": title}}
    if tabs:
        body["sheets"] = [{"properties": {"title": t}} for t in tabs]
    created = sheets_service.spreadsheets().create(body=body, fields="spreadsheetId, properties/title").execute()
    spreadsheet_id = created["spreadsheetId"]

    if parent_folder_id:
        try:
            drive = get_drive_service()
            drive.files().update(fileId=spreadsheet_id, addParents=parent_folder_id, fields="id, parents").execute()
        except Exception as e:
            print("Warning adding spreadsheet to parent folder:", e)

    if share_with_email:
        try:
            drive = get_drive_service()
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
# API Endpoints
# --------------------------
@app.route("/api/upload_image", methods=["POST"])
def upload_image():
    if "image" not in request.files:
        return jsonify({"status": "error", "message": "No image uploaded"}), 400

    img = request.files["image"]
    folder_name = request.form.get("folder_name", DEFAULT_IMAGE_FOLDER)
    parent_folder_id = request.form.get("parent_folder_id")
    owner_email = request.form.get("owner_email")

    if not parent_folder_id:
        return jsonify({"status": "error", "message": "parent_folder_id required"}), 400

    filename = f"{datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{img.filename}"
    temp_path = os.path.join(UPLOAD_TEMP_FOLDER, filename)
    img.save(temp_path)

    drive = get_drive_service()

    # Find or create child folder under parent
    folder = find_child_folder_by_name(drive, parent_folder_id, folder_name)
    if not folder:
        folder = create_child_folder(drive, parent_folder_id, folder_name)

    with io.FileIO(temp_path, "rb") as fh:
        file_stream = io.BytesIO(fh.read())
    mimetype = img.mimetype or "application/octet-stream"

    # Upload to shared drive staging first
    staging_drive_id = "1GrUY5dTBtTAOzQqxQ_u_dvtQbX3Ug1or"  # fixed shared drive ID
    staging_folder = find_child_folder_by_name(drive, staging_drive_id, folder_name)
    if not staging_folder:
        staging_folder = create_child_folder(drive, staging_drive_id, folder_name)

    staging_file_meta = upload_file_to_drive(drive, file_stream, filename, mimetype, folder_id=staging_folder["id"], make_public=True)

    # Move file from staging to user parent folder
    drive.files().update(fileId=staging_file_meta["id"], addParents=folder["id"], removeParents=staging_folder["id"], fields="id, parents").execute()

    try:
        os.remove(temp_path)
    except Exception:
        pass

    return jsonify({"status": "success", "file": staging_file_meta})


@app.route("/api/record_attendance", methods=["POST"])
def record_attendance():
    """
    Expects JSON body:
    {
      "spreadsheet_title": optional, "spreadsheet_id": optional,
      "sheet_tab": optional (default "Attendance"),
      "id": required,
      "name": required,
      "date": required,
      "reason": optional,
      "image_url": optional,
      "owner_email": optional (email to share spreadsheet with)
      "start_col": optional (1-indexed) default 1,
      "parent_folder_id": optional (if provided, new spreadsheets will be placed inside this parent)
    }
    Behavior:
     - If spreadsheet_id provided, use it.
     - Else if spreadsheet_title provided, try to find it (optionally inside parent_folder_id), otherwise create it with default headers.
     - Append a row with format ["ID","Name","Date","Reason","Image URL"] to the specified sheet_tab (creating the sheet if needed).
    """
    data = request.get_json()
    required = ["id", "name", "date"]
    if not data or not all(k in data for k in required):
        return jsonify({"status": "error", "message": "Missing required fields (id,name,date)"}), 400

    drive = get_drive_service()
    sheets = get_sheets_service()

    spreadsheet_id = data.get("spreadsheet_id")
    spreadsheet_title = data.get("spreadsheet_title", f"{data.get('owner_email','user')}_Attendance")
    sheet_tab = data.get("sheet_tab", DEFAULT_SHEET_TAB)
    owner_email = data.get("owner_email")
    start_col = int(data.get("start_col", 1))
    parent_folder_id = data.get("parent_folder_id")  # optional

    # Locate or create spreadsheet
    if spreadsheet_id:
        # Optionally check existence
        try:
            _ = sheets.spreadsheets().get(spreadsheetId=spreadsheet_id, fields="spreadsheetId").execute()
        except Exception as e:
            return jsonify({"status": "error", "message": f"Spreadsheet not found: {e}"}), 400
    else:
        found = find_spreadsheet_by_title(drive, spreadsheet_title, parent_folder_id=parent_folder_id)
        if found:
            spreadsheet_id = found["id"]
        else:
            created = create_spreadsheet(sheets, spreadsheet_title, tabs=[sheet_tab], share_with_email=owner_email, parent_folder_id=parent_folder_id)
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
    """
    Query params: spreadsheet_id OR spreadsheet_title (optional parent_folder_id if searching by title)
    Returns list of sheet/tab names
    """
    spreadsheet_id = request.args.get("spreadsheet_id")
    spreadsheet_title = request.args.get("spreadsheet_title")
    parent_folder_id = request.args.get("parent_folder_id")  # optional
    drive = get_drive_service()
    sheets = get_sheets_service()

    if not spreadsheet_id:
        if not spreadsheet_title:
            return jsonify({"status": "error", "message": "spreadsheet_id or spreadsheet_title required"}), 400
        found = find_spreadsheet_by_title(drive, spreadsheet_title, parent_folder_id=parent_folder_id)
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
    """
    JSON: { "spreadsheet_id" or "spreadsheet_title", "subsheet_name": required, "owner_email": optional, "parent_folder_id": optional }
    If spreadsheet not found and spreadsheet_title provided and parent_folder_id optionally provided -> create spreadsheet under parent_folder_id
    """
    data = request.get_json()
    subsheet_name = data.get("subsheet_name")
    spreadsheet_id = data.get("spreadsheet_id")
    spreadsheet_title = data.get("spreadsheet_title")
    owner_email = data.get("owner_email")
    parent_folder_id = data.get("parent_folder_id")

    if not subsheet_name:
        return jsonify({"status": "error", "message": "subsheet_name required"}), 400

    drive = get_drive_service()
    sheets = get_sheets_service()

    if not spreadsheet_id:
        if not spreadsheet_title:
            return jsonify({"status": "error", "message": "spreadsheet_id or spreadsheet_title required"}), 400
        found = find_spreadsheet_by_title(drive, spreadsheet_title, parent_folder_id=parent_folder_id)
        if not found:
            # create spreadsheet with the requested subsheet as first tab
            created = create_spreadsheet(sheets, spreadsheet_title, tabs=[subsheet_name], share_with_email=owner_email, parent_folder_id=parent_folder_id)
            spreadsheet_id = created["spreadsheetId"]
            return jsonify({"status": "success", "spreadsheet_id": spreadsheet_id, "sheet": subsheet_name})
        spreadsheet_id = found["id"]

    # create subsheet if not exists
    create_subsheet_if_missing(sheets, spreadsheet_id, subsheet_name)
    return jsonify({"status": "success", "spreadsheet_id": spreadsheet_id, "sheet": subsheet_name})


@app.route("/api/delete_subsheet", methods=["POST"])
def delete_subsheet():
    """
    Delete a subsheet (tab) from a spreadsheet.
    JSON: { "spreadsheet_id" or "spreadsheet_title", "subsheet_name": required, "parent_folder_id": optional }
    """
    data = request.get_json()
    subsheet_name = data.get("subsheet_name")
    spreadsheet_id = data.get("spreadsheet_id")
    spreadsheet_title = data.get("spreadsheet_title")
    parent_folder_id = data.get("parent_folder_id")

    if not subsheet_name:
        return jsonify({"status": "error", "message": "subsheet_name required"}), 400

    drive = get_drive_service()
    sheets = get_sheets_service()

    if not spreadsheet_id:
        if not spreadsheet_title:
            return jsonify({"status": "error", "message": "spreadsheet_id or spreadsheet_title required"}), 400
        found = find_spreadsheet_by_title(drive, spreadsheet_title, parent_folder_id=parent_folder_id)
        if not found:
            return jsonify({"status": "error", "message": "Spreadsheet not found"}), 404
        spreadsheet_id = found["id"]

    success, err = delete_subsheet_if_exists(sheets, spreadsheet_id, subsheet_name)
    if not success:
        return jsonify({"status": "error", "message": err}), 400
    return jsonify({"status": "success", "spreadsheet_id": spreadsheet_id, "deleted": subsheet_name})


@app.route("/api/write_row", methods=["POST"])
def write_row():
    """
    Write an arbitrary row (array) starting at a specified column on a specified subsheet.
    JSON:
    {
      "spreadsheet_id" or "spreadsheet_title",
      "sheet_tab": required,
      "start_col": optional 1-indexed default 1,
      "row": ["ID","Name", ...],
      "owner_email": optional,
      "parent_folder_id": optional
    }
    """
    data = request.get_json()
    if not data:
        return jsonify({"status": "error", "message": "JSON body required"}), 400
    row_values = data.get("row")
    sheet_tab = data.get("sheet_tab")
    if not row_values or not sheet_tab:
        return jsonify({"status": "error", "message": "row and sheet_tab required"}), 400

    start_col = int(data.get("start_col", 1))
    spreadsheet_id = data.get("spreadsheet_id")
    spreadsheet_title = data.get("spreadsheet_title")
    owner_email = data.get("owner_email")
    parent_folder_id = data.get("parent_folder_id")

    drive = get_drive_service()
    sheets = get_sheets_service()

    if not spreadsheet_id:
        if not spreadsheet_title:
            return jsonify({"status": "error", "message": "spreadsheet_id or spreadsheet_title required"}), 400
        found = find_spreadsheet_by_title(drive, spreadsheet_title, parent_folder_id=parent_folder_id)
        if not found:
            created = create_spreadsheet(sheets, spreadsheet_title, tabs=[sheet_tab], share_with_email=owner_email, parent_folder_id=parent_folder_id)
            spreadsheet_id = created["spreadsheetId"]
        else:
            spreadsheet_id = found["id"]

    # ensure subsheet exists
    create_subsheet_if_missing(sheets, spreadsheet_id, sheet_tab)
    append_info = append_row_at_column(sheets, spreadsheet_id, sheet_tab, start_col, row_values)

    return jsonify({"status": "success", "append_info": append_info})


@app.route("/api/write_id_name", methods=["POST"])
def write_id_name():
    """
    Write only ID and Name to a specified subsheet (default subsheet name "Attendance Database")
    JSON:
    {
      "spreadsheet_id" or "spreadsheet_title",
      "sheet_tab": optional (default DEFAULT_DB_SHEET),
      "id": required,
      "name": required,
      "start_col": optional (1-indexed) default 1,
      "owner_email": optional,
      "parent_folder_id": optional
    }
    """
    data = request.get_json()
    if not data or "id" not in data or "name" not in data:
        return jsonify({"status": "error", "message": "id and name required"}), 400

    sheet_tab = data.get("sheet_tab", DEFAULT_DB_SHEET)
    start_col = int(data.get("start_col", 1))
    spreadsheet_id = data.get("spreadsheet_id")
    spreadsheet_title = data.get("spreadsheet_title", f"{data.get('owner_email','user')}_AttendanceDB")
    owner_email = data.get("owner_email")
    parent_folder_id = data.get("parent_folder_id")

    drive = get_drive_service()
    sheets = get_sheets_service()

    if not spreadsheet_id:
        found = find_spreadsheet_by_title(drive, spreadsheet_title, parent_folder_id=parent_folder_id)
        if not found:
            # create with the default DB sheet and place it under parent_folder_id if provided
            created = create_spreadsheet(sheets, spreadsheet_title, tabs=[sheet_tab], share_with_email=owner_email, parent_folder_id=parent_folder_id)
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
    """
    Find Name by ID in a specified subsheet.
    Query params:
      spreadsheet_id or spreadsheet_title
      sheet_tab (required)
      id (required)
      id_col_idx optional default 1
      name_col_idx optional default 2
      parent_folder_id optional (if searching by title)
    """
    spreadsheet_id = request.args.get("spreadsheet_id")
    spreadsheet_title = request.args.get("spreadsheet_title")
    sheet_tab = request.args.get("sheet_tab")
    target_id = request.args.get("id")
    id_col_idx = int(request.args.get("id_col_idx", 1))
    name_col_idx = int(request.args.get("name_col_idx", 2))
    parent_folder_id = request.args.get("parent_folder_id")

    if not sheet_tab or not target_id:
        return jsonify({"status": "error", "message": "sheet_tab and id required"}), 400

    drive = get_drive_service()
    sheets = get_sheets_service()

    if not spreadsheet_id:
        if not spreadsheet_title:
            return jsonify({"status": "error", "message": "spreadsheet_id or spreadsheet_title required"}), 400
        found = find_spreadsheet_by_title(drive, spreadsheet_title, parent_folder_id=parent_folder_id)
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
# Run
# --------------------------
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)), debug=True)