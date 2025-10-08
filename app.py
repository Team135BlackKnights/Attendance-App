from flask import Flask, request, jsonify
import os
import json
from datetime import datetime

app = Flask(__name__)

# Simple local "database" as JSON files
DB_FILE = "attendance_db.json"
SHEETS_FILE = "sheets_db.json"
UPLOAD_FOLDER = "uploaded_images"

os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize files if missing
for f, default in [(DB_FILE, []), (SHEETS_FILE, [])]:
    if not os.path.exists(f):
        with open(f, "w") as file:
            json.dump(default, file)

# --------------------------
# Helper functions
# --------------------------
def load_db(file):
    with open(file, "r") as f:
        return json.load(f)

def save_db(file, data):
    with open(file, "w") as f:
        json.dump(data, f, indent=2)

# --------------------------
# Endpoints
# --------------------------

@app.route("/api/upload_image", methods=["POST"])
def upload_image():
    if "image" not in request.files:
        return jsonify({"status": "error", "message": "No image uploaded"}), 400

    img = request.files["image"]
    filename = f"{datetime.now().strftime('%Y%m%d%H%M%S')}_{img.filename}"
    path = os.path.join(UPLOAD_FOLDER, filename)
    img.save(path)
    image_url = f"/images/{filename}"  # For local testing

    return jsonify({"status": "success", "image_url": image_url})


@app.route("/api/record_attendance", methods=["POST"])
def record_attendance():
    data = request.get_json()
    required_keys = ["id", "name", "date"]

    if not all(k in data for k in required_keys):
        return jsonify({"status": "error", "message": "Missing required fields"}), 400

    # Load sheets
    sheets = load_db(SHEETS_FILE)
    main_sheet = sheets[0] if sheets else None

    # If no sheet exists, create a default one
    if not main_sheet:
        main_sheet = {"id": 1, "name": "Attendance Sheet", "owner": data.get("owner_email", "default@example.com")}
        sheets.append(main_sheet)
        save_db(SHEETS_FILE, sheets)

    # Save record
    records = load_db(DB_FILE)
    record = {
        "main_sheet": main_sheet["name"],
        "sheet_tab": "Attendance",
        "id": data["id"],
        "name": data["name"],
        "date": data["date"],
        "reason": data.get("reason"),
        "image_url": data.get("image_url")
    }
    records.append(record)
    save_db(DB_FILE, records)

    return jsonify({"status": "success", **record})


@app.route("/api/list_sheets", methods=["GET"])
def list_sheets():
    sheets = load_db(SHEETS_FILE)
    sheet_names = [s["name"] for s in sheets]
    return jsonify({"status": "success", "sheets": sheet_names})


@app.route("/api/create_sheet", methods=["POST"])
def create_sheet():
    data = request.get_json()
    sheet_name = data.get("sheet_name")
    owner_email = data.get("owner_email", "default@example.com")

    if not sheet_name:
        return jsonify({"status": "error", "message": "sheet_name required"}), 400

    sheets = load_db(SHEETS_FILE)

    # Check if sheet exists
    existing = next((s for s in sheets if s["name"] == sheet_name), None)
    if existing:
        return jsonify({"status": "success", "sheet": existing})

    # Create new sheet
    new_sheet = {"id": len(sheets) + 1, "name": sheet_name, "owner": owner_email}
    sheets.append(new_sheet)
    save_db(SHEETS_FILE, sheets)
    return jsonify({"status": "success", "sheet": new_sheet})


if __name__ == "__main__":
    app.run(debug=True)
