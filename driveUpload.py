from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from oauth2client.service_account import ServiceAccountCredentials
import gspread
import os


# API File Path, Change this depending on your API file.
APIPath = "C:/Users/aqazi075/Downloads/robotics-attendance-447321-989eafb69d96.json"


# Setup Google Sheets API
def setup_google_sheet(document = "Internship Attendance Sheet") :
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
