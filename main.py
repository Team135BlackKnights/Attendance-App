"""
Main entry point and UI for the Attendance App.

This module builds the Tkinter root window, handles the entire attendance
flow, and wires together the Google Sheets/Drive back-end (driveUpload),
camera capture (camera), and OAuth authentication (google_auth).

Startup sequence:
  1. Settings loaded from settings.json (load_settings).
  2. Poppins font registered with the OS (load_private_font).
  3. Root window and all main widgets created.
  4. apply_ui_settings() applies the saved theme and font sizes.
  5. root.after(200, _deferred_startup) fires once the event loop is running:
       - If no sheet is configured, the sheet-setup dialog is shown.
       - If not signed in, the yellow banner is displayed and the form is greyed out.
       - Otherwise the sheet is verified in a background thread, then
         initialize_google_connection() populates the ID cache, Who's Here
         state, and starts background_sync_worker.

Function groups
---------------
Font / theme helpers:
    create_fonts            -- Create scaled Poppins font objects.
    apply_ui_settings       -- Apply the active theme to all existing widgets.
    style_entry             -- Apply consistent styling to an Entry widget.
    style_optionmenu        -- Apply consistent styling to an OptionMenu widget.
    center_window           -- Center a window on screen at a fixed size.
    center_and_fit          -- Resize and center a window to fit its content.
    adjust_all_toplevels_to_scale -- Resize all open Toplevel windows after a scale change.

Settings:
    save_settings           -- Persist all settings globals to settings.json.
    load_settings           -- Load settings from settings.json into globals.

Attendance flow:
    scan_id                 -- Validate the ID entry and dispatch to name-lookup or smile window.
    ask_name_window         -- Prompt a first-time user to enter their name.
    open_smile_window       -- Show the "Smile!" popup and trigger camera capture.
    display_smile_message   -- Render the smile prompt into a container widget.
    take_picture_and_record -- Capture a photo then call process_attendance.
    open_fail_window        -- Show the camera-failure dialog.
    display_fail_message    -- Render the failure message into a container widget.
    process_attendance      -- Record attendance locally and queue the Google push.
    push_to_google          -- (Legacy) Directly push one record to Google Sheets/Drive.
    next_available_row      -- Return the next empty row index in a sheet column range.
    insert_data             -- Write sign-in or sign-out data into the appropriate columns.
    early_sign_out          -- Prompt for and return an early sign-out reason string.
    late_sign_in            -- Prompt for and return a late sign-in reason string.

Sign-in tracking:
    add_sign_in             -- Add or update a person in the local sign-ins dict.
    remove_sign_in          -- Remove a person from the local sign-ins dict.
    get_current_signins     -- Return a snapshot copy of the current sign-ins dict.

Loading windows:
    open_id_lookup_loading_window    -- Show a "looking up ID" progress dialog.
    open_name_submit_loading_window  -- Show a "saving name" progress dialog.
    open_loading_window              -- Show a generic "saving attendance" progress dialog.
    display_loading_message          -- Render the loading text into a container widget.

Who's Here window:
    open_whos_here_window   -- Open (or lift) the scrollable Who's Here dialog.
    refresh_whos_here_window -- Repopulate the Who's Here window if it is open.

Options / Settings dialog:
    open_options_window     -- Open the multi-section Options/Settings dialog.

Keyboardless mode:
    enter_keyboardless_mode -- Activate barcode-scanner input mode.
    exit_keyboardless_mode  -- Deactivate barcode-scanner input mode.

UI state management:
    set_ui_auth_state       -- Show/hide the sign-in banner; enable/disable form.
    set_ui_sheets_state     -- Enable/disable form based on whether sheets are loaded.
    _set_dropdown_loading   -- Put the event dropdown into "Loading sheets…" state.
    _apply_form_state       -- Apply the combined auth+sheets enabled state to all inputs.

Google initialisation:
    initialize_google_connection -- Load ID cache, Who's Here, and start background sync.
    _deferred_startup       -- Post-mainloop startup: verify sheet, auth state, begin init.
    on_closing              -- Clean up background threads before the window closes.

Module-level variables of note:
    sign_ins                -- dict: name → timestamp string of currently signed-in people.
    volunteeringList        -- list of non-standard worksheet names shown in the event dropdown.
    eventsList              -- list of worksheet names populating the event OptionMenu.
    logging_field_toggles   -- dict controlling which attendance columns are written.
    worksheet_targets       -- Ordered list of preferred attendance worksheet names.
    late_signin_cutoff      -- HH:MM (24h) after which a sign-in is considered late.
    early_signout_cutoff    -- HH:MM (24h) before which a sign-out is considered early.
    camera_frequency        -- Probability (0.05–1.0) that a photo is taken per event.
    camera_trigger          -- When camera fires: "in", "out", "both", or "never".
    keyboardless_mode       -- True when barcode-scanner input mode is active.
    easy_signin_mode        -- True when sign-in/out direction is auto-detected locally.
    ui_theme                -- Active theme name: "Light", "Dark", or "Black & Gold".
    main_ui_scale           -- Scale multiplier for the main window fonts (0.5–2.0).
    whos_here_scale         -- Scale multiplier for the Who's Here window fonts (0.5–2.0).
"""

import os
import sys
from PIL import ImageFont
from datetime import datetime
import tkinter as tk
from tkinter import messagebox, Label, Entry, Button, Toplevel, Radiobutton, StringVar, OptionMenu, BooleanVar, Checkbutton
from driveUpload import *
from camera import takePic
from google_auth import is_signed_in, get_user_email, sign_out, sign_in
from tkinter import font
import time
import threading
import random
import json

# --- Begin: Embedding Poppins (runtime only) --------------------------------
# Purpose: when packaged with PyInstaller, the font file will be extracted into
# the bundle; we load it for the current process so tkinter can use the family.
if os.name == "nt":
    import ctypes
    FR_PRIVATE = 0x10

def _get_base_path():
    """
    Return folder where bundled resources live:
    - when running from PyInstaller onefile exe, sys._MEIPASS points to temp bundle
    - otherwise use script dir
    """
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

def load_private_font(filename):
    """
    Loads a TTF font for this process only (Windows). Safe, temporary.
    Call early before creating font.Font instances.
    """
    font_path = os.path.join(_get_base_path(), filename)
    if os.name == "nt" and os.path.exists(font_path):
        try:
            ctypes.windll.gdi32.AddFontResourceExW(font_path, FR_PRIVATE, 0)
        except Exception:
            # best-effort: if we can't load it, fall back to system fonts
            pass
    # On non-Windows systems tkinter will use the system font fallback
    return font_path


# Global dictionary to track current signed-in people.
# Keys: person's name (string) -> value: sign-in timestamp string (e.g. "03:24 PM, 2025-12-04")
sign_ins = {}

# Volunteering list (populated later after settings/sheet are loaded)
volunteeringList = []

# Event sheet options used by the "Why are you here" dropdown.
NO_ACTIVE_WORKSHEETS_LABEL = "(No Active Worksheets)"
LOADING_SHEETS_LABEL = "Loading sheets\u2026"
eventsList = [NO_ACTIVE_WORKSHEETS_LABEL]
event_dropdown = None

LOGGING_FIELD_DEFAULTS = {
    "name": True,
    "timestamp": True,
    "image_link": True,
    "image_path": True,
    "reason": True,
}

# Persisted data logging configuration.
logging_field_toggles = LOGGING_FIELD_DEFAULTS.copy()
worksheet_targets = []
late_signin_cutoff = "15:45"
early_signout_cutoff = "18:45"
worksheet_cutoff_toggles = {}


def _parse_hhmm(value):
    """Parse HH:MM (24h) and return (hour, minute) or None."""
    try:
        text = str(value).strip()
        parts = text.split(":")
        if len(parts) != 2:
            return None
        hour = int(parts[0])
        minute = int(parts[1])
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return None
        return hour, minute
    except Exception:
        return None


def _normalize_hhmm_or_default(value, default_value):
    """Return normalized HH:MM using default when parsing fails."""
    parsed = _parse_hhmm(value)
    if parsed is None:
        parsed = _parse_hhmm(default_value)
    if parsed is None:
        parsed = (0, 0)
    return f"{parsed[0]:02d}:{parsed[1]:02d}"


def _hhmm_to_minutes(value, default_value):
    """Convert HH:MM to minutes-from-midnight using default on parse errors."""
    parsed = _parse_hhmm(value)
    if parsed is None:
        parsed = _parse_hhmm(default_value)
    if parsed is None:
        parsed = (0, 0)
    return parsed[0] * 60 + parsed[1]


def get_effective_logging_fields(camera_trigger_override=None):
    """Return logging field toggles after applying hard runtime constraints."""
    fields = LOGGING_FIELD_DEFAULTS.copy()
    fields.update(logging_field_toggles)

    trigger = camera_trigger_override if camera_trigger_override is not None else camera_trigger
    if trigger == "never":
        fields["image_link"] = False
        fields["image_path"] = False

    return fields


def _sanitize_worksheet_targets(targets):
    """Return an ordered, deduplicated worksheet list excluding reserved tabs."""
    cleaned = []
    for item in targets or []:
        title = str(item).strip()
        if title and title != "IDs" and title not in cleaned:
            cleaned.append(title)
    return cleaned


def _apply_worksheet_target_order(attendance_sheets):
    """Apply configured worksheet target order and return active dropdown options."""
    global worksheet_targets

    configured = _sanitize_worksheet_targets(worksheet_targets)
    available = [s for s in attendance_sheets if s and s != "IDs"]
    ordered = [s for s in configured if s in available]
    ordered.extend([s for s in available if s not in ordered])

    worksheet_targets = ordered
    return ordered


def _attendance_sheets_from_list(sheet_names):
    """Return worksheet names that can receive attendance rows."""
    available = [s for s in sheet_names if s and s != "IDs"]
    return _apply_worksheet_target_order(available)


def _refresh_event_dropdown(sheet_names):
    """Update event dropdown options on the UI thread."""
    global eventsList

    choices = _attendance_sheets_from_list(sheet_names)
    has_real_sheets = bool(choices)
    if not choices:
        choices = [NO_ACTIVE_WORKSHEETS_LABEL]

    eventsList = choices

    try:
        if event_dropdown is not None:
            menu = event_dropdown["menu"]
            menu.delete(0, "end")
            for item in choices:
                menu.add_command(label=item, command=tk._setit(event_var, item))
        if event_var.get() not in choices:
            event_var.set(choices[0])
    except Exception:
        pass

    # Enable form inputs only when real sheets are available
    set_ui_sheets_state(has_real_sheets)


_INACTIVE_LABELS = {NO_ACTIVE_WORKSHEETS_LABEL, LOADING_SHEETS_LABEL}


def _has_active_worksheet_selection():
    """Return True when current selected event points at a real worksheet."""
    current = event_var.get()
    return bool(current and current not in _INACTIVE_LABELS and current in eventsList)


def _first_active_worksheet_name():
    """Return the first active worksheet option, or empty string when unavailable."""
    for sheet in eventsList:
        if sheet and sheet not in _INACTIVE_LABELS and sheet != "IDs":
            return sheet
    return ""


local_sheet_refresh_queued = False


def queue_local_sheet_refresh():
    """Queue a non-blocking refresh of all locally-cached sheet data."""
    global local_sheet_refresh_queued

    if local_sheet_refresh_queued:
        return
    if not get_default_doc():
        return

    local_sheet_refresh_queued = True

    def _refresh_worker():
        global local_sheet_refresh_queued
        try:
            all_sheets = list_sheets()
            sheets_to_scan = _sync_sheet_metadata(all_sheets)

            try:
                load_ids_cache()
            except Exception as e:
                print(f"Warning: Failed to refresh IDs cache: {e}")

            try:
                loaded = fetch_whos_here_from_sheets(sheets_to_scan) if sheets_to_scan else {}
                sign_ins.clear()
                for pname, pts in loaded.items():
                    sign_ins[pname] = pts
                root.after(0, refresh_whos_here_window)
                print(f"Local sheet refresh complete. Loaded {len(loaded)} active sign-ins.")
            except Exception as e:
                print(f"Warning: Failed to refresh Who's Here cache: {e}")
        except Exception as e:
            print(f"Warning: Local sheet refresh failed: {e}")
        finally:
            local_sheet_refresh_queued = False

    threading.Thread(target=_refresh_worker, daemon=True).start()


def _sync_sheet_metadata(all_sheets):
    """Sync volunteering/event metadata from current spreadsheet worksheets."""
    global volunteeringList, worksheet_cutoff_toggles

    before_targets = list(worksheet_targets)
    before_cutoff_toggles = dict(worksheet_cutoff_toggles)
    attendance_sheets = _attendance_sheets_from_list(all_sheets)
    volunteeringList = [s for s in attendance_sheets if s not in ("Main Attendance", "Build Season")]
    worksheet_cutoff_toggles = {
        sheet: bool(worksheet_cutoff_toggles.get(sheet, sheet == "Main Attendance"))
        for sheet in attendance_sheets
    }

    if before_targets != worksheet_targets or before_cutoff_toggles != worksheet_cutoff_toggles:
        try:
            save_settings()
        except Exception:
            pass

    try:
        root.after(0, lambda: _refresh_event_dropdown(all_sheets))
    except Exception:
        _refresh_event_dropdown(all_sheets)

    return attendance_sheets


def initialize_google_connection():
    """Initialize IDs cache, Who's Here, background sync, and volunteering list.

    Call this after the sheet_name is known (either on startup or after the
    user configures their sheet in the options).  Safe to call more than once.
    """
    global volunteeringList

    doc = get_default_doc()
    if not doc:
        print("No Google Sheet configured — skipping initialization.")
        return False

    try:
        ensure_ids_sheet_exists()
        print("IDs sheet ready.")

        print("Loading IDs cache from Google Sheets...")
        if load_ids_cache():
            print("IDs cache loaded successfully.")
        else:
            print("Warning: Failed to load IDs cache.")

        all_sheets = list_sheets()
        print(all_sheets)
        sheets_to_scan = _sync_sheet_metadata(all_sheets)

        print("Loading Who's Here from Google Sheets...")
        try:
            if sheets_to_scan:
                loaded_signins = fetch_whos_here_from_sheets(sheets_to_scan)
            else:
                loaded_signins = {}
            for pname, pts in loaded_signins.items():
                sign_ins[pname] = pts
            print(f"Loaded {len(loaded_signins)} currently signed-in people from sheets.")
        except Exception as e:
            print(f"Warning: Could not load Who's Here from sheets: {e}")

        start_background_sync()
        print("Background sync started.")
    except Exception as e:
        print(f"Warning: Could not initialize IDs system: {e}")

    # Refresh volunteering list and event dropdown metadata
    try:
        all_sheets = list_sheets()
        print(all_sheets)
        _sync_sheet_metadata(all_sheets)
    except Exception as e:
        print(f"Warning: Could not list sheets: {e}")
        volunteeringList = []

    return True


# --------------------------
# UI state variables (can be toggled via Options)
# --------------------------
ui_theme = "Light"   # "Light", "Dark" or "Black & Gold"
main_ui_scale = 1.0  # Scale multiplier for main UI (0.5 - 2.0)
whos_here_scale = 1.0  # Scale multiplier for Who's Here window (0.5 - 2.0)

# --------------------------
# Theme definitions
# --------------------------
THEMES = {
    "Light": {
        "BG_MAIN": "#F3F6FA",
        "PANEL_BG": "#FFFFFF",
        "ACCENT": "#1565C0",
        "ACCENT_DARK": "#0D47A1",
        "TEXT": "#1F2D3D",
        "POSITIVE": "#2E7D32",
        "NEGATIVE": "#C62828",
        "CARD_BORDER": "#E6ECF2",
        "BUTTON_ACTIVE": "#0B63C7",
        "INPUT_BG": "#FFFFFF",
        "FOOTER_TEXT": "#5D6D7E",
        "OPTION_MENU_BG": "#FFFFFF",
        "OPTION_MENU_FG": "#1F2D3D"
    },
    "Dark": {
        # Neutral grey/black aesthetic inspired by Firefox private browsing (grey/black)
        "BG_MAIN": "#0B0D0F",
        "PANEL_BG": "#111417",
        "ACCENT": "#1B6ED6",
        "ACCENT_DARK": "#1356A8",
        "TEXT": "#EAF3FF",
        "POSITIVE": "#6FC17A",
        "NEGATIVE": "#FF6B6B",
        "CARD_BORDER": "#16232B",
        "BUTTON_ACTIVE": "#0F5FAE",
        "INPUT_BG": "#071016",
        "FOOTER_TEXT": "#94A9BD",
        "OPTION_MENU_BG": "#111417",
        "OPTION_MENU_FG": "#EAF3FF"
    }
    ,
    "Black & Gold": {
        # High-contrast black with gold accents
        "BG_MAIN": "#000000",
        "PANEL_BG": "#0B0B0B",
        "ACCENT": "#D4AF37",
        "ACCENT_DARK": "#A67C00",
        "TEXT": "#F5F1E6",
        "POSITIVE": "#6FC17A",
        "NEGATIVE": "#FF6B6B",
        "CARD_BORDER": "#1A1A1A",
        "BUTTON_ACTIVE": "#B8860B",
        "INPUT_BG": "#0A0A0A",
        "FOOTER_TEXT": "#CFC0A6",
        "OPTION_MENU_BG": "#0B0B0B",
        "OPTION_MENU_FG": "#F5F1E6"
    }
}

# theme globals (set by apply_ui_settings)
BG_MAIN = None
PANEL_BG = None
ACCENT = None
ACCENT_DARK = None
TEXT = None
POSITIVE = None
NEGATIVE = None
CARD_BORDER = None
BUTTON_ACTIVE = None
INPUT_BG = None
FOOTER_TEXT = None
OPTION_MENU_BG = None
OPTION_MENU_FG = None

# --------------------------
# Geometry helpers
# --------------------------

def center_window(window, width=500, height=400):
    """Center ``window`` on the primary display at the given pixel dimensions."""
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    x = (screen_width // 2) - (width // 2)
    y = (screen_height // 2) - (height // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")

def center_and_fit(window, inner_widget, pad_x=60, pad_y=60, max_width=None, max_height=None):
    """Resize ``window`` to fit ``inner_widget`` plus padding, then center it.

    Clamps the final size to the screen minus 80 px on each side so the window
    never exceeds the display.

    Args:
        window:       The Toplevel or Tk window to resize.
        inner_widget: The widget whose requested dimensions drive the size.
        pad_x:        Extra horizontal pixels to add around the inner widget.
        pad_y:        Extra vertical pixels to add around the inner widget.
        max_width:    Upper bound in pixels; defaults to screen width − 80.
        max_height:   Upper bound in pixels; defaults to screen height − 80.
    """
    window.update_idletasks()
    req_w = inner_widget.winfo_reqwidth() + pad_x
    req_h = inner_widget.winfo_reqheight() + pad_y
    if max_width is None:
        max_width = window.winfo_screenwidth() - 80
    if max_height is None:
        max_height = window.winfo_screenheight() - 80
    final_w = min(req_w, max_width)
    final_h = min(req_h, max_height)
    center_window(window, width=final_w, height=final_h)


def adjust_all_toplevels_to_scale():
    """Attempt to resize all open Toplevel windows to fit their content.

    This finds the first Frame child inside each Toplevel and calls
    `center_and_fit` so dialogs/popup windows expand to accommodate font scaling.
    """
    try:
        for w in root.winfo_children():
            try:
                # Some platforms return strings; be defensive
                if getattr(w, 'winfo_class', lambda: '')() == 'Toplevel' or isinstance(w, tk.Toplevel):
                    # find a suitable inner widget (card) to size to
                    inner = None
                    for c in w.winfo_children():
                        if isinstance(c, tk.Frame):
                            inner = c
                            break
                    if inner is not None:
                        try:
                            inner.update_idletasks()
                            center_and_fit(w, inner, pad_x=80, pad_y=80)
                        except Exception:
                            pass
            except Exception:
                pass
    except Exception:
        pass

# --------------------------
# Fonts
# --------------------------
tk_font_large = None
tk_font_medium = None
tk_font_smedium = None
tk_font_small = None

def create_fonts():
    """Create and assign the four Poppins font sizes scaled by ``main_ui_scale``.

    Replaces the four tk_font_* globals with new Font objects.  Must be called
    after the Tk root exists and whenever ``main_ui_scale`` changes.
    """
    global tk_font_large, tk_font_medium, tk_font_smedium, tk_font_small
    # Base sizes scaled by main_ui_scale (0.5 - 2.0)
    tk_font_large = font.Font(family="Poppins", size=int(48 * main_ui_scale))
    tk_font_medium = font.Font(family="Poppins", size=int(36 * main_ui_scale))
    tk_font_smedium = font.Font(family="Poppins", size=int(28 * main_ui_scale))
    tk_font_small = font.Font(family="Poppins", size=int(18 * main_ui_scale))

# --------------------------
# Styling: entries & optionmenus helpers
# --------------------------

def style_optionmenu(optmenu):
    """Apply theme colours and font to an OptionMenu and its dropdown menu."""
    try:
        optmenu.configure(
            font=tk_font_small,
            bg=OPTION_MENU_BG,
            fg=OPTION_MENU_FG,
            activebackground=OPTION_MENU_BG,
            activeforeground=OPTION_MENU_FG,
            bd=0,
            relief="flat",
            highlightthickness=1,
            highlightbackground=CARD_BORDER
        )
        m = optmenu["menu"]
        # menu background/foreground and active colors
        m.configure(bg=OPTION_MENU_BG, fg=OPTION_MENU_FG, activebackground=ACCENT_DARK, activeforeground=OPTION_MENU_FG, bd=0, font=tk_font_small)
    except Exception:
        pass

def style_entry(entry):
    """Apply theme colours and an accent outline to an Entry widget.

    Uses a thicker highlight border in Dark and Black & Gold themes for
    stronger contrast against the dark background.
    """
    try:
        thick = 3 if ui_theme in ("Dark", "Black & Gold") else 2
        entry.configure(bg=INPUT_BG, fg=TEXT, insertbackground=TEXT,
                        bd=0, relief="flat", font=tk_font_small,
                        highlightthickness=thick, highlightbackground=CARD_BORDER, highlightcolor=ACCENT)
        entry.configure(justify="center")
    except Exception:
        pass

# --------------------------
# Apply theme and style existing widgets (UI-only)
# --------------------------

def apply_ui_settings():
    """Apply the active theme and font scale to all existing widgets.

    Reads ``ui_theme`` and ``main_ui_scale`` globals, updates the colour
    globals (BG_MAIN, ACCENT, …), recreates fonts via ``create_fonts``, then
    walks the widget tree recursively to restyle every Frame, Label, Entry,
    Button, OptionMenu, Radiobutton, and Checkbutton.
    """
    global BG_MAIN, PANEL_BG, ACCENT, ACCENT_DARK, TEXT, POSITIVE, NEGATIVE, CARD_BORDER, BUTTON_ACTIVE, INPUT_BG, FOOTER_TEXT, OPTION_MENU_BG, OPTION_MENU_FG
    theme = THEMES.get(ui_theme, THEMES["Light"])
    BG_MAIN = theme["BG_MAIN"]
    PANEL_BG = theme["PANEL_BG"]
    ACCENT = theme["ACCENT"]
    ACCENT_DARK = theme["ACCENT_DARK"]
    TEXT = theme["TEXT"]
    POSITIVE = theme["POSITIVE"]
    NEGATIVE = theme["NEGATIVE"]
    CARD_BORDER = theme["CARD_BORDER"]
    BUTTON_ACTIVE = theme["BUTTON_ACTIVE"]
    INPUT_BG = theme["INPUT_BG"]
    FOOTER_TEXT = theme["FOOTER_TEXT"]
    OPTION_MENU_BG = theme["OPTION_MENU_BG"]
    OPTION_MENU_FG = theme["OPTION_MENU_FG"]

    load_private_font(os.path.join("fonts", "Poppins-Regular.ttf"))
    create_fonts()

    # Root background
    try:
        root.configure(bg=BG_MAIN)
    except NameError:
        pass

    # style main frames only if they exist
    for frame_name in ("header", "main_card", "action_row", "footer"):
        try:
            obj = globals().get(frame_name)
            if obj:
                bg_color = PANEL_BG if frame_name in ("header", "main_card") else BG_MAIN
                obj.configure(bg=bg_color)
        except Exception:
            pass

    # header title
    try:
        header_title.configure(bg=PANEL_BG, fg=TEXT, font=tk_font_large)
    except Exception:
        pass

    # Enter button
    try:
        enter_btn.configure(bg=ACCENT, fg="white", font=tk_font_smedium, activebackground=ACCENT_DARK)
    except Exception:
        pass

    # Options button styling
    try:
        options_btn.configure(bg=PANEL_BG, fg=TEXT, font=tk_font_small, activebackground=ACCENT_DARK)
    except Exception:
        pass

    # style all widgets recursively (entries, optionmenus, buttons, labels)
    def recursive_style(widget):
        for child in widget.winfo_children():
            try:
                cname = child.__class__.__name__
                if cname == "Frame":
                    child.configure(bg=PANEL_BG)
                elif cname == "Label":
                    child.configure(bg=PANEL_BG, fg=TEXT, font=tk_font_small)
                elif cname == "Entry":
                    style_entry(child)
                elif cname == "Button":
                    if child not in (enter_btn, options_btn):
                        try:
                            child.configure(bg=ACCENT, fg="white", font=tk_font_small, activebackground=ACCENT_DARK, bd=0)
                        except Exception:
                            pass
                elif cname == "OptionMenu":
                    style_optionmenu(child)
                elif cname == "Radiobutton":
                    child.configure(bg=PANEL_BG, fg=TEXT, font=tk_font_smedium, selectcolor=PANEL_BG, activebackground=PANEL_BG)
                elif cname == "Checkbutton":
                    child.configure(bg=PANEL_BG, fg=TEXT, selectcolor=PANEL_BG)
            except Exception:
                pass
            recursive_style(child)

    try:
        recursive_style(root)
    except Exception:
        pass

    # footer label
    try:
        footer_label.configure(bg=BG_MAIN, fg=FOOTER_TEXT, font=tk_font_small)
    except Exception:
        pass

# --------------------------
# Core logic functions 
# --------------------------

# Track the currently-open "Who's Here" window and its after() id so we can
# avoid multiple pollers and cancel polling when the window closes.
whos_here_win = None
whos_here_after_id = None
whos_here_populate_func = None  # Reference to populate function for manual refresh

# Camera settings: frequency is probability (0.05 - 1.0) that a picture is taken when camera is enabled.
# camera_trigger controls whether camera is used on sign in, sign out, or both.
camera_frequency = 1.0
camera_trigger = "both"  # one of: "in", "out", "both"

# Keyboardless mode settings
keyboardless_mode = False
keyboardless_bindings = {
    "sign_in": "",
    "sign_out": "",
    "internship": "",
    "build_season": "",
    "volunteering": "",
    "close_popup": ""
}

# Easy sign in mode - automatically determines sign in/out based on last action
easy_signin_mode = False

# Google Sheet ID (set by user in options)
sheet_id = ""

# Settings persistence
DEFAULT_SETTINGS = {
    "ui_theme": "Light",
    "main_ui_scale": 1.0,
    "whos_here_scale": 1.0,
    "camera_frequency": 1.0,
    "camera_trigger": "both",
    "keyboardless_mode": False,
    "keyboardless_bindings": {
        "sign_in": "",
        "sign_out": "",
        "internship": "",
        "build_season": "",
        "volunteering": "",
        "close_popup": ""
    },
    "easy_signin_mode": False,
    "sheet_id": "",
    "data_logging": {
        "fields": LOGGING_FIELD_DEFAULTS.copy(),
        "worksheet_targets": [],
        "time_cutoffs": {
            "late_signin": "15:45",
            "early_signout": "18:45"
        },
        "cutoff_enabled_by_worksheet": {}
    }
}

SETTINGS_FILE = os.path.join(_get_base_path(), "settings.json")

def save_settings():
    """Write all current settings globals to settings.json.

    Silently ignores write errors so a read-only filesystem does not crash the app.
    """
    data = {
        "ui_theme": ui_theme,
        "main_ui_scale": main_ui_scale,
        "whos_here_scale": whos_here_scale,
        "camera_frequency": camera_frequency,
        "camera_trigger": camera_trigger,
        "keyboardless_mode": keyboardless_mode,
        "keyboardless_bindings": keyboardless_bindings,
        "easy_signin_mode": easy_signin_mode,
        "sheet_id": sheet_id,
        "data_logging": {
            "fields": logging_field_toggles,
            "worksheet_targets": worksheet_targets,
            "time_cutoffs": {
                "late_signin": late_signin_cutoff,
                "early_signout": early_signout_cutoff
            },
            "cutoff_enabled_by_worksheet": worksheet_cutoff_toggles
        }
    }
    try:
        with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def load_settings():
    """Read settings.json and populate all settings globals.

    Falls back to DEFAULT_SETTINGS values for any missing or invalid key.
    Also falls back entirely to defaults if the file is missing or cannot
    be parsed, so the app always starts in a consistent state.
    """
    global ui_theme, main_ui_scale, whos_here_scale, camera_frequency, camera_trigger, keyboardless_mode, keyboardless_bindings, easy_signin_mode, sheet_id
    global logging_field_toggles, worksheet_targets, late_signin_cutoff, early_signout_cutoff, worksheet_cutoff_toggles
    try:
        if os.path.exists(SETTINGS_FILE):
            with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            ui_theme = data.get("ui_theme", DEFAULT_SETTINGS["ui_theme"])
            main_ui_scale = float(data.get("main_ui_scale", DEFAULT_SETTINGS["main_ui_scale"]))
            whos_here_scale = float(data.get("whos_here_scale", DEFAULT_SETTINGS["whos_here_scale"]))
            camera_frequency = float(data.get("camera_frequency", DEFAULT_SETTINGS["camera_frequency"]))
            camera_trigger = data.get("camera_trigger", DEFAULT_SETTINGS["camera_trigger"])
            keyboardless_mode = bool(data.get("keyboardless_mode", DEFAULT_SETTINGS["keyboardless_mode"]))
            loaded_bindings = data.get("keyboardless_bindings", {})
            keyboardless_bindings = {
                k: loaded_bindings.get(k, "")
                for k in DEFAULT_SETTINGS["keyboardless_bindings"].keys()
            }
            easy_signin_mode = data.get("easy_signin_mode", DEFAULT_SETTINGS["easy_signin_mode"])
            sheet_id = data.get("sheet_id", DEFAULT_SETTINGS["sheet_id"])

            loaded_data_logging = data.get("data_logging", {})
            loaded_fields = loaded_data_logging.get("fields", {}) if isinstance(loaded_data_logging, dict) else {}
            logging_field_toggles = {
                k: bool(loaded_fields.get(k, v))
                for k, v in LOGGING_FIELD_DEFAULTS.items()
            }
            loaded_targets = loaded_data_logging.get("worksheet_targets", []) if isinstance(loaded_data_logging, dict) else []
            worksheet_targets = _sanitize_worksheet_targets(loaded_targets)

            loaded_cutoff_toggles = loaded_data_logging.get("cutoff_enabled_by_worksheet", {}) if isinstance(loaded_data_logging, dict) else {}
            worksheet_cutoff_toggles = {
                str(k).strip(): bool(v)
                for k, v in loaded_cutoff_toggles.items()
                if str(k).strip() and str(k).strip() != "IDs"
            }

            loaded_cutoffs = loaded_data_logging.get("time_cutoffs", {}) if isinstance(loaded_data_logging, dict) else {}
            late_signin_cutoff = _normalize_hhmm_or_default(
                loaded_cutoffs.get("late_signin", DEFAULT_SETTINGS["data_logging"]["time_cutoffs"]["late_signin"]),
                DEFAULT_SETTINGS["data_logging"]["time_cutoffs"]["late_signin"]
            )
            early_signout_cutoff = _normalize_hhmm_or_default(
                loaded_cutoffs.get("early_signout", DEFAULT_SETTINGS["data_logging"]["time_cutoffs"]["early_signout"]),
                DEFAULT_SETTINGS["data_logging"]["time_cutoffs"]["early_signout"]
            )
    except Exception:
        # on error, fall back to defaults
        ui_theme = DEFAULT_SETTINGS["ui_theme"]
        main_ui_scale = DEFAULT_SETTINGS["main_ui_scale"]
        whos_here_scale = DEFAULT_SETTINGS["whos_here_scale"]
        camera_frequency = DEFAULT_SETTINGS["camera_frequency"]
        camera_trigger = DEFAULT_SETTINGS["camera_trigger"]
        keyboardless_mode = DEFAULT_SETTINGS["keyboardless_mode"]
        keyboardless_bindings = DEFAULT_SETTINGS["keyboardless_bindings"].copy()
        easy_signin_mode = DEFAULT_SETTINGS["easy_signin_mode"]
        sheet_id = DEFAULT_SETTINGS["sheet_id"]
        logging_field_toggles = DEFAULT_SETTINGS["data_logging"]["fields"].copy()
        worksheet_targets = DEFAULT_SETTINGS["data_logging"]["worksheet_targets"].copy()
        late_signin_cutoff = DEFAULT_SETTINGS["data_logging"]["time_cutoffs"]["late_signin"]
        early_signout_cutoff = DEFAULT_SETTINGS["data_logging"]["time_cutoffs"]["early_signout"]
        worksheet_cutoff_toggles = DEFAULT_SETTINGS["data_logging"]["cutoff_enabled_by_worksheet"].copy()

def add_sign_in(name, timestamp_str):
    """Add or update a person's sign-in time in the global tracking dict."""
    try:
        sign_ins[name] = timestamp_str
    except Exception:
        pass

def remove_sign_in(name):
    """Remove a person from the global tracking dict if present."""
    try:
        sign_ins.pop(name, None)
    except Exception:
        pass

def get_current_signins():
    """Return a shallow copy of current sign-ins.

    Returns:
        dict: name -> timestamp string
    """
    return dict(sign_ins)

def refresh_whos_here_window():
    """Manually trigger a refresh of the Who's Here window if it's open."""
    global whos_here_win, whos_here_populate_func
    try:
        if whos_here_win is not None and whos_here_win.winfo_exists() and whos_here_populate_func is not None:
            whos_here_populate_func()
    except Exception:
        pass


def scan_id(event=None):
    """Read and validate the ID entry, then route to name-entry or the smile/camera flow.

    Guards:
      - Blocks if not signed in to Google.
      - Blocks if no Google Sheet is configured.
      - Blocks if the event dropdown has no active worksheet selection.
      - Validates that the entered value is a six-digit positive integer.

    On success, performs an instant local cache lookup for the ID.  If the name
    is not found and the name field is enabled, opens ``ask_name_window``.
    Otherwise calls ``open_smile_window`` directly.

    Args:
        event: Optional Tkinter event (passed automatically when bound to a key).
    """
    # Guard: must be signed in before recording attendance
    if not is_signed_in():
        messagebox.showwarning(
            "Not Signed In",
            "Please sign in via Options \u2192 Google Settings before recording attendance."
        )
        return

    # Guard: ensure a sheet is configured before allowing attendance
    if not get_default_doc():
        messagebox.showwarning(
            "Google Sheet Not Configured",
            "Please configure a Google Sheet first.\n"
            "Go to Settings → Google Settings."
        )
        return

    if not _has_active_worksheet_selection():
        messagebox.showwarning(
            "No Active Worksheet",
            "No active worksheet is available for attendance logging.\n"
            "Add or connect worksheet tabs in Settings → Google Settings."
        )
        return

    try:
        current_id = int(id_entry.get())
        if len(str(current_id)) != 6 or current_id < 0:
            raise ValueError("Invalid length")
    except ValueError as e:
        messagebox.showerror("Error", f"Invalid ID: {str(e)}")
        return

    id_entry.delete(0, tk.END)
    
    # get_name_by_id is now an instant local cache lookup — no loading window needed
    try:
        effective_fields = get_effective_logging_fields()
        name = get_name_by_id(current_id)
        if not name:
            if effective_fields.get("name", True):
                ask_name_window(current_id)
            else:
                # Name collection disabled: operate with an ID-based placeholder.
                open_smile_window(current_id, f"ID {current_id}")
        else:
            open_smile_window(current_id, name)
    except Exception as e:
        messagebox.showerror("Error", f"Failed to lookup ID: {str(e)}")

def open_id_lookup_loading_window():
    """Display a modal 'Looking up ID' progress dialog and return it.

    The caller is responsible for destroying the returned window once the
    lookup completes.  This dialog is no longer used in the main flow (ID
    lookup is now an instant cache hit), but is kept for potential reuse.

    Returns:
        The Toplevel loading window.
    """
    loading_window = Toplevel(root)
    loading_window.title("Loading...")
    center_window(loading_window, width=500, height=180)
    loading_window.configure(bg=BG_MAIN)
    loading_window.focus_force()

    card = tk.Frame(loading_window, bg=PANEL_BG, bd=1, relief="solid")
    card.place(relx=0.5, rely=0.5, anchor=tk.CENTER, width=460, height=140)
    try:
        card.configure(highlightbackground=CARD_BORDER)
    except Exception:
        pass

    loading_label = Label(
        card,
        text="Looking up ID — please wait...",
        font=tk_font_small,
        fg=TEXT,
        bg=PANEL_BG,
        wraplength=420,
        justify="center"
    )
    loading_label.pack(expand=True, fill=tk.BOTH, padx=12, pady=12)
    
    center_and_fit(loading_window, card, pad_x=80, pad_y=80)
    return loading_window

def ask_name_window(current_id):
    """Show a dialog asking the user to type their first and last name.

    Capitalises first and last tokens, saves the ID/name pair to the local
    cache (and queues it for background sheet upload via save_id_name_pair),
    then opens ``open_smile_window`` on success.

    Args:
        current_id: The six-digit integer ID that was scanned.
    """
    new_window = Toplevel(root)
    new_window.title("Enter Name")
    center_window(new_window, width=460, height=260)
    new_window.configure(bg=BG_MAIN)
    new_window.focus_force()

    card = tk.Frame(new_window, bg=PANEL_BG, bd=1, relief="solid", highlightthickness=1)
    card.place(relx=0.5, rely=0.5, anchor=tk.CENTER, width=420, height=int(200 * main_ui_scale))
    try:
        card.configure(highlightbackground=CARD_BORDER)
    except Exception:
        pass

    Label(card, text="Enter your first AND last name:", bg=PANEL_BG, fg=TEXT, font=tk_font_small, wraplength=380, justify="center").pack(pady=(16, 6))

    name_entry = Entry(card, font=tk_font_small, bd=0, justify="center", bg=INPUT_BG, width=34)
    name_entry.pack(fill="x", pady=4, ipadx=10, ipady=8)
    name_entry.focus()
    style_entry(name_entry)

    def save_name(event=None):
        name = name_entry.get().strip()
        sName = name.split()
        if len(sName) >= 2:
            sName[0] = sName[0].capitalize()
            sName[1] = sName[1].capitalize()
            formatted = " ".join(sName)
        else:
            formatted = name

        if formatted:
            # save_id_name_pair is now instant (local cache + background queue)
            ok = save_id_name_pair(current_id, formatted)
            new_window.destroy()
            if ok:
                open_smile_window(current_id, formatted)
            else:
                messagebox.showerror("Error", "Failed to save ID-name pair.")
        else:
            messagebox.showerror("Error", "Name cannot be empty.", parent=new_window)

    btn_frame = tk.Frame(card, bg=PANEL_BG)
    btn_frame.pack(pady=(8, 12), fill="x", padx=18)
    submit_btn = tk.Button(btn_frame, text="Submit", command=save_name, bg=ACCENT, fg="white",
                           font=tk_font_small, bd=0, activebackground=ACCENT_DARK, padx=12, pady=8)
    submit_btn.pack(side="right")

    # Bind Enter to submit (both on the entry and the popup window)
    name_entry.bind("<Return>", lambda e: save_name())
    new_window.bind("<Return>", lambda e: save_name())

    center_and_fit(new_window, card, pad_x=80, pad_y=80)


def open_name_submit_loading_window():
    """Show a themed loading window while the name/ID save is in progress."""
    loading_window = Toplevel(root)
    loading_window.title("Saving...")
    center_window(loading_window, width=500, height=180)
    loading_window.configure(bg=BG_MAIN)
    loading_window.focus_force()

    card = tk.Frame(loading_window, bg=PANEL_BG, bd=1, relief="solid")
    card.place(relx=0.5, rely=0.5, anchor=tk.CENTER, width=460, height=140)
    try:
        card.configure(highlightbackground=CARD_BORDER)
    except Exception:
        pass

    loading_label = Label(
        card,
        text="Saving — please wait...",
        font=tk_font_small,
        fg=TEXT,
        bg=PANEL_BG,
        wraplength=420,
        justify="center"
    )
    loading_label.pack(expand=True, fill=tk.BOTH, padx=12, pady=12)

    center_and_fit(loading_window, card, pad_x=80, pad_y=80)
    return loading_window

def open_smile_window(current_id, name):
    """Show the 'Smile!' popup and schedule camera capture after 500 ms.

    Checks camera_trigger and camera_frequency before showing the popup;
    if the camera is disabled for the current action or the probabilistic
    frequency check fails, skips the popup entirely and calls
    ``process_attendance`` directly with ``hasPic=False``.

    In easy_signin_mode the sign-in/out direction is determined from the
    local sign_ins dict rather than the radiobutton selection.

    Args:
        current_id: The six-digit integer ID that was scanned.
        name:       The student's display name (from cache or just entered).
    """
    # Decide whether we will actually attempt to take a picture. If the camera
    # is disabled for this action or the probabilistic frequency check fails,
    # bypass the picture flow entirely and proceed to record attendance
    # (with hasPic=False) — this avoids showing a transient popup.
    try:
        global camera_frequency, camera_trigger
        # Determine the effective action (respect easy_signin_mode if enabled)
        try:
            if easy_signin_mode:
                # Use local sign_ins dict instead of API call
                action = "out" if name in sign_ins else "in"
            else:
                action = action_var.get()
        except Exception:
            action = action_var.get()

        camera_enabled_for_action = (camera_trigger == "both") or (camera_trigger == action)
    except Exception:
        camera_enabled_for_action = True

    # If camera is not enabled for this action, bypass picture flow
    if not camera_enabled_for_action:
        process_attendance(current_id, name, hasPic=False)
        return

    # Apply probabilistic frequency check before showing UI
    try:
        p = float(camera_frequency)
    except Exception:
        p = 1.0
    if p < 1.0 and random.random() > p:
        process_attendance(current_id, name, hasPic=False)
        return

    # Camera will be used; show the Smile popup and take the picture shortly.
    smile_window = Toplevel(root)
    smile_window.title("Smile!")
    center_window(smile_window, width=480, height=320)
    smile_window.configure(bg=BG_MAIN)
    smile_window.focus_force()

    card = tk.Frame(smile_window, bg=PANEL_BG, bd=1, relief="solid")
    card.place(relx=0.5, rely=0.5, anchor=tk.CENTER, width=440, height=260)
    try:
        card.configure(highlightbackground=CARD_BORDER)
    except Exception:
        pass

    display_smile_message(card)
    smile_window.after(500, lambda: take_picture_and_record(smile_window, current_id, name))

def display_smile_message(container):
    """Clear ``container`` and render the 'Smile!' label in POSITIVE colour."""
    for widget in container.winfo_children():
        widget.destroy()
    smile_label = Label(
        container,
        text="😊  Smile!  😊",
        font=tk_font_medium,
        fg=POSITIVE,
        bg=PANEL_BG
    )
    smile_label.pack(expand=True, fill=tk.BOTH)

def take_picture_and_record(window, current_id, name):
    """Capture a webcam photo, then call process_attendance or open the fail dialog.

    Re-checks camera_trigger and camera_frequency in case the smile popup was
    already showing when settings changed.  On a successful capture (takePic
    returns None) calls ``process_attendance``; on failure opens
    ``open_fail_window``.

    Args:
        window:     The smile Toplevel to destroy before proceeding.
        current_id: The six-digit integer ID that was scanned.
        name:       The student's display name.
    """
    now = datetime.now()
    global folder
    folder = f"images/{current_id}-{name}"
    if not os.path.isdir(folder):
        os.makedirs(folder)

    # Decide whether to attempt taking a picture based on camera settings
    try:
        global camera_frequency, camera_trigger
        action = action_var.get()
        camera_enabled_for_action = (camera_trigger == "both") or (camera_trigger == action)
    except Exception:
        camera_enabled_for_action = True

    # If camera is not enabled for this action, skip taking picture
    if not camera_enabled_for_action:
        try:
            window.destroy()
        except Exception:
            pass
        process_attendance(current_id, name, hasPic=False)
        return

    # Camera is enabled for this action; apply probabilistic frequency
    try:
        p = float(camera_frequency)
    except Exception:
        p = 1.0

    # If random test fails, skip taking picture
    if p < 1.0 and random.random() > p:
        try:
            window.destroy()
        except Exception:
            pass
        process_attendance(current_id, name, hasPic=False)
        return

    file_date = now.strftime("%I-%M-%p-%Y-%m-%d")
    global picName
    picName = f"{name}__{file_date}.jpeg"
    confirmation = takePic(f"{name}__{file_date}", f"{current_id}-{name}")

    window.destroy()
    if (confirmation == None):
        process_attendance(current_id, name)
    else:
        open_fail_window(current_id, name)

def open_fail_window(current_id, name):
    """Show the camera-failure dialog.

    Displays an error message and binds Ctrl+O as a hidden override that
    allows proceeding without a photo (``process_attendance`` with
    ``hasPic=False``).

    Args:
        current_id: The six-digit integer ID that was scanned.
        name:       The student's display name.

    Returns:
        The Toplevel fail window.
    """
    fail_window = Toplevel(root)
    fail_window.title("Camera Failure")
    center_window(fail_window, width=680, height=220)
    fail_window.configure(bg=BG_MAIN)
    fail_window.focus_force()
    fail_window.bind("<Control-o>", lambda event: process_attendance(current_id, name, False))

    card = tk.Frame(fail_window, bg=PANEL_BG, bd=1, relief="solid")
    card.place(relx=0.5, rely=0.5, anchor=tk.CENTER, width=640, height=160)
    try:
        card.configure(highlightbackground=CARD_BORDER)
    except Exception:
        pass

    display_fail_message(card)
    center_and_fit(fail_window, card, pad_x=80, pad_y=80)
    return fail_window

def display_fail_message(container):
    """Clear ``container`` and render the camera-failure error text in NEGATIVE colour."""
    for widget in container.winfo_children():
        widget.destroy()
    loading_label = Label(
        container,
        text="Failed to take a picture. Please try again.",
        font=tk_font_small,
        fg=NEGATIVE,
        bg=PANEL_BG,
        wraplength=580,
        justify="center"
    )
    loading_label.pack(expand=True, fill=tk.BOTH, padx=12, pady=10)

def process_attendance(current_id, name, hasPic = True):
    """Record an attendance event locally and queue it for background Google push.

    Determines sign-in/out direction (easy_signin_mode or radiobutton),
    checks cutoff times to decide whether an early-sign-out or late-sign-in
    reason prompt is needed, updates the local sign_ins dict immediately,
    places the full record onto ``attendance_queue`` for the background
    worker, and shows a confirmation messagebox — all without waiting for
    Google.

    Args:
        current_id: The six-digit integer ID that was scanned.
        name:       The student's display name.
        hasPic:     Whether a photo was successfully captured for this event.
                    Ignored when both image fields are disabled in logging settings.
    """
    now = datetime.now()
    formatted_time = now.strftime("%I:%M %p")
    formatted_date = now.strftime("%Y-%m-%d")

    # Determine action based on easy_signin_mode
    if easy_signin_mode:
        # Use local sign_ins dict instead of API call
        action = "out" if name in sign_ins else "in"
    else:
        # Use the action from radiobuttons
        action = action_var.get()
    
    event = event_var.get()
    effective_fields = get_effective_logging_fields()

    reason = None
    if effective_fields.get("reason", True):
        now_minutes = now.hour * 60 + now.minute
        cutoff_enabled = bool(worksheet_cutoff_toggles.get(event, event == "Main Attendance"))
        late_cutoff_minutes = _hhmm_to_minutes(
            late_signin_cutoff,
            DEFAULT_SETTINGS["data_logging"]["time_cutoffs"]["late_signin"]
        )
        early_cutoff_minutes = _hhmm_to_minutes(
            early_signout_cutoff,
            DEFAULT_SETTINGS["data_logging"]["time_cutoffs"]["early_signout"]
        )

        if cutoff_enabled:
            if action == "out":
                if now_minutes < early_cutoff_minutes:
                    reason = early_sign_out()
            else:
                if now_minutes > late_cutoff_minutes:
                    reason = late_sign_in()

            if reason is None:
                if event == "Build Season":
                    reason = "Build Season"
                elif event not in ("Main Attendance", "Build Season"):
                    # Preserve custom worksheet context when no prompt was needed.
                    reason = event
        else:
            if event == "Main Attendance":
                reason = None
            elif event == "Build Season":
                reason = "Build Season"
            else:
                # Persist custom worksheet name in the reason column for context.
                reason = event

    full_date = f"Signed {action} at: {formatted_time}, Date: {formatted_date}"

    # If image fields are disabled, skip picture upload/write entirely.
    if not (effective_fields.get("image_link", True) or effective_fields.get("image_path", True)):
        hasPic = False

    # Update global sign-ins tracking: add on sign in, remove on sign out
    try:
        if action == "in":
            add_sign_in(name, f"{formatted_time}, {formatted_date}")
        else:
            remove_sign_in(name)
        # Trigger manual refresh of Who's Here window if open
        refresh_whos_here_window()
    except Exception:
        pass

    # Determine image folder/filename for background push
    img_folder = None
    img_picName = None
    if hasPic:
        try:
            img_folder = folder
            img_picName = picName
        except Exception:
            hasPic = False

    # Queue the Google push for background processing (non-blocking)
    attendance_queue.put((
        current_id, name, full_date, event, reason, action,
        hasPic, img_folder, img_picName, volunteeringList, effective_fields
    ))

    # Show confirmation immediately — no waiting for Google
    messagebox.showinfo(
        "Attendance Recorded",
        f"Name: {name}\n{full_date}\nReason: {reason if reason else 'N/A'}"
    )


def open_loading_window():
    """Display a 'Saving attendance' progress dialog and return it.

    The caller is responsible for destroying the returned window once the
    background push has completed.

    Returns:
        The Toplevel loading window.
    """
    loading_window = Toplevel(root)
    loading_window.title("Loading...")
    center_window(loading_window, width=500, height=180)
    loading_window.configure(bg=BG_MAIN)
    loading_window.focus_force()

    card = tk.Frame(loading_window, bg=PANEL_BG, bd=1, relief="solid")
    card.place(relx=0.5, rely=0.5, anchor=tk.CENTER, width=460, height=140)
    try:
        card.configure(highlightbackground=CARD_BORDER)
    except Exception:
        pass

    display_loading_message(card)
    center_and_fit(loading_window, card, pad_x=80, pad_y=80)
    return loading_window

def display_loading_message(container):
    """Clear ``container`` and render the 'Saving attendance' text."""
    for widget in container.winfo_children():
        widget.destroy()
    loading_label = Label(
        container,
        text="Saving attendance — please wait...",
        font=tk_font_small,
        fg=TEXT,
        bg=PANEL_BG,
        wraplength=420,
        justify="center"
    )
    loading_label.pack(expand=True, fill=tk.BOTH, padx=12, pady=12)

def push_to_google(current_id, name, attendance_record, event, reason, load, action, hasPic = True):
    """Push a single attendance record directly to Google Sheets and Drive.

    This is a legacy synchronous helper retained for completeness.  The
    active code path queues records via ``attendance_queue`` and
    ``background_sync_worker`` instead.  This function destroys ``load``
    and shows a confirmation dialog in the main thread regardless of success
    or failure.

    Args:
        current_id:        Six-digit student ID.
        name:              Student display name.
        attendance_record: Full timestamp string (e.g. "Signed in at: …").
        event:             Selected worksheet name from the event dropdown.
        reason:            Late/early reason string, or None.
        load:              The loading Toplevel to destroy when done.
        action:            ``"in"`` or ``"out"``.
        hasPic:            Whether a photo was captured for this event.
    """
    try:
        spreadsheet = setup_google_sheet()
        drive = setup_google_drive()

        if (hasPic):
            file_path = f"{folder}/{picName}"
            print(file_path)
            file_url = upload_image_to_drive(drive, file_path)
        else:
            file_path = "No Image"
            file_url = "No Image"

        sheet_names = [ws.title for ws in spreadsheet.worksheets()]
        target_sheet = event if event in sheet_names else (reason if reason in sheet_names else "Main Attendance")
        sheet = spreadsheet.worksheet(target_sheet)
        insert_data(sheet, action, [current_id, name, attendance_record, file_path, file_url, reason])

    finally:
        root.after(0, load.destroy)
        root.after(0, lambda: messagebox.showinfo(
            "Attendance Recorded",
            f"Name: {name}\n{attendance_record}\nReason: {reason if reason else 'N/A'}"
        ))

def next_available_row(sheet, col_range):
    """Return the 1-based index of the first empty row in ``col_range``.

    Args:
        sheet:     A gspread Worksheet object.
        col_range: A1-notation column range string (e.g. ``"A:A"``).

    Returns:
        int: Row number of the first row after the last non-empty cell.
    """
    values = sheet.get(col_range)
    return len(values) + 1

def insert_data(sheet, action, data):
    """Append ``data`` to the sign-in (A:F) or sign-out (H:M) block of ``sheet``.

    Args:
        sheet:  A gspread Worksheet object.
        action: ``"in"`` to write columns A–F; ``"out"`` for columns H–M.
        data:   A list of six values: [ID, Name, Timestamp, Image Path, Image URL, Reason].
    """
    if(action == "in"):
        row = next_available_row(sheet, "A:A")
        sheet.update(range_name=f"A{row}:F{row}", values=[data])
    else:
        row = next_available_row(sheet, "H:H")
        sheet.update(range_name=f"H{row}:M{row}", values=[data])

def early_sign_out():
    """Show a modal dialog prompting the user to enter an early sign-out reason.

    Blocks the calling flow via ``root.wait_window`` until the user submits or
    closes the dialog.  In keyboardless mode the entry is kept continuously
    focused and the close-popup binding dismisses without a reason.

    Returns:
        str: ``"Early sign out: <reason>"`` if submitted, or ``None`` if dismissed.
    """
    reason_window = Toplevel(root)
    reason_window.title("Reason for Early Sign-Out")
    center_window(reason_window, width=460, height=220)
    reason_window.configure(bg=BG_MAIN)
    reason_window.focus_force()

    card = tk.Frame(reason_window, bg=PANEL_BG, bd=1, relief="solid")
    card.place(relx=0.5, rely=0.5, anchor=tk.CENTER, width=420, height=int(180 * main_ui_scale))
    try:
        card.configure(highlightbackground=CARD_BORDER)
    except Exception:
        pass

    Label(card, text="Enter reason for early sign-out:", bg=PANEL_BG, fg=TEXT, font=tk_font_small, wraplength=380).pack(pady=(12, 6))
    reason_entry = Entry(card, font=tk_font_small, bd=0, bg=INPUT_BG)
    reason_entry.pack(pady=5, ipadx=6, ipady=8)
    style_entry(reason_entry)
    reason_entry.focus()

    reason = None
    def save_reason(event=None):
        nonlocal reason
        reason = reason_entry.get()
        if reason:
            reason_window.destroy()
        else:
            messagebox.showerror("Error", "Reason cannot be empty.", parent=reason_window)

    Button(card, text="Submit", command=save_reason, bg=ACCENT, fg="white", bd=0,
           font=tk_font_small, activebackground=ACCENT_DARK, padx=12, pady=8).pack(pady=(8, 10))

    # Bind Enter both on the entry and on the window
    reason_entry.bind("<Return>", lambda e: save_reason())
    reason_window.bind("<Return>", lambda e: save_reason())

    # Keyboardless mode: force focus on entry and handle close popup binding
    if keyboardless_mode:
        def keyboardless_dialog_handler(event=None):
            current_input = reason_entry.get().strip()
            if current_input == keyboardless_bindings.get("close_popup"):
                reason_entry.delete(0, tk.END)
                reason_window.destroy()
        
        reason_entry.bind("<KeyRelease>", keyboardless_dialog_handler)
        
        def refocus_reason_entry():
            if reason_window.winfo_exists():
                try:
                    reason_entry.focus_force()
                    reason_window.after(100, refocus_reason_entry)
                except Exception:
                    pass
        
        refocus_reason_entry()

    center_and_fit(reason_window, card, pad_x=80, pad_y=80)
    root.wait_window(reason_window)
    if reason:
        reason = "Early sign out: " + reason
    return reason

def late_sign_in():
    """Show a modal dialog prompting the user to enter a late sign-in reason.

    Mirrors ``early_sign_out`` in structure.  Blocks via ``root.wait_window``.

    Returns:
        str: ``"Late Sign In: <reason>"`` if submitted, or ``None`` if dismissed.
    """
    reason_window = Toplevel(root)
    reason_window.title("Reason for Late Sign-In")
    center_window(reason_window, width=460, height=220)
    reason_window.configure(bg=BG_MAIN)
    reason_window.focus_force()

    card = tk.Frame(reason_window, bg=PANEL_BG, bd=1, relief="solid")
    card.place(relx=0.5, rely=0.5, anchor=tk.CENTER, width=420, height=int(180 * main_ui_scale))
    try:
        card.configure(highlightbackground=CARD_BORDER)
    except Exception:
        pass

    Label(card, text="Enter reason for late sign-in:", bg=PANEL_BG, fg=TEXT, font=tk_font_small, wraplength=380).pack(pady=(12, 6))
    reason_entry = Entry(card, font=tk_font_small, bd=0, bg=INPUT_BG)
    reason_entry.pack(pady=5, ipadx=6, ipady=8)
    style_entry(reason_entry)
    reason_entry.focus()

    reason = None
    def save_reason(event=None):
        nonlocal reason
        reason = reason_entry.get()
        if reason:
            reason_window.destroy()
        else:
            messagebox.showerror("Error", "Reason cannot be empty.", parent=reason_window)

    Button(card, text="Submit", command=save_reason, bg=ACCENT, fg="white", bd=0,
           font=tk_font_small, activebackground=ACCENT_DARK, padx=12, pady=8).pack(pady=(8, 10))

    # Bind Enter
    reason_entry.bind("<Return>", lambda e: save_reason())
    reason_window.bind("<Return>", lambda e: save_reason())

    # Keyboardless mode: force focus on entry and handle close popup binding
    if keyboardless_mode:
        def keyboardless_dialog_handler(event=None):
            current_input = reason_entry.get().strip()
            if current_input == keyboardless_bindings.get("close_popup"):
                reason_entry.delete(0, tk.END)
                reason_window.destroy()
        
        reason_entry.bind("<KeyRelease>", keyboardless_dialog_handler)
        
        def refocus_reason_entry():
            if reason_window.winfo_exists():
                try:
                    reason_entry.focus_force()
                    reason_window.after(100, refocus_reason_entry)
                except Exception:
                    pass
        
        refocus_reason_entry()

    center_and_fit(reason_window, card, pad_x=80, pad_y=80)
    root.wait_window(reason_window)
    if reason:
        reason = "Late Sign In: " + reason
    return reason

# --------------------------
# Build main UI (fonts created before widgets)
# --------------------------
root = tk.Tk()
root.title("Attendance System")
center_window(root, width=1000, height=720)

action_var = StringVar(value="in")                              # Current radiobutton selection: "in" or "out"
event_var = StringVar(value=NO_ACTIVE_WORKSHEETS_LABEL)         # Currently selected worksheet in the event dropdown

root.attributes("-fullscreen", True)
root.bind("<Escape>", lambda event: root.attributes("-fullscreen", False))

# Initialize fonts (so widgets can use them)
# Load saved settings (if present) before creating fonts so scale is applied
load_settings()

try:
    register_api_refresh_callback(queue_local_sheet_refresh)
except Exception:
    pass

# Apply saved sheet ID to the driveUpload module
if sheet_id:
    set_default_doc(sheet_id)

load_private_font(os.path.join("fonts", "Poppins-Regular.ttf"))
create_fonts()

# Header
header = tk.Frame(root, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], bd=1, relief="solid")
header.pack(fill="x", padx=24, pady=(20, 10))
header_title = Label(header, text="Attendance System", font=tk_font_large, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=TEXT if TEXT else THEMES["Light"]["TEXT"])
header_title.pack(side="left", padx=20, pady=18)

# Options button
options_btn = tk.Button(header, text="⚙️ Options", command=lambda: open_options_window(), bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=TEXT if TEXT else THEMES["Light"]["TEXT"],
                        font=tk_font_small, bd=0, activebackground=ACCENT_DARK if ACCENT_DARK else THEMES["Light"]["ACCENT_DARK"])
options_btn.pack(side="right", padx=16, pady=12)

# Who's Here button
tracking_btn = tk.Button(header, text="Who's here?", command=lambda: open_whos_here_window(), bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=TEXT if TEXT else THEMES["Light"]["TEXT"],
                        font=tk_font_small, bd=0, activebackground=ACCENT_DARK if ACCENT_DARK else THEMES["Light"]["ACCENT_DARK"])
tracking_btn.pack(side="right", padx=16, pady=12)

# Sign-in banner — shown when not signed in, hidden otherwise.
# Height-0 trick keeps pack order stable so main_card position never shifts.
signin_banner = tk.Frame(root, bg="#FFF3CD", height=0)
signin_banner.pack(fill="x", padx=24)
signin_banner.pack_propagate(False)
signin_banner_label = Label(
    signin_banner,
    text="Not signed in  —  open Options \u2192 Google Settings to sign in. Attendance cannot be recorded.",
    bg="#FFF3CD", fg="#856404",
    font=None,  # resolved after create_fonts()
    wraplength=800,
    pady=9, padx=16,
)
signin_banner_label.pack()

# Main panel
main_card = tk.Frame(root, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], bd=1, relief="solid")
main_card.pack(expand=True, padx=24, pady=12, ipadx=10, ipady=10)
try:
    main_card.configure(highlightbackground=THEMES["Light"]["CARD_BORDER"])
except Exception:
    pass

# Inputs column
inputs_frame = tk.Frame(main_card, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"])
inputs_frame.pack(side="left", fill="both", expand=True, padx=28, pady=20)

Label(inputs_frame, text="Enter your ID:", font=tk_font_medium, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=TEXT if TEXT else THEMES["Light"]["TEXT"]).pack(anchor="w", pady=(6, 8))
id_entry = Entry(inputs_frame, font=tk_font_medium, bd=0, bg=INPUT_BG if INPUT_BG else THEMES["Light"]["INPUT_BG"], justify="center")
id_entry.pack(fill="x", pady=(0, 12), ipady=10)
style_entry(id_entry)
id_entry.bind("<Return>", lambda event: scan_id())

# Controls column
controls_frame = tk.Frame(main_card, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"])
controls_frame.pack(side="right", fill="both", expand=True, padx=28, pady=20)

Label(controls_frame, text="Why are you here:", font=tk_font_small, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=TEXT if TEXT else THEMES["Light"]["TEXT"]).pack(anchor="w", pady=(6, 6))

event_dropdown = OptionMenu(controls_frame, event_var, *eventsList)
try:
    style_optionmenu(event_dropdown)
except Exception:
    # fallback to basic config
    try:
        event_dropdown.config(font=tk_font_small)
    except Exception:
        pass
event_dropdown.pack(anchor="w", pady=(0, 12))
# bind Enter on the optionmenu to trigger no-op selection (keeps behavior consistent)
event_dropdown.bind("<Return>", lambda e: None)

# Radio buttons for sign in/out (store references for toggling visibility)
action_label = Label(controls_frame, text="Select Action:", font=tk_font_small, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=TEXT if TEXT else THEMES["Light"]["TEXT"]) 
action_label.pack(anchor="w", pady=(6, 6))
radio_signin = Radiobutton(controls_frame, text="Sign In", font=tk_font_smedium, variable=action_var, value="in", bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=TEXT if TEXT else THEMES["Light"]["TEXT"])
radio_signin.pack(anchor="w")
radio_signout = Radiobutton(controls_frame, text="Sign Out", font=tk_font_smedium, variable=action_var, value="out", bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=TEXT if TEXT else THEMES["Light"]["TEXT"])
radio_signout.pack(anchor="w")

def toggle_action_radiobuttons():
    """Show or hide the action radiobuttons based on easy_signin_mode."""
    if easy_signin_mode:
        action_label.pack_forget()
        radio_signin.pack_forget()
        radio_signout.pack_forget()
    else:
        # Re-pack them if not already visible
        try:
            if not action_label.winfo_ismapped():
                action_label.pack(anchor="w", pady=(6, 6))
                radio_signin.pack(anchor="w")
                radio_signout.pack(anchor="w")
        except Exception:
            pass

# Apply initial visibility based on loaded settings
toggle_action_radiobuttons()

# Action row
action_row = tk.Frame(root, bg=BG_MAIN if BG_MAIN else THEMES["Light"]["BG_MAIN"])
action_row.pack(fill="x", padx=24, pady=(6, 24))
enter_btn = tk.Button(action_row, text="Enter", font=tk_font_smedium, command=lambda: scan_id(),
                      bg="#1565C0", fg="white", bd=0, activebackground="#0B63C7", padx=18, pady=10)
enter_btn.pack(side="right")

# Footer
footer = tk.Frame(root, bg=BG_MAIN if BG_MAIN else THEMES["Light"]["BG_MAIN"])
footer.pack(fill="x", padx=24, pady=(0, 18))
footer_label = Label(footer, text="Tip: Press Esc to exit fullscreen.", font=tk_font_small, bg=BG_MAIN if BG_MAIN else THEMES["Light"]["BG_MAIN"], fg=FOOTER_TEXT if FOOTER_TEXT else THEMES["Light"]["FOOTER_TEXT"])
footer_label.pack(side="left", padx=6, pady=6)


_auth_ok = False       # True once the user has a valid Google OAuth token
_sheets_ready = False  # True once at least one real worksheet has loaded into the dropdown


def _apply_form_state():
    """Enable form inputs only when both signed in and sheets are ready."""
    enabled = _auth_ok and _sheets_ready
    state = "normal" if enabled else "disabled"
    id_entry.config(state=state)
    enter_btn.config(state=state)
    try:
        event_dropdown.config(state=state)
    except Exception:
        pass
    try:
        radio_signin.config(state=state)
        radio_signout.config(state=state)
    except Exception:
        pass


def set_ui_auth_state(signed_in: bool):
    """Show/hide the sign-in banner and update form state."""
    global _auth_ok
    _auth_ok = signed_in
    if signed_in:
        signin_banner.config(height=0)
        signin_banner_label.pack_forget()
    else:
        try:
            signin_banner_label.config(font=tk_font_small)
        except Exception:
            pass
        signin_banner.config(height=36)
        signin_banner_label.pack()
    _apply_form_state()


def set_ui_sheets_state(ready: bool):
    """Enable or disable form inputs based on whether sheets have loaded."""
    global _sheets_ready
    _sheets_ready = ready
    _apply_form_state()


def _set_dropdown_loading():
    """Put the event dropdown into a 'Loading sheets…' state and disable form inputs."""
    global eventsList
    eventsList = [LOADING_SHEETS_LABEL]
    set_ui_sheets_state(False)
    try:
        if event_dropdown is not None:
            menu = event_dropdown["menu"]
            menu.delete(0, "end")
            menu.add_command(label=LOADING_SHEETS_LABEL, command=tk._setit(event_var, LOADING_SHEETS_LABEL))
        event_var.set(LOADING_SHEETS_LABEL)
    except Exception:
        pass


def open_whos_here_window():
    """Open (or raise) the resizable scrollable 'Who's Here?' dialog.

    Shows all currently signed-in people from the local sign_ins dict,
    sortable by name or sign-in time.  Automatically signs out anyone
    who has been signed in for more than 12 hours and queues the
    resulting sign-out records for background Google push.  Polls for
    UI refresh every 60 seconds while open; supports a manual sheet
    refresh button that re-fetches live data from Google.

    If the window is already open, it is lifted to the front rather than
    opened again.
    """
    global whos_here_win, whos_here_after_id, whos_here_populate_func

    # If window already open, just lift it and return
    try:
        if whos_here_win is not None and whos_here_win.winfo_exists():
            whos_here_win.lift()
            return
    except Exception:
        whos_here_win = None

    win = Toplevel(root)
    whos_here_win = win
    win.title("Who's Here?")
    win.configure(bg=BG_MAIN if BG_MAIN else THEMES["Light"]["BG_MAIN"]) 
    win.focus_force()
    # Set initial size and allow resizing
    win.geometry("520x420")
    win.resizable(True, True)

    # Main container uses pack to fill window dynamically
    container = tk.Frame(win, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], bd=1, relief="solid")
    container.pack(fill="both", expand=True, padx=20, pady=20)
    try:
        container.configure(highlightbackground=CARD_BORDER if CARD_BORDER else THEMES["Light"]["CARD_BORDER"])
    except Exception:
        pass

    # Header label with scaled font
    def get_header_font():
        return font.Font(family="Poppins", size=max(10, int(28 * whos_here_scale)))
    
    header_label = Label(container, text="Currently Signed In:", bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=TEXT if TEXT else THEMES["Light"]["TEXT"], font=get_header_font())
    header_label.pack(pady=(12, 8))

    # Ordering dropdown for Who's Here
    order_var = StringVar(value="Most Recent")
    order_options = ["Alphabetical (A-Z)", "Alphabetical (Z-A)", "Most Recent", "Oldest"]
    try:
        order_menu = OptionMenu(container, order_var, *order_options)
        order_menu.config(font=tk_font_small)
        # place to the right of header_label visually
        order_menu.pack(pady=(0, 8))
        style_optionmenu(order_menu)
    except Exception:
        order_menu = None

    # Scrollable list area
    list_container = tk.Frame(container, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"])
    list_container.pack(fill="both", expand=True, padx=12, pady=(4, 8))

    canvas = tk.Canvas(list_container, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], bd=0, highlightthickness=0)
    scrollbar = tk.Scrollbar(list_container, orient="vertical", command=canvas.yview)
    scrollable_frame = tk.Frame(canvas, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"])

    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )

    canvas_window = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side="left", fill="both", expand=True)
    scrollbar.pack(side="right", fill="y")

    def populate():
        # Build fonts dynamically so changes to `whos_here_scale` take effect immediately
        wh_font_small = font.Font(family="Poppins", size=max(8, int(18 * whos_here_scale)))
        
        # Clear existing widgets
        for w in scrollable_frame.winfo_children():
            w.destroy()
        
        current = get_current_signins()
        
        # Check for and auto sign-out anyone signed in for 12+ hours
        now = datetime.now()
        names_to_remove = []
        for name, ts_str in list(current.items()):
            try:
                # Parse timestamp string like "03:45 PM, 2024-01-15"
                time_part, date_part = ts_str.split(", ")
                # Combine and parse
                datetime_str = f"{date_part} {time_part}"
                signin_time = datetime.strptime(datetime_str, "%Y-%m-%d %I:%M %p")
                
                # Calculate time difference
                time_diff = now - signin_time
                if time_diff.total_seconds() >= 12 * 3600:  # 12 hours in seconds
                    names_to_remove.append((name, signin_time))
                    current.pop(name, None)
            except Exception:
                # If parsing fails, skip this entry
                pass
        
        # Sign out anyone who exceeded 12 hours (queue for background push)
        for name, signin_time in names_to_remove:
            try:
                remove_sign_in(name)
                # Get the ID from the local cache
                current_id = get_id_by_name(name)
                
                if current_id:
                    current_time = now.strftime("%I:%M %p")
                    current_date = now.strftime("%Y-%m-%d")
                    full_date = f"Signed out at: {current_time}, Date: {current_date}"
                    auto_event = _first_active_worksheet_name()
                    if not auto_event:
                        continue
                    
                    # Queue auto sign-out for background push (no direct API call)
                    attendance_queue.put((
                        current_id, name, full_date, auto_event, "Didn't sign out",
                        "out", False, None, None, volunteeringList, get_effective_logging_fields()
                    ))
            except Exception:
                pass
        
        if not current:
            Label(scrollable_frame, text="No one is currently signed in.", bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=FOOTER_TEXT if FOOTER_TEXT else THEMES["Light"]["FOOTER_TEXT"], font=wh_font_small).pack(pady=8, padx=8)
            return
        
        # Adjust wraplength based on canvas width
        try:
            canvas.update_idletasks()
            avail_w = max(200, canvas.winfo_width() - 40)
        except Exception:
            avail_w = 400
        
        # Sort according to selected ordering
        items = list(current.items())

        def parse_ts(ts_str):
            try:
                time_part, date_part = ts_str.split(", ")
                datetime_str = f"{date_part} {time_part}"
                return datetime.strptime(datetime_str, "%Y-%m-%d %I:%M %p")
            except Exception:
                return None

        ordering = order_var.get() if 'order_var' in locals() else "Most Recent"
        if ordering == "Alphabetical (A-Z)":
            items.sort(key=lambda x: x[0].split()[0].lower())
        elif ordering == "Alphabetical (Z-A)":
            items.sort(key=lambda x: x[0].split()[0].lower(), reverse=True)
        elif ordering == "Oldest":
            items.sort(key=lambda x: (parse_ts(x[1]) or datetime.min))
        else:  # Most Recent (default)
            items.sort(key=lambda x: (parse_ts(x[1]) or datetime.min), reverse=True)

        for name, ts in items:
            Label(scrollable_frame, text=f"{name} — Signed in at {ts}", anchor="w", justify="left",
                  bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"],
                  fg=TEXT if TEXT else THEMES["Light"]["TEXT"],
                  font=wh_font_small, wraplength=avail_w).pack(fill="x", padx=8, pady=4)
        
        # Update header font as well
        header_label.config(font=get_header_font())
    
    # Store populate function globally for manual refresh
    whos_here_populate_func = populate

    def _poll():
        # refresh contents
        try:
            populate()
        except Exception:
            pass
        # schedule next poll if window still exists (60s interval)
        global whos_here_after_id
        try:
            if whos_here_win is not None and whos_here_win.winfo_exists():
                whos_here_after_id = root.after(60000, _poll)
            else:
                whos_here_after_id = None
        except Exception:
            whos_here_after_id = None

    def _cleanup_and_close():
        global whos_here_win, whos_here_after_id, whos_here_populate_func
        try:
            if whos_here_after_id is not None:
                root.after_cancel(whos_here_after_id)
        except Exception:
            pass
        whos_here_after_id = None
        try:
            if whos_here_win is not None and whos_here_win.winfo_exists():
                whos_here_win.destroy()
        except Exception:
            pass
        whos_here_win = None
        whos_here_populate_func = None

    # Button row at bottom
    try:
        wh_font_small_btn = font.Font(family="Poppins", size=max(8, int(18 * whos_here_scale)))
    except Exception:
        wh_font_small_btn = tk_font_small

    def refresh_from_sheets():
        """Re-scan Google Sheets in the background to rebuild sign_ins, then repopulate the list."""
        refresh_btn.config(state="disabled", text="Refreshing...")

        def _do_refresh():
            try:
                all_sheets = list_sheets()
                sheets_to_scan = _sync_sheet_metadata(all_sheets)
                loaded = fetch_whos_here_from_sheets(sheets_to_scan) if sheets_to_scan else {}
                # Merge: sheet data is authoritative — reset sign_ins from it
                sign_ins.clear()
                for pname, pts in loaded.items():
                    sign_ins[pname] = pts
                print(f"Refreshed Who's Here: {len(loaded)} people currently signed in.")
            except Exception as e:
                print(f"Error refreshing Who's Here from sheets: {e}")
            # Repopulate the UI on the main thread
            root.after(0, lambda: (populate(), refresh_btn.config(state="normal", text="Refresh")))

        threading.Thread(target=_do_refresh, daemon=True).start()

    btn_row = tk.Frame(container, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"]) 
    btn_row.pack(fill="x", pady=(6, 12), padx=12)
    refresh_btn = tk.Button(btn_row, text="Refresh", command=refresh_from_sheets, bg=ACCENT if ACCENT else THEMES["Light"]["ACCENT"], fg="white", bd=0, font=wh_font_small_btn, activebackground=ACCENT_DARK if ACCENT_DARK else THEMES["Light"]["ACCENT_DARK"], padx=12, pady=6)
    refresh_btn.pack(side="left")
    close_btn = tk.Button(btn_row, text="Close", command=_cleanup_and_close, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=TEXT if TEXT else THEMES["Light"]["TEXT"], bd=0, font=wh_font_small_btn, padx=12, pady=6)
    close_btn.pack(side="right")

    # Ensure cleanup when user closes the window via window manager
    win.protocol("WM_DELETE_WINDOW", _cleanup_and_close)

    # Debounced resize handling: adjust canvas window width and repopulate
    resize_after = None
    def _on_resize(event=None):
        nonlocal resize_after
        try:
            if resize_after is not None:
                root.after_cancel(resize_after)
        except Exception:
            pass
        def _do_resize():
            try:
                # Match canvas window width to canvas width
                canvas.update_idletasks()
                canvas.itemconfig(canvas_window, width=canvas.winfo_width())
                populate()
            except Exception:
                pass
        resize_after = root.after(150, _do_resize)
    
    win.bind('<Configure>', _on_resize)

    # initial populate and start polling
    populate()
    # start poll loop (60s interval)
    whos_here_after_id = root.after(60000, _poll)

# --------------------------
# Keyboardless Mode Functions
# --------------------------

def open_keyboardless_config_window():
    """Open the configuration window for setting up keyboardless mode bindings."""
    config_win = Toplevel(root)
    config_win.title("Keyboardless Mode Configuration")
    config_win.configure(bg=BG_MAIN if BG_MAIN else THEMES["Light"]["BG_MAIN"])
    config_win.focus_force()
    center_window(config_win, width=1800, height=700)

    # Outer card frame
    card = tk.Frame(config_win, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], bd=1, relief="solid")
    card.pack(fill="both", expand=True, padx=20, pady=20)
    try:
        card.configure(highlightbackground=CARD_BORDER if CARD_BORDER else THEMES["Light"]["CARD_BORDER"])
    except Exception:
        pass

    # Canvas for scrolling
    canvas = tk.Canvas(card, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], bd=0, highlightthickness=0)
    scrollbar = tk.Scrollbar(card, orient="vertical", command=canvas.yview)
    scrollable_frame = tk.Frame(canvas, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"])

    scrollable_frame.bind(
        "<Configure>",
        lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
    )

    window_id = canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
    canvas.configure(yscrollcommand=scrollbar.set)

    canvas.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=10)
    scrollbar.pack(side="right", fill="y", pady=10, padx=(0, 10))

    # When the config window is resized, ensure the embedded window width follows
    resize_after_config = None
    def _on_config_resize(event=None):
        nonlocal resize_after_config
        try:
            if resize_after_config is not None:
                root.after_cancel(resize_after_config)
        except Exception:
            pass
        def _do():
            try:
                canvas.itemconfig(window_id, width=canvas.winfo_width())
                canvas.configure(scrollregion=canvas.bbox("all"))
            except Exception:
                pass
        resize_after_config = root.after(120, _do)
    config_win.bind('<Configure>', _on_config_resize)

    # Title and instructions
    tk.Label(scrollable_frame, text="Configure Keyboardless Mode Bindings", 
             bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], 
             fg=TEXT if TEXT else THEMES["Light"]["TEXT"], 
             font=tk_font_medium).pack(anchor="w", padx=18, pady=(16, 4))
    
    tk.Label(scrollable_frame, text="Enter a unique 16-digit string for each action. These will be used with barcode scanners.", 
             bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], 
             fg=TEXT if TEXT else THEMES["Light"]["TEXT"], 
             font=tk_font_small, wraplength=700).pack(anchor="w", padx=18, pady=(0, 16))

    # Dictionary to hold entry widgets
    entry_widgets = {}
    
    # Binding configurations
    bindings_config = [
        ("sign_in", "Sign In Action"),
        ("sign_out", "Sign Out Action"),
        ("internship", "Select Internship"),
        ("build_season", "Select Build Season"),
        ("volunteering", "Select First Custom Sheet"),
        ("close_popup", "Close Any Popup/Dialog")
    ]
    
    for key, label in bindings_config:
        frame = tk.Frame(scrollable_frame, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"])
        frame.pack(fill="x", padx=18, pady=8)
        
        tk.Label(frame, text=f"{label}:", 
                bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], 
                fg=TEXT if TEXT else THEMES["Light"]["TEXT"], 
                font=tk_font_small).pack(anchor="w", pady=(0, 4))
        
        entry = Entry(frame, font=tk_font_small, bd=0, bg=INPUT_BG if INPUT_BG else THEMES["Light"]["INPUT_BG"])
        entry.pack(fill="x", pady=(0, 4), ipady=6)
        style_entry(entry)
        
        # Pre-fill with existing binding
        current_value = keyboardless_bindings.get(key, "")
        if current_value:
            entry.insert(0, current_value)
        
        entry_widgets[key] = entry

    # Buttons at bottom
    btn_frame = tk.Frame(card, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"])
    btn_frame.pack(fill="x", pady=(10, 10), padx=18)
    
    def save_and_enter_keyboardless():
        """Save bindings and enter keyboardless mode."""
        global keyboardless_bindings
        
        # Validate and save all bindings
        new_bindings = {}
        for key, entry in entry_widgets.items():
            value = entry.get().strip()
            if value and len(value) != 16:
                messagebox.showerror("Invalid Binding", 
                                   f"The binding for '{key}' must be exactly 16 characters long.",
                                   parent=config_win)
                return
            new_bindings[key] = value
        
        # Check for duplicates
        values = [v for v in new_bindings.values() if v]
        if len(values) != len(set(values)):
            messagebox.showerror("Duplicate Bindings", 
                               "Each binding must be unique. Please check for duplicates.",
                               parent=config_win)
            return
        
        # Save bindings
        keyboardless_bindings = new_bindings
        save_settings()
        
        config_win.destroy()
        enter_keyboardless_mode()
    
    def save_and_close():
        """Save bindings without entering keyboardless mode."""
        global keyboardless_bindings
        
        # Validate and save all bindings
        new_bindings = {}
        for key, entry in entry_widgets.items():
            value = entry.get().strip()
            if value and len(value) != 16:
                messagebox.showerror("Invalid Binding", 
                                   f"The binding for '{key}' must be exactly 16 characters long.",
                                   parent=config_win)
                return
            new_bindings[key] = value
        
        # Check for duplicates
        values = [v for v in new_bindings.values() if v]
        if len(values) != len(set(values)):
            messagebox.showerror("Duplicate Bindings", 
                               "Each binding must be unique. Please check for duplicates.",
                               parent=config_win)
            return
        
        # Save bindings
        keyboardless_bindings = new_bindings
        save_settings()
        
        config_win.destroy()
    
    enter_mode_btn = tk.Button(btn_frame, text="Save & Enter Keyboardless Mode", 
                              command=save_and_enter_keyboardless,
                              bg=ACCENT if ACCENT else THEMES["Light"]["ACCENT"], 
                              fg="white",
                              font=tk_font_small, bd=0, 
                              activebackground=ACCENT_DARK if ACCENT_DARK else THEMES["Light"]["ACCENT_DARK"], 
                              padx=12, pady=8)
    enter_mode_btn.pack(side="right")
    
    save_btn = tk.Button(btn_frame, text="Save", 
                        command=save_and_close,
                        bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], 
                        fg=TEXT if TEXT else THEMES["Light"]["TEXT"],
                        font=tk_font_small, bd=0, padx=12, pady=8)
    save_btn.pack(side="right", padx=(0, 8))
    
    close_btn = tk.Button(btn_frame, text="Cancel", 
                         command=lambda: config_win.destroy(),
                         bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], 
                         fg=TEXT if TEXT else THEMES["Light"]["TEXT"],
                         font=tk_font_small, bd=0, padx=12, pady=8)
    close_btn.pack(side="left")


def enter_keyboardless_mode():
    """Enter keyboardless mode where all actions are controlled by 16-digit strings."""
    global keyboardless_mode
    keyboardless_mode = True
    
    # Update footer label
    try:
        footer_label.config(text="Notice: Keyboardless mode is active. Press Ctrl+E to exit.")
    except Exception:
        pass
    
    # Bind Ctrl+E to exit keyboardless mode
    root.bind("<Control-e>", lambda e: exit_keyboardless_mode())
    
    # Force focus on ID entry and keep it focused
    id_entry.focus_force()
    
    # Set up keyboardless input handler
    def keyboardless_input_handler(event=None):
        """Handle input in keyboardless mode."""
        if not keyboardless_mode:
            return
        
        current_input = id_entry.get().strip()
        
        # Check if input matches any binding
        # Skip sign_in/sign_out bindings if easy_signin_mode is enabled
        if not easy_signin_mode:
            if current_input == keyboardless_bindings.get("sign_in"):
                action_var.set("in")
                id_entry.delete(0, tk.END)
                id_entry.focus_force()
                return
            elif current_input == keyboardless_bindings.get("sign_out"):
                action_var.set("out")
                id_entry.delete(0, tk.END)
                id_entry.focus_force()
                return
        
        # Process other bindings (these work regardless of easy_signin_mode)
        if current_input == keyboardless_bindings.get("internship"):
            target = _first_active_worksheet_name()
            if target:
                event_var.set(target)
            id_entry.delete(0, tk.END)
            id_entry.focus_force()
        elif current_input == keyboardless_bindings.get("build_season"):
            if "Build Season" in eventsList:
                event_var.set("Build Season")
            id_entry.delete(0, tk.END)
            id_entry.focus_force()
        elif current_input == keyboardless_bindings.get("volunteering"):
            volunteering_sheets = [s for s in eventsList if s not in ("Main Attendance", "Build Season", "IDs")]
            if volunteering_sheets:
                event_var.set(volunteering_sheets[0])
            id_entry.delete(0, tk.END)
            id_entry.focus_force()
        else:
            # If not a command, try to process as ID
            if len(current_input) == 6:
                try:
                    int(current_input)
                    scan_id()
                except ValueError:
                    id_entry.delete(0, tk.END)
                    id_entry.focus_force()
            elif len(current_input) >= 16:
                # Clear if too long and not a valid command
                id_entry.delete(0, tk.END)
                id_entry.focus_force()
    
    # Bind input handler to id_entry
    id_entry.bind("<KeyRelease>", keyboardless_input_handler)
    
    # Periodically refocus id_entry
    def refocus_id_entry():
        if keyboardless_mode:
            try:
                # Only refocus if no other toplevel window has focus
                if not any(isinstance(w, tk.Toplevel) and w.winfo_exists() for w in root.winfo_children()):
                    id_entry.focus_force()
            except Exception:
                pass
            root.after(100, refocus_id_entry)
    
    refocus_id_entry()


def exit_keyboardless_mode():
    """Exit keyboardless mode and restore normal operation."""
    global keyboardless_mode
    keyboardless_mode = False
    
    # Update footer label
    try:
        footer_label.config(text="Tip: Press Esc to exit fullscreen.")
    except Exception:
        pass
    
    # Unbind Ctrl+E
    root.unbind("<Control-e>")
    
    # Unbind keyboardless input handler
    id_entry.unbind("<KeyRelease>")




def open_options_window(initial_section: str = "app_behavior"):
    """Open the multi-section Options/Settings dialog.

    The dialog has a scrollable sidebar with four sections:
      - App Behavior: theme, UI scale, camera frequency/trigger, Easy Sign In.
      - Google Settings: sign-in/out, sheet create/connect.
      - Data Logging: field toggles, cutoff times, worksheet targets.
      - Keyboardless Mode: scanner binding configuration.

    All changes are applied and persisted to settings.json only when the
    user clicks "Apply".  "Reset Defaults" restores DEFAULT_SETTINGS values.
    Mouse-wheel scroll is routed to whichever panel the pointer is over.
    """
    opts = Toplevel(root)
    opts.title("Settings")
    opts.configure(bg=BG_MAIN if BG_MAIN else THEMES["Light"]["BG_MAIN"])
    opts.focus_force()
    try:
        opts.state("zoomed")
    except Exception:
        try:
            opts.attributes("-zoomed", True)
        except Exception:
            center_window(opts, width=1280, height=800)
    opts.minsize(900, 600)

    theme_defaults = THEMES["Light"]
    panel_bg = PANEL_BG if PANEL_BG else theme_defaults["PANEL_BG"]
    bg_main = BG_MAIN if BG_MAIN else theme_defaults["BG_MAIN"]
    text_color = TEXT if TEXT else theme_defaults["TEXT"]
    footer_text = FOOTER_TEXT if FOOTER_TEXT else theme_defaults["FOOTER_TEXT"]
    accent = ACCENT if ACCENT else theme_defaults["ACCENT"]
    accent_dark = ACCENT_DARK if ACCENT_DARK else theme_defaults["ACCENT_DARK"]
    card_border = CARD_BORDER if CARD_BORDER else theme_defaults["CARD_BORDER"]
    input_bg = INPUT_BG if INPUT_BG else theme_defaults["INPUT_BG"]
    positive = POSITIVE if POSITIVE else theme_defaults["POSITIVE"]
    negative = NEGATIVE if NEGATIVE else theme_defaults["NEGATIVE"]
    option_bg = OPTION_MENU_BG if OPTION_MENU_BG else theme_defaults["OPTION_MENU_BG"]
    option_fg = OPTION_MENU_FG if OPTION_MENU_FG else theme_defaults["OPTION_MENU_FG"]

    # Local state for all sections
    theme_var_local = StringVar(value=ui_theme)
    main_scale_var = tk.DoubleVar(value=main_ui_scale)
    whos_here_scale_var = tk.DoubleVar(value=whos_here_scale)
    camera_freq_var = tk.DoubleVar(value=camera_frequency)
    camera_trigger_var = tk.StringVar(value=camera_trigger)
    easy_signin_var = BooleanVar(value=easy_signin_mode)
    keyboardless_enabled_var = BooleanVar(value=keyboardless_mode)

    local_field_vars = {
        "name": BooleanVar(value=logging_field_toggles.get("name", True)),
        "timestamp": BooleanVar(value=logging_field_toggles.get("timestamp", True)),
        "image_link": BooleanVar(value=logging_field_toggles.get("image_link", True)),
        "image_path": BooleanVar(value=logging_field_toggles.get("image_path", True)),
        "reason": BooleanVar(value=logging_field_toggles.get("reason", True)),
    }
    late_cutoff_var = StringVar(value=late_signin_cutoff)
    early_cutoff_var = StringVar(value=early_signout_cutoff)
    worksheet_targets_local = list(worksheet_targets)
    if not worksheet_targets_local:
        worksheet_targets_local = [s for s in eventsList if s and s not in ("IDs", NO_ACTIVE_WORKSHEETS_LABEL)]

    keyboardless_binding_vars = {
        key: StringVar(value=keyboardless_bindings.get(key, ""))
        for key in DEFAULT_SETTINGS["keyboardless_bindings"].keys()
    }

    field_checkbuttons = {}
    keyboardless_binding_entries = {}
    keyboardless_binding_labels = []
    cutoff_toggle_vars = {}
    cutoff_toggle_checkbuttons = {}
    google_status_var = StringVar(value="")
    account_label_var = StringVar(value="Not signed in")
    data_logging_status_var = StringVar(value="")

    layout = tk.Frame(opts, bg=bg_main)
    layout.pack(fill="both", expand=True, padx=12, pady=12)

    sidebar_holder = tk.Frame(layout, bg=panel_bg, width=250, bd=1, relief="solid")
    sidebar_holder.pack(side="left", fill="y")
    sidebar_holder.pack_propagate(False)
    try:
        sidebar_holder.configure(highlightbackground=card_border)
    except Exception:
        pass

    divider = tk.Frame(layout, bg=card_border, width=1)
    divider.pack(side="left", fill="y", padx=(8, 8))

    content_holder = tk.Frame(layout, bg=panel_bg, bd=1, relief="solid")
    content_holder.pack(side="left", fill="both", expand=True)
    try:
        content_holder.configure(highlightbackground=card_border)
    except Exception:
        pass

    # Sidebar scrolling
    sidebar_canvas = tk.Canvas(sidebar_holder, bg=panel_bg, bd=0, highlightthickness=0)
    sidebar_scrollbar = tk.Scrollbar(sidebar_holder, orient="vertical", command=sidebar_canvas.yview)
    sidebar_inner = tk.Frame(sidebar_canvas, bg=panel_bg)
    sidebar_window_id = sidebar_canvas.create_window((0, 0), window=sidebar_inner, anchor="nw")
    sidebar_canvas.configure(yscrollcommand=sidebar_scrollbar.set)
    sidebar_canvas.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)
    sidebar_scrollbar.pack(side="right", fill="y", pady=8, padx=(0, 8))

    # Content scrolling
    content_scroll_container = tk.Frame(content_holder, bg=panel_bg)
    content_scroll_container.pack(fill="both", expand=True, padx=8, pady=(8, 0))
    content_canvas = tk.Canvas(content_scroll_container, bg=panel_bg, bd=0, highlightthickness=0)
    content_scrollbar = tk.Scrollbar(content_scroll_container, orient="vertical", command=content_canvas.yview)
    content_inner = tk.Frame(content_canvas, bg=panel_bg)
    content_window_id = content_canvas.create_window((0, 0), window=content_inner, anchor="nw")
    content_canvas.configure(yscrollcommand=content_scrollbar.set)
    content_canvas.pack(side="left", fill="both", expand=True, padx=(4, 0), pady=(4, 6))
    content_scrollbar.pack(side="right", fill="y", pady=(4, 6), padx=(0, 4))

    btn_frame = tk.Frame(content_holder, bg=panel_bg)
    btn_frame.pack(fill="x", padx=18, pady=(0, 10))

    def _refresh_sidebar_scroll_region(event=None):
        try:
            sidebar_canvas.configure(scrollregion=sidebar_canvas.bbox("all"))
            sidebar_canvas.itemconfig(sidebar_window_id, width=sidebar_canvas.winfo_width())
        except Exception:
            pass

    def _refresh_content_scroll_region(event=None):
        try:
            content_canvas.configure(scrollregion=content_canvas.bbox("all"))
            content_canvas.itemconfig(content_window_id, width=content_canvas.winfo_width())
        except Exception:
            pass

    sidebar_inner.bind("<Configure>", _refresh_sidebar_scroll_region)
    content_inner.bind("<Configure>", _refresh_content_scroll_region)

    resize_after_opts = None
    def _on_opts_resize(event=None):
        nonlocal resize_after_opts
        try:
            if resize_after_opts is not None:
                root.after_cancel(resize_after_opts)
        except Exception:
            pass

        def _do_resize():
            _refresh_sidebar_scroll_region()
            _refresh_content_scroll_region()

        resize_after_opts = root.after(100, _do_resize)

    opts.bind("<Configure>", _on_opts_resize)

    # Mouse wheel routing so each panel scrolls independently from hover location.
    def _is_descendant(widget, ancestor):
        while widget is not None:
            if widget == ancestor:
                return True
            widget = getattr(widget, "master", None)
        return False

    def _route_scroll(direction_units, event):
        target = opts.winfo_containing(event.x_root, event.y_root)
        if target is None:
            return
        if _is_descendant(target, sidebar_holder):
            sidebar_canvas.yview_scroll(direction_units, "units")
        elif _is_descendant(target, content_holder):
            content_canvas.yview_scroll(direction_units, "units")

    def _on_mousewheel(event):
        delta = int(-1 * (event.delta / 120)) if event.delta else 0
        if delta != 0:
            _route_scroll(delta, event)
            return "break"
        return None

    def _on_linux_scroll(event):
        if event.num == 4:
            _route_scroll(-1, event)
            return "break"
        if event.num == 5:
            _route_scroll(1, event)
            return "break"
        return None

    opts.bind_all("<MouseWheel>", _on_mousewheel)
    opts.bind_all("<Button-4>", _on_linux_scroll)
    opts.bind_all("<Button-5>", _on_linux_scroll)

    # ------- Shared section helpers -------
    def _style_optionmenu_local(optmenu):
        try:
            optmenu.configure(
                font=tk_font_small,
                bg=option_bg,
                fg=option_fg,
                activebackground=option_bg,
                activeforeground=option_fg,
                bd=0,
                relief="flat",
                highlightthickness=1,
                highlightbackground=card_border
            )
            optmenu["menu"].configure(
                bg=option_bg,
                fg=option_fg,
                activebackground=accent_dark,
                activeforeground=option_fg,
                bd=0,
                font=tk_font_small
            )
        except Exception:
            pass

    def _style_card(frame):
        try:
            frame.configure(highlightbackground=card_border)
        except Exception:
            pass

    # ------- Section builders -------
    sections = {
        "app_behavior": tk.Frame(content_inner, bg=panel_bg),
        "google_settings": tk.Frame(content_inner, bg=panel_bg),
        "data_logging": tk.Frame(content_inner, bg=panel_bg),
        "keyboardless_mode": tk.Frame(content_inner, bg=panel_bg),
    }

    # App Behavior
    app_frame = sections["app_behavior"]
    tk.Label(app_frame, text="App Behavior", bg=panel_bg, fg=text_color, font=tk_font_medium, wraplength=900).pack(anchor="w", padx=18, pady=(14, 4))

    tk.Label(app_frame, text="Theme:", bg=panel_bg, fg=text_color, font=tk_font_small).pack(anchor="w", padx=18, pady=(8, 4))
    theme_menu = OptionMenu(app_frame, theme_var_local, "Light", "Dark", "Black & Gold")
    _style_optionmenu_local(theme_menu)
    theme_menu.pack(anchor="w", padx=18, pady=(0, 12))

    tk.Label(app_frame, text="Main UI Scale (0.5x - 2.0x):", bg=panel_bg, fg=text_color, font=tk_font_small, wraplength=500).pack(anchor="w", padx=18, pady=(6, 4))
    main_scale_label = tk.Label(app_frame, text=f"{main_ui_scale:.2f}x", bg=panel_bg, fg=text_color, font=tk_font_small)
    main_scale_label.pack(anchor="w", padx=18)

    def update_main_scale_label(val):
        main_scale_label.config(text=f"{float(val):.2f}x")

    main_scale_slider = tk.Scale(
        app_frame,
        from_=0.5,
        to=2.0,
        resolution=0.1,
        orient="horizontal",
        variable=main_scale_var,
        command=update_main_scale_label,
        bg=panel_bg,
        fg=text_color,
        highlightthickness=0,
        troughcolor=accent
    )
    main_scale_slider.pack(fill="x", padx=18, pady=(0, 10))

    tk.Label(app_frame, text="Who's Here Scale (0.5x - 2.0x):", bg=panel_bg, fg=text_color, font=tk_font_small, wraplength=500).pack(anchor="w", padx=18, pady=(6, 4))
    whos_here_scale_label = tk.Label(app_frame, text=f"{whos_here_scale:.2f}x", bg=panel_bg, fg=text_color, font=tk_font_small)
    whos_here_scale_label.pack(anchor="w", padx=18)

    def update_whos_here_scale_label(val):
        whos_here_scale_label.config(text=f"{float(val):.2f}x")

    whos_here_scale_slider = tk.Scale(
        app_frame,
        from_=0.5,
        to=2.0,
        resolution=0.1,
        orient="horizontal",
        variable=whos_here_scale_var,
        command=update_whos_here_scale_label,
        bg=panel_bg,
        fg=text_color,
        highlightthickness=0,
        troughcolor=accent
    )
    whos_here_scale_slider.pack(fill="x", padx=18, pady=(0, 10))

    tk.Label(app_frame, text="Camera Frequency (1/20 - 1.0):", bg=panel_bg, fg=text_color, font=tk_font_small, wraplength=500).pack(anchor="w", padx=18, pady=(6, 4))
    camera_freq_label = tk.Label(app_frame, text="", bg=panel_bg, fg=text_color, font=tk_font_small)
    camera_freq_label.pack(anchor="w", padx=18)

    def update_camera_freq_label(val):
        try:
            v = float(val)
            denom = int(round(1.0 / v)) if v > 0 else 999
            denom = max(1, min(999, denom))
            camera_freq_label.config(text=f"Every 1 in {denom} (p={v:.2f})")
        except Exception:
            camera_freq_label.config(text=str(val))

    update_camera_freq_label(camera_freq_var.get())

    camera_freq_slider = tk.Scale(
        app_frame,
        from_=0.05,
        to=1.0,
        resolution=0.05,
        orient="horizontal",
        variable=camera_freq_var,
        command=update_camera_freq_label,
        bg=panel_bg,
        fg=text_color,
        highlightthickness=0,
        troughcolor=accent
    )
    camera_freq_slider.pack(fill="x", padx=18, pady=(0, 10))

    tk.Label(app_frame, text="Camera Trigger:", bg=panel_bg, fg=text_color, font=tk_font_small).pack(anchor="w", padx=18, pady=(6, 4))
    trigger_frame = tk.Frame(app_frame, bg=panel_bg)
    trigger_frame.pack(anchor="w", padx=18, pady=(0, 10))
    tk.Radiobutton(trigger_frame, text="Sign In", variable=camera_trigger_var, value="in", bg=panel_bg, fg=text_color, font=tk_font_small, selectcolor=panel_bg).pack(side="left", padx=(0, 8))
    tk.Radiobutton(trigger_frame, text="Sign Out", variable=camera_trigger_var, value="out", bg=panel_bg, fg=text_color, font=tk_font_small, selectcolor=panel_bg).pack(side="left", padx=(0, 8))
    tk.Radiobutton(trigger_frame, text="Both", variable=camera_trigger_var, value="both", bg=panel_bg, fg=text_color, font=tk_font_small, selectcolor=panel_bg).pack(side="left")
    tk.Radiobutton(trigger_frame, text="Never", variable=camera_trigger_var, value="never", bg=panel_bg, fg=text_color, font=tk_font_small, selectcolor=panel_bg).pack(side="left", padx=(8, 0))

    tk.Label(app_frame, text="Easy Sign In Mode:", bg=panel_bg, fg=text_color, font=tk_font_small).pack(anchor="w", padx=18, pady=(14, 4))
    tk.Label(
        app_frame,
        text="Automatically determines sign in/out based on your last action.",
        bg=panel_bg,
        fg=footer_text,
        font=tk_font_small,
        wraplength=900,
        justify="left"
    ).pack(anchor="w", padx=18, pady=(0, 6))
    tk.Checkbutton(
        app_frame,
        text="Enable Easy Sign In Mode",
        variable=easy_signin_var,
        bg=panel_bg,
        fg=text_color,
        font=tk_font_small,
        selectcolor=panel_bg
    ).pack(anchor="w", padx=18, pady=(0, 12))

    # Google Settings
    google_frame = sections["google_settings"]
    tk.Label(google_frame, text="Google Settings", bg=panel_bg, fg=text_color, font=tk_font_medium, wraplength=900).pack(anchor="w", padx=18, pady=(14, 4))

    account_card = tk.Frame(google_frame, bg=panel_bg, bd=1, relief="solid")
    account_card.pack(fill="x", padx=18, pady=(8, 10))
    _style_card(account_card)

    tk.Label(account_card, text="Authenticated Google Account", bg=panel_bg, fg=text_color, font=tk_font_small).pack(anchor="w", padx=12, pady=(10, 4))
    account_value_label = tk.Label(account_card, textvariable=account_label_var, bg=panel_bg, fg=footer_text, font=tk_font_small)
    account_value_label.pack(anchor="w", padx=12, pady=(0, 8))

    def refresh_account_display():
        """Update account label and show the correct Sign In / Sign Out button."""
        if is_signed_in():
            sign_out_btn.pack(anchor="w", padx=12, pady=(0, 12))
            sign_in_btn.pack_forget()
            account_label_var.set("Loading…")
            def _fetch():
                email = get_user_email()
                display = email if (email and email != "Unknown") else "Signed in (email unavailable)"
                root.after(0, lambda: account_label_var.set(display))
            threading.Thread(target=_fetch, daemon=True).start()
        else:
            sign_in_btn.pack(anchor="w", padx=12, pady=(0, 12))
            sign_out_btn.pack_forget()
            account_label_var.set("Not signed in")

    def handle_sign_in():
        sign_in_btn.config(state="disabled")
        google_status_var.set("Opening browser for sign-in… Complete sign-in in your browser.")
        google_status_label.configure(fg=text_color)

        def _worker():
            try:
                sign_in()
                root.after(0, _on_success)
            except Exception as e:
                root.after(0, lambda err=str(e): _on_fail(err))

        def _on_success():
            refresh_account_display()
            google_status_var.set("Signed in successfully! Reconnecting to Google…")
            google_status_label.configure(fg=positive)
            sign_in_btn.config(state="normal")
            set_ui_auth_state(True)
            threading.Thread(target=initialize_google_connection, daemon=True).start()

        def _on_fail(_err):
            google_status_var.set("Sign-in was cancelled or failed. Try again.")
            google_status_label.configure(fg=negative)
            sign_in_btn.config(state="normal")

        threading.Thread(target=_worker, daemon=True).start()

    def handle_sign_out():
        try:
            if not messagebox.askyesno("Sign Out", "Sign out of the current Google account on this device?", parent=opts):
                return
        except Exception:
            return
        stop_background_sync()
        sign_out()
        refresh_account_display()
        google_status_var.set("Signed out. Sign in again via the button above to restore access.")
        google_status_label.configure(fg=positive)
        set_ui_auth_state(False)

    sign_in_btn = tk.Button(
        account_card,
        text="Sign In with Google",
        command=handle_sign_in,
        bg=accent,
        fg="white",
        font=tk_font_small,
        bd=0,
        activebackground=accent_dark,
        padx=12,
        pady=8,
    )
    sign_out_btn = tk.Button(
        account_card,
        text="Sign Out",
        command=handle_sign_out,
        bg=accent,
        fg="white",
        font=tk_font_small,
        bd=0,
        activebackground=accent_dark,
        padx=12,
        pady=8,
    )
    # Set initial button visibility
    refresh_account_display()

    current_sheet_var = StringVar(value=sheet_id if sheet_id else "(none)")
    google_status_label = tk.Label(google_frame, textvariable=google_status_var, bg=panel_bg, fg=footer_text, font=tk_font_small, wraplength=920, justify="left")

    sheet_card = tk.Frame(google_frame, bg=panel_bg, bd=1, relief="solid")
    sheet_card.pack(fill="x", padx=18, pady=(0, 8))
    _style_card(sheet_card)

    tk.Label(sheet_card, text="Sheets Config", bg=panel_bg, fg=text_color, font=tk_font_small).pack(anchor="w", padx=12, pady=(10, 6))
    tk.Label(sheet_card, textvariable=current_sheet_var, bg=panel_bg, fg=footer_text, font=tk_font_small).pack(anchor="w", padx=12, pady=(0, 10))

    combined_sheet_card = tk.Frame(sheet_card, bg=panel_bg)
    combined_sheet_card.pack(fill="x", padx=12, pady=(0, 12))
    tk.Label(combined_sheet_card, text="Sheet ID", bg=panel_bg, fg=text_color, font=tk_font_small).pack(anchor="w")
    tk.Label(combined_sheet_card, text="Paste the Sheet ID to link an existing sheet, or enter a name to create a new one.", bg=panel_bg, fg=footer_text, font=tk_font_small, wraplength=560, justify="left").pack(anchor="w", pady=(0, 2))
    tk.Label(combined_sheet_card, text="Find the Sheet ID in the URL:  docs.google.com/spreadsheets/d/  [SHEET-ID-HERE]  /edit", bg=panel_bg, fg=footer_text, font=tk_font_small, wraplength=560, justify="left").pack(anchor="w", pady=(0, 6))
    combined_entry = Entry(combined_sheet_card, font=tk_font_small, bd=0, bg=input_bg, justify="center")
    combined_entry.pack(fill="x", pady=(0, 6), ipady=8)
    style_entry(combined_entry)
    if sheet_id:
        combined_entry.insert(0, sheet_id)
    else:
        combined_entry.insert(0, "Attendance Sheet")

    # Aliases so the handler functions below reference the same widget
    new_sheet_entry = combined_entry
    existing_sheet_entry = combined_entry

    def _set_google_status(msg, color):
        google_status_var.set(msg)
        google_status_label.configure(fg=color)

    def _on_sheet_connected(connected_id, created=False):
        global sheet_id
        sheet_id = connected_id
        set_default_doc(sheet_id)
        save_settings()
        current_sheet_var.set(f"Current sheet ID:  {sheet_id}")
        existing_sheet_entry.delete(0, tk.END)
        existing_sheet_entry.insert(0, sheet_id)
        if created:
            _set_google_status(f"Sheet created! ID: {sheet_id}", positive)
        else:
            _set_google_status(f"Connected successfully.", positive)
        threading.Thread(target=initialize_google_connection, daemon=True).start()
        queue_local_sheet_refresh()

    def create_new_sheet_inline():
        name = new_sheet_entry.get().strip()
        if not name:
            _set_google_status("Please enter a name for the new sheet.", negative)
            return

        _set_google_status("Creating sheet, please wait...", text_color)

        def _worker():
            try:
                created_name = create_attendance_spreadsheet(name)
                root.after(0, lambda: _on_sheet_connected(created_name, created=True))
            except Exception as e:
                root.after(0, lambda err=str(e): _set_google_status(f"Failed to create sheet.\n{err}", negative))

        threading.Thread(target=_worker, daemon=True).start()

    def connect_existing_sheet_inline():
        entered_id = existing_sheet_entry.get().strip()
        if not entered_id:
            _set_google_status("Please enter a Sheet ID.", negative)
            return

        _set_google_status("Verifying access...", text_color)

        def _worker():
            try:
                set_default_doc(entered_id)
                setup_google_sheet(entered_id)
                root.after(0, lambda: _on_sheet_connected(entered_id, created=False))
            except Exception as e:
                root.after(0, lambda err=str(e): _set_google_status(f"Could not open that sheet. Check that the ID is correct.\n{err}", negative))

        threading.Thread(target=_worker, daemon=True).start()

    google_btn_row = tk.Frame(combined_sheet_card, bg=panel_bg)
    google_btn_row.pack(fill="x")
    tk.Button(google_btn_row, text="Link Sheet", command=connect_existing_sheet_inline, bg=accent, fg="white", font=tk_font_small, bd=0, activebackground=accent_dark, padx=12, pady=8).pack(side="left")
    tk.Button(google_btn_row, text="Create Sheet", command=create_new_sheet_inline, bg=accent, fg="white", font=tk_font_small, bd=0, activebackground=accent_dark, padx=12, pady=8).pack(side="left", padx=(8, 0))
    google_status_label.pack(anchor="w", padx=18, pady=(0, 10))

    # Data Logging
    data_frame = sections["data_logging"]
    tk.Label(data_frame, text="Data Logging", bg=panel_bg, fg=text_color, font=tk_font_medium, wraplength=900).pack(anchor="w", padx=18, pady=(14, 4))
    tk.Label(
        data_frame,
        text="Choose which fields are logged and how worksheet targets are prioritized in the main dropdown.",
        bg=panel_bg,
        fg=footer_text,
        font=tk_font_small,
        wraplength=900,
        justify="left"
    ).pack(anchor="w", padx=18, pady=(0, 8))

    tk.Label(data_frame, text="Field Toggles", bg=panel_bg, fg=text_color, font=tk_font_small).pack(anchor="w", padx=18, pady=(4, 4))
    fields_card = tk.Frame(data_frame, bg=panel_bg, bd=1, relief="solid")
    fields_card.pack(fill="x", padx=18, pady=(0, 10))
    _style_card(fields_card)

    id_row = tk.Frame(fields_card, bg=panel_bg)
    id_row.pack(fill="x", padx=10, pady=(8, 4))
    tk.Label(id_row, text="ID", bg=panel_bg, fg=text_color, font=tk_font_small).pack(side="left")
    tk.Label(id_row, text="Always enabled", bg=panel_bg, fg=footer_text, font=tk_font_small).pack(side="right")

    field_labels = {
        "name": "Name",
        "timestamp": "Timestamp",
        "image_link": "Image Link",
        "image_path": "Image Path",
        "reason": "Reason",
    }
    for key in ("name", "timestamp", "image_link", "image_path", "reason"):
        cb = Checkbutton(
            fields_card,
            text=field_labels[key],
            variable=local_field_vars[key],
            bg=panel_bg,
            fg=text_color,
            font=tk_font_small,
            selectcolor=panel_bg
        )
        cb.pack(anchor="w", padx=10, pady=2)
        field_checkbuttons[key] = cb

    tk.Label(data_frame, text="Main Attendance Cutoff Times (24h HH:MM)", bg=panel_bg, fg=text_color, font=tk_font_small, wraplength=500).pack(anchor="w", padx=18, pady=(8, 4))
    cutoff_card = tk.Frame(data_frame, bg=panel_bg, bd=1, relief="solid")
    cutoff_card.pack(fill="x", padx=18, pady=(0, 10))
    _style_card(cutoff_card)

    late_row = tk.Frame(cutoff_card, bg=panel_bg)
    late_row.pack(fill="x", padx=10, pady=(8, 4))
    tk.Label(late_row, text="Late Sign-In After:", bg=panel_bg, fg=text_color, font=tk_font_small).pack(side="left")
    late_cutoff_entry = Entry(late_row, textvariable=late_cutoff_var, width=8, font=tk_font_small, bd=0, bg=input_bg, justify="center")
    late_cutoff_entry.pack(side="right", padx=(8, 0), ipady=4)
    style_entry(late_cutoff_entry)

    early_row = tk.Frame(cutoff_card, bg=panel_bg)
    early_row.pack(fill="x", padx=10, pady=(4, 8))
    tk.Label(early_row, text="Early Sign-Out Before:", bg=panel_bg, fg=text_color, font=tk_font_small).pack(side="left")
    early_cutoff_entry = Entry(early_row, textvariable=early_cutoff_var, width=8, font=tk_font_small, bd=0, bg=input_bg, justify="center")
    early_cutoff_entry.pack(side="right", padx=(8, 0), ipady=4)
    style_entry(early_cutoff_entry)

    tk.Label(data_frame, text="Enable Cutoff Times By Worksheet", bg=panel_bg, fg=text_color, font=tk_font_small, wraplength=500).pack(anchor="w", padx=18, pady=(0, 4))
    cutoff_toggle_card = tk.Frame(data_frame, bg=panel_bg, bd=1, relief="solid")
    cutoff_toggle_card.pack(fill="x", padx=18, pady=(0, 10))
    _style_card(cutoff_toggle_card)
    tk.Label(
        cutoff_toggle_card,
        text="When enabled for a worksheet, late sign-ins and early sign-outs use the cutoff prompts.",
        bg=panel_bg,
        fg=footer_text,
        font=tk_font_small,
        wraplength=900,
        justify="left"
    ).pack(anchor="w", padx=10, pady=(8, 6))
    cutoff_toggle_rows = tk.Frame(cutoff_toggle_card, bg=panel_bg)
    cutoff_toggle_rows.pack(fill="x", padx=8, pady=(0, 8))

    tk.Label(data_frame, text="Worksheet Targets (ordered)", bg=panel_bg, fg=text_color, font=tk_font_small, wraplength=500).pack(anchor="w", padx=18, pady=(8, 4))
    ws_card = tk.Frame(data_frame, bg=panel_bg, bd=1, relief="solid")
    ws_card.pack(fill="x", padx=18, pady=(0, 8))
    _style_card(ws_card)
    tk.Label(ws_card, text="First item is the default dropdown option.", bg=panel_bg, fg=footer_text, font=tk_font_small, wraplength=500).pack(anchor="w", padx=10, pady=(8, 6))

    ws_rows_container = tk.Frame(ws_card, bg=panel_bg)
    ws_rows_container.pack(fill="x", padx=8, pady=(0, 8))

    add_ws_row = tk.Frame(data_frame, bg=panel_bg)
    add_ws_row.pack(fill="x", padx=18, pady=(0, 8))
    add_ws_name_var = StringVar(value="")
    add_ws_entry = Entry(add_ws_row, textvariable=add_ws_name_var, font=tk_font_small, bd=0, bg=input_bg)
    add_ws_entry.pack(side="left", fill="x", expand=True, ipady=6)
    style_entry(add_ws_entry)

    data_logging_status_label = tk.Label(data_frame, textvariable=data_logging_status_var, bg=panel_bg, fg=footer_text, font=tk_font_small, wraplength=900, justify="left")
    data_logging_status_label.pack(anchor="w", padx=18, pady=(0, 8))

    def get_loaded_worksheet_names_for_cutoffs():
        try:
            loaded = [s for s in list_sheets() if s and s != "IDs"]
            if loaded:
                return loaded
        except Exception:
            pass
        return [s for s in eventsList if s and s not in ("IDs", NO_ACTIVE_WORKSHEETS_LABEL)]

    def render_cutoff_toggle_rows():
        loaded_worksheets = get_loaded_worksheet_names_for_cutoffs()

        for ws_name in list(cutoff_toggle_vars.keys()):
            if ws_name not in loaded_worksheets:
                cutoff_toggle_vars.pop(ws_name, None)

        for ws_name in loaded_worksheets:
            if ws_name not in cutoff_toggle_vars:
                default_enabled = bool(worksheet_cutoff_toggles.get(ws_name, ws_name == "Main Attendance"))
                cutoff_toggle_vars[ws_name] = BooleanVar(value=default_enabled)

        for child in cutoff_toggle_rows.winfo_children():
            child.destroy()
        cutoff_toggle_checkbuttons.clear()

        if not loaded_worksheets:
            tk.Label(cutoff_toggle_rows, text="No active worksheets available.", bg=panel_bg, fg=footer_text, font=tk_font_small).pack(anchor="w", padx=4, pady=4)
            return

        for ws_name in loaded_worksheets:
            cb = Checkbutton(
                cutoff_toggle_rows,
                text=ws_name,
                variable=cutoff_toggle_vars[ws_name],
                bg=panel_bg,
                fg=text_color,
                font=tk_font_small,
                selectcolor=panel_bg
            )
            cb.pack(anchor="w", padx=4, pady=2)
            cutoff_toggle_checkbuttons[ws_name] = cb

    def update_image_field_toggle_state(*args):
        master_off = camera_trigger_var.get() == "never"
        for key in ("image_link", "image_path"):
            cb = field_checkbuttons.get(key)
            if cb is None:
                continue
            if master_off:
                local_field_vars[key].set(False)
                cb.configure(state="disabled", fg=footer_text)
            else:
                cb.configure(state="normal", fg=text_color)

    def update_cutoff_controls_state(*args):
        reason_enabled = bool(local_field_vars.get("reason").get())

        if reason_enabled:
            late_cutoff_entry.configure(state="normal")
            early_cutoff_entry.configure(state="normal")
        else:
            late_cutoff_entry.configure(state="disabled")
            early_cutoff_entry.configure(state="disabled")

        for ws_name, cb in cutoff_toggle_checkbuttons.items():
            if reason_enabled:
                cb.configure(state="normal", fg=text_color)
            else:
                cb.configure(state="disabled", fg=footer_text)

    def persist_local_worksheet_targets(show_refresh=False):
        global worksheet_targets
        worksheet_targets = _sanitize_worksheet_targets(worksheet_targets_local)
        save_settings()
        try:
            current_sheets = list_sheets()
            _sync_sheet_metadata(current_sheets)
            if show_refresh:
                data_logging_status_var.set("Worksheet targets saved and dropdown order refreshed.")
                data_logging_status_label.configure(fg=positive)
        except Exception:
            if show_refresh:
                data_logging_status_var.set("Worksheet targets saved. Dropdown will refresh after reconnection.")
                data_logging_status_label.configure(fg=footer_text)

    def render_worksheet_targets():
        for child in ws_rows_container.winfo_children():
            child.destroy()

        if not worksheet_targets_local:
            tk.Label(ws_rows_container, text="No worksheet targets configured.", bg=panel_bg, fg=footer_text, font=tk_font_small).pack(anchor="w", padx=4, pady=4)
            return

        for idx, ws_name in enumerate(worksheet_targets_local):
            row = tk.Frame(ws_rows_container, bg=panel_bg)
            row.pack(fill="x", pady=2)

            prefix = "Default" if idx == 0 else f"Priority {idx + 1}"
            tk.Label(row, text=f"{prefix}: {ws_name}", bg=panel_bg, fg=text_color, font=tk_font_small).pack(side="left", padx=(4, 8))

            def _move_up(i=idx):
                if i <= 0:
                    return
                worksheet_targets_local[i - 1], worksheet_targets_local[i] = worksheet_targets_local[i], worksheet_targets_local[i - 1]
                render_worksheet_targets()
                persist_local_worksheet_targets(show_refresh=True)

            def _move_down(i=idx):
                if i >= len(worksheet_targets_local) - 1:
                    return
                worksheet_targets_local[i + 1], worksheet_targets_local[i] = worksheet_targets_local[i], worksheet_targets_local[i + 1]
                render_worksheet_targets()
                persist_local_worksheet_targets(show_refresh=True)

            def _remove(i=idx):
                worksheet_targets_local.pop(i)
                render_worksheet_targets()
                persist_local_worksheet_targets(show_refresh=True)

            tk.Button(row, text="Up", command=_move_up, bg=panel_bg, fg=text_color, font=tk_font_small, bd=0, padx=8, pady=2).pack(side="right")
            tk.Button(row, text="Down", command=_move_down, bg=panel_bg, fg=text_color, font=tk_font_small, bd=0, padx=8, pady=2).pack(side="right")
            tk.Button(row, text="Remove", command=_remove, bg=panel_bg, fg=text_color, font=tk_font_small, bd=0, padx=8, pady=2).pack(side="right", padx=(0, 6))

    def _apply_created_worksheet(new_title):
        if new_title not in worksheet_targets_local:
            worksheet_targets_local.append(new_title)
        if new_title not in cutoff_toggle_vars:
            cutoff_toggle_vars[new_title] = BooleanVar(value=False)
        render_cutoff_toggle_rows()
        render_worksheet_targets()
        persist_local_worksheet_targets(show_refresh=True)
        data_logging_status_var.set(f"Added worksheet '{new_title}' to targets.")
        data_logging_status_label.configure(fg=positive)

    def create_or_add_worksheet_inline():
        ws_name = add_ws_name_var.get().strip()
        if not ws_name:
            data_logging_status_var.set("Worksheet name cannot be empty.")
            data_logging_status_label.configure(fg=negative)
            return
        if ws_name in worksheet_targets_local:
            data_logging_status_var.set("That worksheet is already in your target list.")
            data_logging_status_label.configure(fg=negative)
            return
        if not get_default_doc():
            data_logging_status_var.set("Connect a Google Sheet first in Google Settings.")
            data_logging_status_label.configure(fg=negative)
            return

        data_logging_status_var.set("Creating worksheet...")
        data_logging_status_label.configure(fg=text_color)

        def _worker():
            try:
                created = create_worksheet_tab(ws_name)
                root.after(0, lambda: _on_success(created.title))
            except Exception as e:
                root.after(0, lambda err=str(e): _on_fail(err))

        def _on_success(title):
            add_ws_name_var.set("")
            _apply_created_worksheet(title)

        def _on_fail(err):
            data_logging_status_var.set(err)
            data_logging_status_label.configure(fg=negative)

        threading.Thread(target=_worker, daemon=True).start()

    tk.Button(add_ws_row, text="Create / Add Worksheet", command=create_or_add_worksheet_inline, bg=accent, fg="white", font=tk_font_small, bd=0, activebackground=accent_dark, padx=14, pady=8).pack(side="left", padx=(8, 0))

    render_cutoff_toggle_rows()
    render_worksheet_targets()
    update_image_field_toggle_state()
    update_cutoff_controls_state()

    # Keyboardless Mode
    keyboardless_frame = sections["keyboardless_mode"]
    tk.Label(keyboardless_frame, text="Keyboardless Mode", bg=panel_bg, fg=text_color, font=tk_font_medium, wraplength=900).pack(anchor="w", padx=18, pady=(14, 4))
    tk.Label(
        keyboardless_frame,
        text="Use scanner-friendly 16-character bindings for actions.",
        bg=panel_bg,
        fg=footer_text,
        font=tk_font_small,
        wraplength=900,
        justify="left"
    ).pack(anchor="w", padx=18, pady=(0, 10))

    keyboardless_master_cb = Checkbutton(
        keyboardless_frame,
        text="Enable Keyboardless Mode",
        variable=keyboardless_enabled_var,
        bg=panel_bg,
        fg=text_color,
        font=tk_font_small,
        selectcolor=panel_bg
    )
    keyboardless_master_cb.pack(anchor="w", padx=18, pady=(0, 6))

    tk.Label(
        keyboardless_frame,
        text="When disabled, all keyboardless bindings and scanner command handling are turned off.",
        bg=panel_bg,
        fg=footer_text,
        font=tk_font_small,
        wraplength=900,
        justify="left"
    ).pack(anchor="w", padx=18, pady=(0, 10))

    kb_card = tk.Frame(keyboardless_frame, bg=panel_bg, bd=1, relief="solid")
    kb_card.pack(fill="x", padx=18, pady=(0, 10))
    _style_card(kb_card)

    bindings_config = [
        ("sign_in", "Sign In Action"),
        ("sign_out", "Sign Out Action"),
        ("internship", "Select Internship"),
        ("build_season", "Select Build Season"),
        ("volunteering", "Select First Custom Sheet"),
        ("close_popup", "Close Any Popup/Dialog")
    ]

    for key, label in bindings_config:
        row = tk.Frame(kb_card, bg=panel_bg)
        row.pack(fill="x", padx=12, pady=(8, 0))
        lbl = tk.Label(row, text=f"{label}:", bg=panel_bg, fg=text_color, font=tk_font_small)
        lbl.pack(anchor="w", pady=(0, 4))
        entry = Entry(row, textvariable=keyboardless_binding_vars[key], font=tk_font_small, bd=0, bg=input_bg)
        entry.pack(fill="x", ipady=6)
        style_entry(entry)
        keyboardless_binding_labels.append(lbl)
        keyboardless_binding_entries[key] = entry

    tk.Label(kb_card, text="Each binding must be unique and exactly 16 characters.", bg=panel_bg, fg=footer_text, font=tk_font_small, wraplength=500).pack(anchor="w", padx=12, pady=(10, 12))

    def update_keyboardless_controls_state(*args):
        enabled = bool(keyboardless_enabled_var.get())
        label_color = text_color if enabled else footer_text
        for lbl in keyboardless_binding_labels:
            lbl.configure(fg=label_color)
        for entry in keyboardless_binding_entries.values():
            if enabled:
                entry.configure(state="normal", disabledbackground=input_bg, disabledforeground=footer_text)
            else:
                entry.configure(state="disabled", disabledbackground=input_bg, disabledforeground=footer_text)

    update_keyboardless_controls_state()
    keyboardless_master_cb.configure(command=update_keyboardless_controls_state)

    # Camera trigger updates should immediately affect Data Logging image field toggles.
    def _on_camera_trigger_change(*args):
        try:
            update_image_field_toggle_state()
        except Exception:
            pass

    try:
        camera_trigger_var.trace_add("write", _on_camera_trigger_change)
    except Exception:
        try:
            camera_trigger_var.trace("w", _on_camera_trigger_change)
        except Exception:
            pass

    try:
        local_field_vars["reason"].trace_add("write", update_cutoff_controls_state)
    except Exception:
        try:
            local_field_vars["reason"].trace("w", update_cutoff_controls_state)
        except Exception:
            pass

    # Sidebar items and section switching
    section_order = [
        ("app_behavior", "App Behavior"),
        ("google_settings", "Google Settings"),
        ("data_logging", "Data Logging"),
        ("keyboardless_mode", "Keyboardless Mode"),
    ]
    sidebar_buttons = {}
    current_section = {"name": "app_behavior"}

    tk.Label(sidebar_inner, text="Settings", bg=panel_bg, fg=text_color, font=tk_font_medium, wraplength=230).pack(anchor="w", padx=12, pady=(12, 10))

    def show_section(name):
        current_section["name"] = name
        for s_name, frame in sections.items():
            if s_name == name:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        for s_name, btn in sidebar_buttons.items():
            if s_name == name:
                btn.configure(bg=accent, fg="white", activebackground=accent_dark)
            else:
                btn.configure(bg=panel_bg, fg=text_color, activebackground=accent_dark)
        try:
            content_canvas.yview_moveto(0)
        except Exception:
            pass
        _refresh_content_scroll_region()

    for section_name, section_label in section_order:
        btn = tk.Button(
            sidebar_inner,
            text=section_label,
            command=lambda name=section_name: show_section(name),
            bg=panel_bg,
            fg=text_color,
            font=tk_font_small,
            bd=0,
            activebackground=accent_dark,
            anchor="w",
            padx=12,
            pady=10,
            wraplength=210,
            justify="left"
        )
        btn.pack(fill="x", padx=8, pady=2)
        sidebar_buttons[section_name] = btn

    def validate_keyboardless_bindings():
        values = {}
        for key, var in keyboardless_binding_vars.items():
            val = var.get().strip()
            if val and len(val) != 16:
                show_section("keyboardless_mode")
                messagebox.showerror("Invalid Binding", f"The binding for '{key}' must be exactly 16 characters long.", parent=opts)
                return None
            values[key] = val

        used = [v for v in values.values() if v]
        if len(used) != len(set(used)):
            show_section("keyboardless_mode")
            messagebox.showerror("Duplicate Bindings", "Each binding must be unique. Please check for duplicates.", parent=opts)
            return None
        return values

    def reset_to_defaults():
        nonlocal worksheet_targets_local
        global ui_theme, main_ui_scale, whos_here_scale, camera_frequency, camera_trigger
        global easy_signin_mode, keyboardless_mode, keyboardless_bindings
        global logging_field_toggles, worksheet_targets, late_signin_cutoff, early_signout_cutoff, worksheet_cutoff_toggles

        try:
            if not messagebox.askyesno("Reset Defaults", "Are you sure you want to reset all settings to defaults? This will overwrite your current settings.", parent=opts):
                return
        except Exception:
            return

        ui_theme = DEFAULT_SETTINGS["ui_theme"]
        main_ui_scale = DEFAULT_SETTINGS["main_ui_scale"]
        whos_here_scale = DEFAULT_SETTINGS["whos_here_scale"]
        camera_frequency = DEFAULT_SETTINGS["camera_frequency"]
        camera_trigger = DEFAULT_SETTINGS["camera_trigger"]
        easy_signin_mode = DEFAULT_SETTINGS["easy_signin_mode"]
        keyboardless_mode = DEFAULT_SETTINGS["keyboardless_mode"]
        keyboardless_bindings = DEFAULT_SETTINGS["keyboardless_bindings"].copy()
        logging_field_toggles = DEFAULT_SETTINGS["data_logging"]["fields"].copy()
        worksheet_targets = DEFAULT_SETTINGS["data_logging"]["worksheet_targets"].copy()
        late_signin_cutoff = DEFAULT_SETTINGS["data_logging"]["time_cutoffs"]["late_signin"]
        early_signout_cutoff = DEFAULT_SETTINGS["data_logging"]["time_cutoffs"]["early_signout"]
        worksheet_cutoff_toggles = DEFAULT_SETTINGS["data_logging"]["cutoff_enabled_by_worksheet"].copy()
        worksheet_targets_local = worksheet_targets.copy()

        theme_var_local.set(ui_theme)
        main_scale_var.set(main_ui_scale)
        update_main_scale_label(main_ui_scale)
        whos_here_scale_var.set(whos_here_scale)
        update_whos_here_scale_label(whos_here_scale)
        camera_freq_var.set(camera_frequency)
        update_camera_freq_label(camera_frequency)
        camera_trigger_var.set(camera_trigger)
        easy_signin_var.set(easy_signin_mode)
        keyboardless_enabled_var.set(keyboardless_mode)
        late_cutoff_var.set(late_signin_cutoff)
        early_cutoff_var.set(early_signout_cutoff)
        for key, var in local_field_vars.items():
            var.set(logging_field_toggles.get(key, True))
        for key, var in keyboardless_binding_vars.items():
            var.set(keyboardless_bindings.get(key, ""))
        cutoff_toggle_vars.clear()
        render_cutoff_toggle_rows()

        update_image_field_toggle_state()
        update_keyboardless_controls_state()
        update_cutoff_controls_state()
        render_worksheet_targets()
        data_logging_status_var.set("Data logging settings reset to defaults.")
        data_logging_status_label.configure(fg=positive)

        try:
            if keyboardless_mode:
                enter_keyboardless_mode()
            else:
                exit_keyboardless_mode()
        except Exception:
            pass

        try:
            apply_ui_settings()
            toggle_action_radiobuttons()
            save_settings()
            refresh_whos_here_window()
            adjust_all_toplevels_to_scale()
        except Exception:
            pass

    def apply_and_close(event_arg=None):
        nonlocal worksheet_targets_local
        global ui_theme, main_ui_scale, whos_here_scale, camera_frequency, camera_trigger
        global easy_signin_mode, keyboardless_mode, keyboardless_bindings
        global logging_field_toggles, worksheet_targets, late_signin_cutoff, early_signout_cutoff, worksheet_cutoff_toggles

        new_bindings = validate_keyboardless_bindings()
        if new_bindings is None:
            return

        ui_theme = theme_var_local.get()
        main_ui_scale = main_scale_var.get()
        whos_here_scale = whos_here_scale_var.get()
        try:
            camera_frequency = float(camera_freq_var.get())
        except Exception:
            camera_frequency = 1.0
        camera_trigger = camera_trigger_var.get()
        easy_signin_mode = easy_signin_var.get()
        keyboardless_mode = bool(keyboardless_enabled_var.get())
        keyboardless_bindings = new_bindings

        logging_field_toggles = {key: bool(var.get()) for key, var in local_field_vars.items()}

        late_parsed = _parse_hhmm(late_cutoff_var.get())
        early_parsed = _parse_hhmm(early_cutoff_var.get())
        if late_parsed is None or early_parsed is None:
            show_section("data_logging")
            messagebox.showerror(
                "Invalid Cutoff Time",
                "Use 24-hour HH:MM format for cutoff times (for example, 15:45).",
                parent=opts
            )
            return

        late_signin_cutoff = f"{late_parsed[0]:02d}:{late_parsed[1]:02d}"
        early_signout_cutoff = f"{early_parsed[0]:02d}:{early_parsed[1]:02d}"
        worksheet_targets = _sanitize_worksheet_targets(worksheet_targets_local)
        worksheet_cutoff_toggles = {
            ws_name: bool(var.get())
            for ws_name, var in cutoff_toggle_vars.items()
        }

        if camera_trigger == "never":
            logging_field_toggles["image_link"] = False
            logging_field_toggles["image_path"] = False

        if not logging_field_toggles.get("reason", True):
            worksheet_cutoff_toggles = {
                ws_name: False
                for ws_name in worksheet_cutoff_toggles.keys()
            }

        if keyboardless_mode:
            enter_keyboardless_mode()
        else:
            exit_keyboardless_mode()

        apply_ui_settings()
        try:
            _sync_sheet_metadata(list_sheets())
        except Exception:
            pass
        toggle_action_radiobuttons()
        refresh_whos_here_window()
        try:
            adjust_all_toplevels_to_scale()
        except Exception:
            pass

        try:
            save_settings()
        except Exception:
            pass

        close_options_window()

    def close_options_window():
        try:
            opts.unbind_all("<MouseWheel>")
            opts.unbind_all("<Button-4>")
            opts.unbind_all("<Button-5>")
        except Exception:
            pass
        opts.destroy()

    apply_btn = tk.Button(btn_frame, text="Apply", command=apply_and_close, bg=accent, fg="white", font=tk_font_small, bd=0, activebackground=accent_dark, padx=12, pady=8)
    apply_btn.pack(side="right")
    reset_btn = tk.Button(btn_frame, text="Reset Defaults", command=reset_to_defaults, bg=panel_bg, fg=text_color, font=tk_font_small, bd=0, padx=12, pady=8)
    reset_btn.pack(side="left")
    close_btn = tk.Button(btn_frame, text="Close", command=close_options_window, bg=panel_bg, fg=text_color, font=tk_font_small, bd=0, padx=12, pady=8)
    close_btn.pack(side="right", padx=(0, 8))

    # Default section and startup state
    refresh_account_display()
    current_sheet_var.set(f"Current sheet ID:  {sheet_id if sheet_id else '(none)'}")
    show_section(initial_section)

    opts.protocol("WM_DELETE_WINDOW", close_options_window)
    opts.bind("<Return>", lambda e: apply_and_close())

# Apply UI settings once widgets exist
apply_ui_settings()

if keyboardless_mode:
    try:
        enter_keyboardless_mode()
    except Exception:
        keyboardless_mode = False

# Register cleanup handler for when the app closes
def on_closing():
    """Clean up resources before closing the application."""
    print("Shutting down...")
    try:
        stop_background_sync()
    except Exception as e:
        print(f"Error stopping background sync: {e}")
    root.destroy()

root.protocol("WM_DELETE_WINDOW", on_closing)


# --------------------------
# Deferred Google initialization (after UI is built)
# --------------------------
def _deferred_startup():
    """Run Google initialisation after the main loop starts.

    Opens Settings on the Google section whenever setup is incomplete.
    """
    if not sheet_id:
        messagebox.showwarning(
            "Google Sheet Not Configured",
            "No Google Sheet has been set up yet.\n\n"
            "Please configure or create a Google Sheet so the app "
            "knows where to save attendance data."
        )
        open_options_window("google_settings")
    else:
        set_default_doc(sheet_id)

        # If not signed in, warn and open Settings so the user can sign in.
        if not is_signed_in():
            set_ui_auth_state(False)
            messagebox.showwarning(
                "Google Sign-In Required",
                "You are not signed in to Google.\n\n"
                "Please sign in via Settings → Google Settings to enable attendance logging."
            )
            open_options_window("google_settings")
            return

        set_ui_auth_state(True)

        # Put dropdown into loading state immediately — before the network call.
        _set_dropdown_loading()

        # Verify sheet is accessible before starting background sync.
        # Runs in a thread so the UI stays responsive.
        def _verify_and_init():
            try:
                setup_google_sheet(sheet_id)
            except Exception as e:
                root.after(0, lambda err=str(e): (
                    messagebox.showwarning(
                        "Google Sheet Not Accessible",
                        "The configured Google Sheet could not be opened.\n\n"
                        f"{err}\n\nPlease configure or create a sheet."
                    ),
                    open_options_window("google_settings"),
                ))
                return
            initialize_google_connection()

        threading.Thread(target=_verify_and_init, daemon=True).start()


# Schedule the check for after the mainloop starts
root.after(200, _deferred_startup)

# Start application loop
root.mainloop()
