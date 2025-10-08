import requests
import os

API_BASE_URL = "http://127.0.0.1:5000/api"

def push_attendance_to_api(record):
    # Upload image
    image_url = None
    if record.get("image_path") and os.path.exists(record["image_path"]):
        with open(record["image_path"], "rb") as img_file:
            files = {"image": img_file}
            try:
                resp = requests.post(f"{API_BASE_URL}/upload_image", files=files)
                resp.raise_for_status()
                res_json = resp.json()
                if res_json.get("status") == "success":
                    image_url = res_json.get("image_url")
                else:
                    return {"status": "error", "message": "Failed to upload image"}
            except Exception as e:
                return {"status": "error", "message": str(e)}

    payload = {
        "id": record["id"],
        "name": record["name"],
        "date": record["date"],
        "reason": record.get("reason"),
        "image_url": image_url
    }

    try:
        resp = requests.post(f"{API_BASE_URL}/record_attendance", json=payload)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}


def list_sheets():
    try:
        resp = requests.get(f"{API_BASE_URL}/list_sheets")
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") == "success":
            return data.get("sheets", [])
        else:
            return []
    except Exception:
        return []


def create_sheet_if_missing(sheet_name, owner_email=None):
    payload = {"sheet_name": sheet_name, "owner_email": owner_email}
    try:
        resp = requests.post(f"{API_BASE_URL}/create_sheet", json=payload)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        return {"status": "error", "message": str(e)}
