# Attendance App
**A Tkinter application for easy attendance tracking with Google Sheets integration.**

**Capabilities:**
- Sign in and sign out with a 6-digit ID.
- Optionally takes a webcam photo at each sign-in or sign-out to deter fraud.
- Prompts for a reason when signing out early or signing in late (configurable cutoff times).
- Exports records to a Google Sheet in the signed-in user's Google Drive, non-blocking.
- ID-to-name lookup uses an in-memory cache loaded from the "IDs" worksheet — no API call per scan.
- Supports Light, Dark, and Black & Gold themes with scalable fonts.
- Keyboardless mode for barcode-scanner stations.
- Easy Sign In mode auto-detects sign-in vs. sign-out from local state.
- Packagable as a single executable with PyInstaller.

- Privacy policy at [this link](https://team135blackknights.github.io/Attendance-App/privacy-policy.html)

---

## Quick Start

1. Install dependencies (first time only):
   ```
   python dependencies.py
   ```
2. Run the app:
   ```
   python main.py
   ```
3. The app opens in full-screen. The main form is greyed out and a **yellow banner** is shown until you sign in.
4. Open **Options → Google Settings** and click **"Sign In with Google"**. Your browser will open for OAuth consent. Complete the sign-in there.
5. The banner disappears, the form becomes active, and the dropdown populates with your spreadsheet's worksheet names.

---

## First-Time Setup

### Sign In with Google
- Open **Options → Google Settings**.
- Click **"Sign In with Google"** — your browser opens for a one-time consent flow.
- The token is saved to `token.json` in the app folder. Subsequent launches load it automatically; a browser is only opened again if the token expires or is revoked.

### Connect a Google Sheet
The app must know which spreadsheet to write to. In **Options → Google Settings → Sheets Config**:

- **Create a new sheet** — enter a name and click **Create**. The app creates a spreadsheet in your Drive with the standard tab layout (Main Attendance, Build Season, IDs).
- **Use an existing sheet** — enter the exact spreadsheet title and click **Connect**. The sheet must already exist in your signed-in account's Drive.

The selected sheet name is saved to `settings.json` and reused on subsequent launches.

---

## Signing In / Out of Google

| Action | How |
|---|---|
| Sign in | Options → Google Settings → "Sign In with Google" |
| Sign out | Options → Google Settings → "Sign Out" |

Signing out deletes `token.json`. The yellow banner reappears and the form is greyed out until you sign in again.

---

## Daily Use

1. Launch the app. If previously signed in, the form activates automatically after sheets load (the dropdown briefly shows "Loading sheets…").
2. Select the **worksheet** from the "Why are you here" dropdown (e.g. "Main Attendance", "Build Season").
3. Select **Sign In** or **Sign Out** (hidden in Easy Sign In mode — direction is auto-detected).
4. Type or scan a **6-digit ID** into the entry field and press **Enter** (or click **Enter**).
5. If the ID is new, the app prompts for a first and last name.
6. A "Smile!" popup appears while the webcam captures a photo (if the camera is enabled).
7. A confirmation dialog appears immediately — no waiting for Google.

Records are queued and pushed to Google Sheets/Drive in the background. The app remains fully usable while the push is in progress.

---

## Features

### Easy Sign In Mode
When enabled (Options → App Behavior), the Sign In / Sign Out radio buttons are hidden. The app automatically determines direction from its local state: if the person is currently listed as signed in, the next scan signs them out, and vice versa.

### Keyboardless Mode
Designed for barcode-scanner stations where no keyboard is attached. Configure 16-character scanner barcodes for each action (sign in, sign out, select worksheet, close popup). Enable via Options → Keyboardless Mode or activate directly after configuring bindings. Press **Ctrl+E** to exit keyboardless mode.

### Who's Here
Click **"Who's here?"** in the header to open a scrollable, resizable list of everyone currently signed in, with their sign-in time. Sortable by name or time. Refreshes every 60 seconds; the **Refresh** button re-scans Google Sheets live.

People signed in for more than 12 hours are automatically signed out (recorded as "Didn't sign out") and removed from the list.

### Camera Settings (Options → App Behavior)
| Setting | Effect |
|---|---|
| Camera Frequency | Probability a photo is taken per event (0.05 = 1-in-20, 1.0 = always) |
| Camera Trigger | Fire on Sign In, Sign Out, Both, or Never |

Setting the trigger to **Never** automatically disables the Image Link and Image Path logging fields.

### Late Sign-In / Early Sign-Out Prompts
If cutoff times are configured (Options → Data Logging) and enabled for a worksheet, the app prompts for a reason when:
- A **sign-in** occurs after the late sign-in cutoff time (24h HH:MM).
- A **sign-out** occurs before the early sign-out cutoff time (24h HH:MM).

The reason is stored in the Reason column of the attendance sheet.

---

## Sheet Structure

Every attendance spreadsheet created by the app has this layout:

### Attendance worksheets (e.g. "Main Attendance", "Build Season")
| Columns A–F | — | Columns H–M |
|---|---|---|
| Sign-in block | *(gap)* | Sign-out block |
| ID, Name, Timestamp, Image Path, Image Link, Reason | | ID, Name, Timestamp, Image Path, Image Link, Reason |

Headers are written dynamically based on which fields are enabled in Data Logging settings.

### IDs worksheet
| Column A | Column B |
|---|---|
| Name | ID |

The "IDs" tab is reserved and cannot be used as an attendance target. It is populated automatically as new users register.

---

## Settings Reference

Settings are stored in `settings.json` next to the executable (or script). All settings are editable via **Options**.

| Key | Description | Default |
|---|---|---|
| `ui_theme` | Color theme: `"Light"`, `"Dark"`, `"Black & Gold"` | `"Light"` |
| `main_ui_scale` | Font scale for the main window (0.5–2.0) | `1.0` |
| `whos_here_scale` | Font scale for the Who's Here window (0.5–2.0) | `1.0` |
| `camera_frequency` | Probability a photo is taken (0.05–1.0) | `1.0` |
| `camera_trigger` | When camera fires: `"in"`, `"out"`, `"both"`, `"never"` | `"both"` |
| `easy_signin_mode` | Auto-detect sign-in vs. sign-out from local state | `false` |
| `keyboardless_mode` | Enable barcode-scanner input mode | `false` |
| `keyboardless_bindings` | 16-char scanner strings for each action | `{}` |
| `sheet_name` | Google Spreadsheet title to write attendance to | `""` |
| `data_logging.fields` | Toggle each column: name, timestamp, image_link, image_path, reason | all `true` |
| `data_logging.worksheet_targets` | Ordered list of attendance worksheet names for the dropdown | `[]` |
| `data_logging.time_cutoffs.late_signin` | HH:MM after which sign-in is considered late | `"15:45"` |
| `data_logging.time_cutoffs.early_signout` | HH:MM before which sign-out is considered early | `"18:45"` |
| `data_logging.cutoff_enabled_by_worksheet` | Per-worksheet enable flag for cutoff prompts | `{}` |

To reset all settings to defaults, open **Options → Reset Defaults**.

---

## For Developers

### Project structure
```
main.py          — Tkinter UI, attendance flow, settings, all top-level logic
driveUpload.py   — Google Sheets/Drive helpers, ID cache, background sync worker
google_auth.py   — OAuth 2.0 sign-in/out, credential storage
camera.py        — Webcam capture and gamma correction
dependencies.py  — pip install helper
fonts/           — Bundled Poppins font files
images/          — Written at runtime; one folder per student (ID-Name/)
settings.json    — Persisted user settings (written at runtime)
token.json       — Persisted OAuth token (written after first sign-in)
```

### Requirements
- Python 3.8+
- Dependencies: `google-api-python-client`, `google-auth-oauthlib`, `gspread`, `opencv-python`, `Pillow`

### Background sync
Attendance records and new ID/name pairs are never written to Google synchronously. They are placed on `attendance_queue` and `new_id_queue` respectively. `background_sync_worker` (a daemon thread) drains both queues, retrying failed items after a 5-second back-off.

A periodic callback (`register_api_refresh_callback`) triggers a local refresh of the ID cache and Who's Here state every 8–16 Google API calls.

### PyInstaller packaging
The app supports `--onefile` packaging. `_get_base_path()` resolves `sys._MEIPASS` when frozen so bundled resources (fonts) are found correctly. `token.json` and `settings.json` are written next to the `.exe` (via `_get_persistent_path()`) so they survive re-extraction on each launch.

### OAuth credentials
The embedded OAuth client credentials (`_B64_CLIENT_ID`, `_B64_CLIENT_SECRET` in `google_auth.py`) are base64-encoded to avoid secret-scanning false positives. For desktop/installed apps Google explicitly documents that the client secret is not truly secret. Actual security comes from the user consenting in their browser.

To use your own Google Cloud project, replace the `_B64_*` values with your own base64-encoded client ID and secret from the Google Cloud Console (OAuth 2.0 → Desktop application type).
