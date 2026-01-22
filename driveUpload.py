from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from oauth2client.service_account import ServiceAccountCredentials
import gspread
import os


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


def get_name_by_id(student_id, document=defaultDoc):
    """
    Look up a student's name by their ID in the IDs sheet.
    
    Args:
        student_id: The student's 6-digit ID (int or str)
        document: The Google Spreadsheet document name
    
    Returns:
        str: The student's name if found, None otherwise
    """
    try:
        ids_sheet = ensure_ids_sheet_exists(document)
        student_id_str = str(student_id)
        
        # Only fetch ID column (B) first to find matching row
        id_column = ids_sheet.col_values(2)  # Column B (IDs)
        
        # Search for matching ID (skip header at index 0)
        for row_idx, cell_id in enumerate(id_column[1:], start=2):  # start=2 because row 1 is header
            if cell_id == student_id_str:
                # Found match - fetch only the name from column A for this row
                name = ids_sheet.cell(row_idx, 1).value  # Column A
                return name
        
        return None
    except Exception as e:
        print(f"Error looking up ID {student_id}: {e}")
        return None


def get_id_by_name(name, document=defaultDoc):
    """
    Look up a student's ID by their name in the IDs sheet.
    
    Args:
        name: The student's name
        document: The Google Spreadsheet document name
    
    Returns:
        str: The student's ID if found, None otherwise
    """
    try:
        ids_sheet = ensure_ids_sheet_exists(document)
        
        # Only fetch name column (A) first to find matching row
        name_column = ids_sheet.col_values(1)  # Column A (Names)
        
        # Search for matching name (skip header at index 0)
        for row_idx, cell_name in enumerate(name_column[1:], start=2):  # start=2 because row 1 is header
            if cell_name == name:
                # Found match - fetch only the ID from column B for this row
                student_id = ids_sheet.cell(row_idx, 2).value  # Column B
                return student_id
        
        return None
    except Exception as e:
        print(f"Error looking up name {name}: {e}")
        return None


def save_id_name_pair(student_id, name, document=defaultDoc):
    """
    Save a student ID and name pair to the IDs sheet.
    Only adds new entries - does NOT update existing names.
    
    Args:
        student_id: The student's 6-digit ID (int or str)
        name: The student's name
        document: The Google Spreadsheet document name
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        ids_sheet = ensure_ids_sheet_exists(document)
        student_id_str = str(student_id)
        
        # Only fetch ID column (B) to check for duplicates
        id_column = ids_sheet.col_values(2)  # Column B (IDs)
        
        # Check if ID already exists - if so, do nothing (name is permanent)
        if student_id_str in id_column[1:]:  # Skip header
            # Find the row to get the existing name for logging
            for row_idx, cell_id in enumerate(id_column[1:], start=2):
                if cell_id == student_id_str:
                    existing_name = ids_sheet.cell(row_idx, 1).value
                    print(f"ID {student_id} already exists with name '{existing_name}' - not updating")
                    break
            return True
        
        # ID doesn't exist, add new row with both name and ID
        next_row = len(id_column) + 1
        ids_sheet.update_acell(f'A{next_row}', name)
        ids_sheet.update_acell(f'B{next_row}', student_id_str)
        print(f"Added new entry: '{name}' with ID {student_id}")
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
