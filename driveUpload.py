from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from oauth2client.service_account import ServiceAccountCredentials
import gspread
import os
import threading
import queue
import time


# API File Path, Change this depending on your API file.
APIPath = "C:/Users/aqazi075/Downloads/robotics-attendance-447321-ca10f1c31867.json"
defaultDoc = "Internship Attendance Sheet"


# Setup Google Sheets API
def setup_google_sheet(document = defaultDoc) :
    # Change this to your sheet's name ^
    scope = ['https://spreadsheets.google.com/feeds', 'https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(APIPath, scope)
    client = gspread.authorize(creds)
    sheet = client.open(document)
    return sheet

# Authenticate Google Drive API
def setup_google_drive():
    scope = ['https://www.googleapis.com/auth/drive']
    creds = ServiceAccountCredentials.from_json_keyfile_name(APIPath, scope)
    drive_service = build('drive', 'v3', credentials=creds)
    return drive_service

def list_sheets(document = defaultDoc):
    spreadsheet = setup_google_sheet(document)
    worksheets = spreadsheet.worksheets()   # list of Worksheet objects
    sheet_names = [ws.title for ws in worksheets]
    return sheet_names


# Set file permissions to make it publicly accessible
def make_file_public(drive_service, file_id):
    permission = {
        'role': 'reader',
        'type': 'anyone'
    }
    drive_service.permissions().create(
        fileId=file_id,
        body=permission
    ).execute()

# Upload an image and return its view link
def upload_image_to_drive(drive_service, file_path):
    file_name = os.path.basename(file_path)
    file_metadata = {
        'name': file_name,
    }
    media = MediaFileUpload(file_path, mimetype='image/jpeg')  # Adjust mimetype if needed

    # Upload file
    file = drive_service.files().create(
        body=file_metadata,
        media_body=media,
        fields='id, webViewLink, webContentLink'
    ).execute()

    # Make the file public
    make_file_public(drive_service, file.get('id'))

    # Get the file's webViewLink to share
    file_url = file.get('webViewLink')
    print(f"File uploaded successfully. File URL: {file_url}")
    return file_url


# --------------------------
# IDs Sheet Functions
# --------------------------
IDS_SHEET_NAME = "IDs"

# --------------------------
# Local ID Cache
# --------------------------
# Local dictionary cache: ID (str) -> Name (str)
id_to_name_cache = {}
# Reverse lookup cache: Name (str) -> ID (str)
name_to_id_cache = {}

# Queue for new IDs that need to be uploaded to the sheet in the background
new_id_queue = queue.Queue()

# Queue for attendance records that need to be pushed to Google in the background
# Items are tuples: (current_id, name, attendance_record, event, reason, action, hasPic, folder, picName)
attendance_queue = queue.Queue()

# Background thread for syncing new IDs
background_sync_thread = None
background_sync_running = False

def ensure_ids_sheet_exists(document=defaultDoc):
    """
    Ensure the 'IDs' subsheet exists in the spreadsheet.
    Creates it if it doesn't exist with headers 'Name' and 'ID'.
    Returns the worksheet object.
    """
    spreadsheet = setup_google_sheet(document)
    worksheets = spreadsheet.worksheets()
    sheet_names = [ws.title for ws in worksheets]
    
    if IDS_SHEET_NAME in sheet_names:
        return spreadsheet.worksheet(IDS_SHEET_NAME)
    else:
        # Create the IDs sheet
        ids_sheet = spreadsheet.add_worksheet(title=IDS_SHEET_NAME, rows=1000, cols=2)
        # Add headers
        ids_sheet.update_acell('A1', 'Name')
        ids_sheet.update_acell('B1', 'ID')
        print(f"Created '{IDS_SHEET_NAME}' sheet with headers.")
        return ids_sheet


def load_ids_cache(document=defaultDoc):
    """
    Load all IDs and names from the Google Sheet into the local cache.
    This should be called once on startup.
    
    Args:
        document: The Google Spreadsheet document name
    
    Returns:
        bool: True if successful, False otherwise
    """
    global id_to_name_cache, name_to_id_cache
    try:
        ids_sheet = ensure_ids_sheet_exists(document)
        
        # Fetch all data at once (more efficient than multiple cell lookups)
        all_values = ids_sheet.get_all_values()
        
        # Clear existing caches
        id_to_name_cache.clear()
        name_to_id_cache.clear()
        
        # Skip header row (index 0) and populate both caches
        for row in all_values[1:]:
            if len(row) >= 2 and row[0] and row[1]:  # Both name and ID must exist
                name = row[0]
                student_id = str(row[1])
                id_to_name_cache[student_id] = name
                name_to_id_cache[name] = student_id
        
        print(f"Loaded {len(id_to_name_cache)} IDs into local cache")
        return True
        
    except Exception as e:
        print(f"Error loading IDs cache: {e}")
        return False


def _process_id_item(item, document):
    """
    Process a single new-ID item from the queue.
    Checks if it exists in the sheet and uploads if not.
    Returns True on success, False to retry.
    """
    student_id, name = item
    student_id_str = str(student_id)
    print(f"Background sync: Processing ID {student_id_str} with name '{name}'")
    try:
        ids_sheet = ensure_ids_sheet_exists(document)
        id_column = ids_sheet.col_values(2)  # Column B (IDs)
        if student_id_str in id_column[1:]:
            print(f"Background sync: ID {student_id_str} already exists in sheet, skipping")
        else:
            next_row = len(id_column) + 1
            ids_sheet.update_acell(f'A{next_row}', name)
            ids_sheet.update_acell(f'B{next_row}', student_id_str)
            print(f"Background sync: Added new entry: '{name}' with ID {student_id_str}")
        return True
    except Exception as e:
        print(f"Background sync: Error processing ID {student_id_str}: {e}")
        return False


def _process_attendance_item(item, document):
    """
    Process a single attendance item from the queue.
    Pushes the attendance record (and optional image) to Google.
    Returns True on success, False to retry.
    """
    current_id, name, attendance_record, event, reason, action, hasPic, img_folder, img_picName, volunteering_list = item
    print(f"Background sync: Pushing attendance for '{name}' ({action})")
    try:
        spreadsheet = setup_google_sheet(document)
        drive = setup_google_drive()

        if hasPic and img_folder and img_picName:
            file_path = f"{img_folder}/{img_picName}"
            print(f"Background sync: Uploading image {file_path}")
            file_url = upload_image_to_drive(drive, file_path)
        else:
            file_path = "No Image"
            file_url = "No Image"

        # Determine target sheet
        if (reason not in volunteering_list) and reason != "Build Season":
            sheet = spreadsheet.worksheet("Main Attendance")
        elif reason == "Build Season":
            sheet = spreadsheet.worksheet("Build Season")
        else:
            sheet = spreadsheet.worksheet(reason)

        # Insert data into the correct columns
        data = [current_id, name, attendance_record, file_path, file_url, reason]
        if action == "in":
            values = sheet.get("A:A")
            row = len(values) + 1
            sheet.update(f"A{row}:F{row}", [data])
        else:
            values = sheet.get("H:H")
            row = len(values) + 1
            sheet.update(f"H{row}:M{row}", [data])

        print(f"Background sync: Attendance pushed for '{name}'")
        return True
    except Exception as e:
        print(f"Background sync: Error pushing attendance for '{name}': {e}")
        return False


def background_sync_worker(document=defaultDoc):
    """
    Background worker that continuously processes both the new_id_queue
    and the attendance_queue.  Runs in a separate daemon thread so it
    never blocks the main UI / attendance flow.
    """
    global background_sync_running
    print("Background sync worker started")

    while background_sync_running:
        processed_something = False

        # --- Process one ID item if available ---
        try:
            item = new_id_queue.get_nowait()
            if not _process_id_item(item, document):
                new_id_queue.put(item)  # retry later
                time.sleep(5)
            else:
                new_id_queue.task_done()
            processed_something = True
        except queue.Empty:
            pass

        # --- Process one attendance item if available ---
        try:
            item = attendance_queue.get_nowait()
            if not _process_attendance_item(item, document):
                attendance_queue.put(item)  # retry later
                time.sleep(5)
            else:
                attendance_queue.task_done()
            processed_something = True
        except queue.Empty:
            pass

        # If neither queue had work, sleep briefly before rechecking
        if not processed_something:
            time.sleep(0.5)

    print("Background sync worker stopped")


def start_background_sync(document=defaultDoc):
    """
    Start the background sync thread if it's not already running.
    
    Args:
        document: The Google Spreadsheet document name
    """
    global background_sync_thread, background_sync_running
    
    if background_sync_running:
        print("Background sync already running")
        return
    
    background_sync_running = True
    background_sync_thread = threading.Thread(
        target=background_sync_worker,
        args=(document,),
        daemon=True,
        name="IDBackgroundSync"
    )
    background_sync_thread.start()
    print("Background sync thread started")


def stop_background_sync():
    """
    Stop the background sync thread gracefully.
    """
    global background_sync_running
    background_sync_running = False
    print("Background sync thread stopping...")


def get_name_by_id(student_id, document=defaultDoc):
    """
    Look up a student's name by their ID using the local cache.
    No Google API calls are made.
    
    Args:
        student_id: The student's 6-digit ID (int or str)
        document: The Google Spreadsheet document name (unused, kept for compatibility)
    
    Returns:
        str: The student's name if found, None otherwise
    """
    try:
        student_id_str = str(student_id)
        return id_to_name_cache.get(student_id_str, None)
    except Exception as e:
        print(f"Error looking up ID {student_id} in cache: {e}")
        return None


def get_id_by_name(name, document=defaultDoc):
    """
    Look up a student's ID by their name using the local cache.
    No Google API calls are made.
    
    Args:
        name: The student's name
        document: The Google Spreadsheet document name (unused, kept for compatibility)
    
    Returns:
        str: The student's ID if found, None otherwise
    """
    try:
        return name_to_id_cache.get(name, None)
    except Exception as e:
        print(f"Error looking up name {name} in cache: {e}")
        return None


def save_id_name_pair(student_id, name, document=defaultDoc):
    """
    Save a student ID and name pair to the local cache and queue for background sync.
    This immediately updates the local cache and returns, while the background thread
    handles uploading to the Google Sheet asynchronously.
    
    Args:
        student_id: The student's 6-digit ID (int or str)
        name: The student's name
        document: The Google Spreadsheet document name
    
    Returns:
        bool: True if successfully added to cache and queued, False otherwise
    """
    global id_to_name_cache, name_to_id_cache
    try:
        student_id_str = str(student_id)
        
        # Check if ID already exists in local cache
        if student_id_str in id_to_name_cache:
            existing_name = id_to_name_cache[student_id_str]
            print(f"ID {student_id} already exists in cache with name '{existing_name}' - not updating")
            return True
        
        # Add to local cache immediately
        id_to_name_cache[student_id_str] = name
        name_to_id_cache[name] = student_id_str
        print(f"Added to local cache: '{name}' with ID {student_id}")
        
        # Queue for background upload to sheet
        new_id_queue.put((student_id, name))
        print(f"Queued for background sync: '{name}' with ID {student_id}")
        
        return True
        
    except Exception as e:
        print(f"Error saving ID-name pair: {e}")
        return False


def parse_timestamp(timestamp_str):
    """
    Parse a timestamp string into a datetime object.
    
    Supports formats:
    - "Signed in at: HH:MM AM/PM, Date: YYYY-MM-DD"
    - "Signed out at: HH:MM AM/PM, Date: YYYY-MM-DD"
    - "HH:MM AM/PM, YYYY-MM-DD"
    
    Args:
        timestamp_str: The timestamp string to parse
    
    Returns:
        datetime object if successful, None otherwise
    """
    from datetime import datetime
    try:
        if not timestamp_str:
            return None
            
        # Handle format: "Signed in/out at: HH:MM AM/PM, Date: YYYY-MM-DD"
        if "at:" in timestamp_str and "Date:" in timestamp_str:
            parts = timestamp_str.split(", Date: ")
            if len(parts) == 2:
                time_part = parts[0].split("at: ")[-1].strip()  # "HH:MM AM/PM"
                date_part = parts[1].strip()  # "YYYY-MM-DD"
                datetime_str = f"{date_part} {time_part}"
                return datetime.strptime(datetime_str, "%Y-%m-%d %I:%M %p")
        
        # Handle format: "HH:MM AM/PM, YYYY-MM-DD"
        elif ", " in timestamp_str:
            parts = timestamp_str.split(", ")
            if len(parts) == 2:
                time_part = parts[0].strip()
                date_part = parts[1].strip()
                datetime_str = f"{date_part} {time_part}"
                return datetime.strptime(datetime_str, "%Y-%m-%d %I:%M %p")
        
        return None
    except Exception as e:
        print(f"Error parsing timestamp '{timestamp_str}': {e}")
        return None


def fetch_whos_here_from_sheets(sheet_names, document=defaultDoc):
    """
    Scan one or more attendance sub-sheets and return a dict of people
    who are currently signed in (i.e. their most recent sign-in has no
    matching sign-out afterwards).

    The sheet structure is:
      Sign-ins:  A=ID, B=Name, C=Timestamp
      Sign-outs: H=ID, I=Name, J=Timestamp

    Returns:
        dict: name (str) -> sign-in timestamp string  "HH:MM AM/PM, YYYY-MM-DD"
    """
    from datetime import datetime as _dt

    currently_here = {}  # name -> friendly timestamp string

    try:
        spreadsheet = setup_google_sheet(document)
    except Exception as e:
        print(f"fetch_whos_here_from_sheets: Cannot open spreadsheet: {e}")
        return currently_here

    for sheet_name in sheet_names:
        try:
            sheet = spreadsheet.worksheet(sheet_name)

            # Pull all data at once to minimise API calls
            all_values = sheet.get_all_values()
            if len(all_values) <= 1:
                continue  # only header row

            rows = all_values[1:]  # skip header

            # Build per-person latest sign-in and sign-out datetimes
            # sign_in:  col A(0)=ID, B(1)=Name, C(2)=Timestamp
            # sign_out: col H(7)=ID, I(8)=Name, J(9)=Timestamp
            person_last_in = {}   # name -> (datetime, friendly_ts)
            person_last_out = {}  # name -> datetime

            for row in rows:
                # --- sign-in side ---
                if len(row) >= 3 and row[1] and row[2]:
                    name_in = row[1]
                    ts_in = parse_timestamp(row[2])
                    if ts_in:
                        if name_in not in person_last_in or ts_in > person_last_in[name_in][0]:
                            # Build a friendly timestamp string "HH:MM AM/PM, YYYY-MM-DD"
                            friendly = ts_in.strftime("%I:%M %p") + ", " + ts_in.strftime("%Y-%m-%d")
                            person_last_in[name_in] = (ts_in, friendly)

                # --- sign-out side ---
                if len(row) >= 10 and row[8] and row[9]:
                    name_out = row[8]
                    ts_out = parse_timestamp(row[9])
                    if ts_out:
                        if name_out not in person_last_out or ts_out > person_last_out[name_out]:
                            person_last_out[name_out] = ts_out

            # A person is "here" if their latest sign-in is MORE RECENT than
            # their latest sign-out (or they have no sign-out at all).
            for name, (last_in_dt, friendly_ts) in person_last_in.items():
                last_out_dt = person_last_out.get(name)
                if last_out_dt is None or last_in_dt > last_out_dt:
                    # Also skip anyone signed in > 12 hours ago
                    if (_dt.now() - last_in_dt).total_seconds() < 12 * 3600:
                        currently_here[name] = friendly_ts

        except Exception as e:
            print(f"fetch_whos_here_from_sheets: Error scanning '{sheet_name}': {e}")

    return currently_here


def get_last_action_from_sheet(student_id, sheet_name, document=defaultDoc):
    """
    Get the last action (in or out) for a given student ID by scanning the specified subsheet.
    Uses timestamps to determine which action happened most recently.
    
    The sheet structure is:
    - Sign-ins are in columns A-F (ID in A, Name in B, Timestamp in C)
    - Sign-outs are in columns H-M (ID in H, Name in I, Timestamp in J)
    
    Args:
        student_id: The student's 6-digit ID (int or str)
        sheet_name: The name of the subsheet to scan (e.g., "Main Attendance", "Build Season", etc.)
        document: The Google Spreadsheet document name
    
    Returns:
        str: "in" if last action was sign in, "out" if last action was sign out,
             or "out" as default if no records found
    """
    try:
        spreadsheet = setup_google_sheet(document)
        sheet = spreadsheet.worksheet(sheet_name)
        
        student_id_str = str(student_id)
        
        last_sign_in_time = None
        last_sign_out_time = None
        
        # Step 1: Fetch only the sign-in ID column (A) to find matching rows
        sign_in_ids = sheet.col_values(1)  # Column A (sign-in IDs)
        sign_in_matching_rows = []
        for row_idx, cell_id in enumerate(sign_in_ids[1:], start=2):  # Skip header
            if str(cell_id) == student_id_str:
                sign_in_matching_rows.append(row_idx)
        
        # Step 2: Fetch only the sign-out ID column (H) to find matching rows
        sign_out_ids = sheet.col_values(8)  # Column H (sign-out IDs)
        sign_out_matching_rows = []
        for row_idx, cell_id in enumerate(sign_out_ids[1:], start=2):  # Skip header
            if str(cell_id) == student_id_str:
                sign_out_matching_rows.append(row_idx)
        
        # Step 3: Fetch timestamps only for matching sign-in rows (column C)
        for row_idx in sign_in_matching_rows:
            timestamp_str = sheet.cell(row_idx, 3).value  # Column C (timestamp)
            timestamp = parse_timestamp(timestamp_str)
            if timestamp:
                if last_sign_in_time is None or timestamp > last_sign_in_time:
                    last_sign_in_time = timestamp
        
        # Step 4: Fetch timestamps only for matching sign-out rows (column J)
        for row_idx in sign_out_matching_rows:
            timestamp_str = sheet.cell(row_idx, 10).value  # Column J (timestamp)
            timestamp = parse_timestamp(timestamp_str)
            if timestamp:
                if last_sign_out_time is None or timestamp > last_sign_out_time:
                    last_sign_out_time = timestamp
        
        # Determine which action was most recent based on timestamps
        if last_sign_in_time is None and last_sign_out_time is None:
            # No records found, default to "out" so next action is sign in
            return "out"
        elif last_sign_in_time is None:
            # Only sign-outs found
            return "out"
        elif last_sign_out_time is None:
            # Only sign-ins found
            return "in"
        elif last_sign_in_time > last_sign_out_time:
            # Last action was sign in
            return "in"
        else:
            # Last action was sign out
            return "out"
            
    except Exception as e:
        print(f"Error getting last action from sheet: {e}")
        return "out"  # Default to "out" on error
