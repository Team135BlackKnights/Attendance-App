import requests
import os

API_BASE_URL = "http://127.0.0.1:8080/api"

# ===============================
# Upload image
# ===============================
def upload_image(image_path, parent_folder_id, folder_name="Attendance Images", owner_email=None):
    if not os.path.exists(image_path):
        return {"status": "error", "message": "Image file not found"}

    with open(image_path, "rb") as f:
        files = {"image": f}
        data = {"folder_name": folder_name, "parent_folder_id": parent_folder_id}
        if owner_email:
            data["owner_email"] = owner_email
        try:
            resp = requests.post(f"{API_BASE_URL}/upload_image", files=files, data=data)
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            return {"status": "error", "message": str(e)}


# ===============================
# Record attendance
# ===============================
def record_attendance(payload):
    """
    payload must include at least:
      id, name, date
    Optional: spreadsheet_id, spreadsheet_title, sheet_tab, reason, image_url, owner_email, start_col, parent_folder_id
    """
    try:
        resp = requests.post(f"{API_BASE_URL}/record_attendance", json=payload)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ===============================
# List subsheets (tabs)
# ===============================
def list_subsheets(spreadsheet_id=None, spreadsheet_title=None, parent_folder_id=None):
    params = {}
    if spreadsheet_id:
        params["spreadsheet_id"] = spreadsheet_id
    if spreadsheet_title:
        params["spreadsheet_title"] = spreadsheet_title
    if parent_folder_id:
        params["parent_folder_id"] = parent_folder_id

    try:
        resp = requests.get(f"{API_BASE_URL}/list_subsheets", params=params)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ===============================
# Create a subsheet/tab
# ===============================
def create_subsheet(subsheet_name, spreadsheet_id=None, spreadsheet_title=None, owner_email=None, parent_folder_id=None):
    data = {"subsheet_name": subsheet_name}
    if spreadsheet_id:
        data["spreadsheet_id"] = spreadsheet_id
    if spreadsheet_title:
        data["spreadsheet_title"] = spreadsheet_title
    if owner_email:
        data["owner_email"] = owner_email
    if parent_folder_id:
        data["parent_folder_id"] = parent_folder_id

    try:
        resp = requests.post(f"{API_BASE_URL}/create_subsheet", json=data)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ===============================
# Delete a subsheet/tab
# ===============================
def delete_subsheet(subsheet_name, spreadsheet_id=None, spreadsheet_title=None, parent_folder_id=None):
    data = {"subsheet_name": subsheet_name}
    if spreadsheet_id:
        data["spreadsheet_id"] = spreadsheet_id
    if spreadsheet_title:
        data["spreadsheet_title"] = spreadsheet_title
    if parent_folder_id:
        data["parent_folder_id"] = parent_folder_id

    try:
        resp = requests.post(f"{API_BASE_URL}/delete_subsheet", json=data)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ===============================
# Write an arbitrary row
# ===============================
def write_row(row, sheet_tab, spreadsheet_id=None, spreadsheet_title=None, start_col=1, owner_email=None, parent_folder_id=None):
    data = {
        "row": row,
        "sheet_tab": sheet_tab,
        "start_col": start_col
    }
    if spreadsheet_id:
        data["spreadsheet_id"] = spreadsheet_id
    if spreadsheet_title:
        data["spreadsheet_title"] = spreadsheet_title
    if owner_email:
        data["owner_email"] = owner_email
    if parent_folder_id:
        data["parent_folder_id"] = parent_folder_id

    try:
        resp = requests.post(f"{API_BASE_URL}/write_row", json=data)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ===============================
# Write ID and Name
# ===============================
def write_id_name(id_val, name_val, spreadsheet_id=None, spreadsheet_title=None, sheet_tab=None,
                  start_col=1, owner_email=None, parent_folder_id=None):
    data = {
        "id": id_val,
        "name": name_val,
        "start_col": start_col
    }
    if spreadsheet_id:
        data["spreadsheet_id"] = spreadsheet_id
    if spreadsheet_title:
        data["spreadsheet_title"] = spreadsheet_title
    if sheet_tab:
        data["sheet_tab"] = sheet_tab
    if owner_email:
        data["owner_email"] = owner_email
    if parent_folder_id:
        data["parent_folder_id"] = parent_folder_id

    try:
        resp = requests.post(f"{API_BASE_URL}/write_id_name", json=data)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ===============================
# Find name by ID
# ===============================
def find_id(sheet_tab, id_val, spreadsheet_id=None, spreadsheet_title=None,
            id_col_idx=1, name_col_idx=2, parent_folder_id=None):
    params = {
        "sheet_tab": sheet_tab,
        "id": id_val,
        "id_col_idx": id_col_idx,
        "name_col_idx": name_col_idx
    }
    if spreadsheet_id:
        params["spreadsheet_id"] = spreadsheet_id
    if spreadsheet_title:
        params["spreadsheet_title"] = spreadsheet_title
    if parent_folder_id:
        params["parent_folder_id"] = parent_folder_id

    try:
        resp = requests.get(f"{API_BASE_URL}/find_id", params=params)
        # 404 is handled separately
        if resp.status_code == 404:
            return {"status": "not_found", "id": id_val}
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}
