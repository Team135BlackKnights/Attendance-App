# Attendance Application
**A Tkinter application for easy attendance tracking.**

**Capabilities:**
- Check in and check out.
- Takes a picture at sign in to prevent fraud.
- Prompts for a reason if leaving early or signing in late.
- Exports results to a Google Sheet in the signed-in user's Google Drive.
- Any organization leader with a Google account can use this — just download, run, and sign in.

---

## Quick Start (for users)

1. Install dependencies (first time only):
   ```
   python dependencies.py
   ```
2. Run the app:
   ```
   python main.py
   ```
3. A browser tab will open — sign in with your Google account and approve the permissions.
4. That's it! A `token.json` file is saved locally so you only sign in once.

### Requirements
- Python 3.8+
- A Google Sheet named **Internship Attendance Sheet** (or whatever name is set in `driveUpload.py`) must exist in your Google Drive with at least a "Main Attendance" worksheet.
- The "Poppins" font should be installed, or the bundled font file should be present in `fonts/`.

### Signing Out / Switching Accounts
Delete `token.json` from the app folder. The next run will prompt a fresh Google sign-in.
