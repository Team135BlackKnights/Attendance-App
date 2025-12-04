import os
import sys
from PIL import ImageFont
from datetime import datetime
import sqlite3 as sql
import tkinter as tk
from tkinter import messagebox, Label, Entry, Button, Toplevel, Radiobutton, StringVar, OptionMenu, BooleanVar, Checkbutton
from databaseMain import *
from driveUpload import *
from camera import takePic
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from oauth2client.service_account import ServiceAccountCredentials
from tkinter import font
import gspread
import time
import threading

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



# Ensure the table is created 
createTable()

# Get the list of open sheets 
global volunteeringList
volunteeringList = list_sheets()
print(volunteeringList)
if len(volunteeringList) >= 2:
    volunteeringList.pop(0)
    volunteeringList.pop(0)


# --------------------------
# UI state variables (can be toggled via Options)
# --------------------------
ui_theme = "Light"   # "Light" or "Dark"
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

# Center a window on the primary display using the given width/height.
def center_window(window, width=500, height=400):
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    x = (screen_width // 2) - (width // 2)
    y = (screen_height // 2) - (height // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")

# Resize a window to comfortably hold `inner_widget` plus padding, clamped to screen size.
def center_and_fit(window, inner_widget, pad_x=60, pad_y=60, max_width=None, max_height=None):
    """
    Resize window to fit inner_widget's requested size plus padding, then center.
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

# Create and assign font sizes based on main_ui_scale.
def create_fonts():
    global tk_font_large, tk_font_medium, tk_font_smedium, tk_font_small
    # Base sizes scaled by main_ui_scale (0.5 - 2.0)
    tk_font_large = font.Font(family="Poppins", size=int(48 * main_ui_scale))
    tk_font_medium = font.Font(family="Poppins", size=int(36 * main_ui_scale))
    tk_font_smedium = font.Font(family="Poppins", size=int(28 * main_ui_scale))
    tk_font_small = font.Font(family="Poppins", size=int(18 * main_ui_scale))

# --------------------------
# Styling: entries & optionmenus helpers
# --------------------------

# Apply consistent visual styling to an OptionMenu and its dropdown menu.
def style_optionmenu(optmenu):
    """Style an OptionMenu widget and its underlying menu."""
    try:
        optmenu.configure(font=tk_font_small, bg=OPTION_MENU_BG, fg=OPTION_MENU_FG, activebackground=OPTION_MENU_BG, bd=0, relief="flat")
        m = optmenu["menu"]
        # menu background/foreground and active colors
        m.configure(bg=OPTION_MENU_BG, fg=OPTION_MENU_FG, activebackground=ACCENT_DARK, activeforeground=OPTION_MENU_FG, bd=0)
    except Exception:
        pass

# Enhance Entry widgets with an accent outline and consistent inner background/padding.
def style_entry(entry):
    """
    Make entries more distinct: subtle accent outline + inner background and padding.
    For dark mode the outline is thicker for stronger contrast.
    """
    try:
        thick = 3 if ui_theme == "Dark" else 2
        entry.configure(bg=INPUT_BG, fg=TEXT, insertbackground=TEXT,
                        bd=0, relief="flat", font=tk_font_small,
                        highlightthickness=thick, highlightbackground=CARD_BORDER, highlightcolor=ACCENT)
        entry.configure(justify="center")
    except Exception:
        pass

# --------------------------
# Apply theme and style existing widgets (UI-only)
# --------------------------

# Apply the currently chosen theme and tablet_mode to all existing widgets.
# This function updates the color/global variables and restyles existing widgets recursively.
def apply_ui_settings():
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

# Global dictionary to track current signed-in people.
# Keys: person's name (string) -> value: sign-in timestamp string (e.g. "03:24 PM, 2025-12-04")
sign_ins = {}

# Track the currently-open "Who's Here" window and its after() id so we can
# avoid multiple pollers and cancel polling when the window closes.
whos_here_win = None
whos_here_after_id = None
whos_here_populate_func = None  # Reference to populate function for manual refresh

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


# Validate the ID entry, fetch the name from DB, and either prompt for name or take picture+record attendance.
def scan_id(event=None):
    try:
        current_id = int(id_entry.get())
        if len(str(current_id)) != 6 or current_id < 0:
            raise ValueError("Invalid length")
    except ValueError as e:
        messagebox.showerror("Error", f"Invalid ID: {str(e)}")
        return

    id_entry.delete(0, tk.END)
    name = getName(current_id)
    if not name:
        ask_name_window(current_id)
    else:
        open_smile_window(current_id, name)

# Prompt for a new user's first+last name and save it to the database.
def ask_name_window(current_id):
    new_window = Toplevel(root)
    new_window.title("Enter Name")
    center_window(new_window, width=460, height=260)
    new_window.configure(bg=BG_MAIN)
    new_window.focus_force()

    card = tk.Frame(new_window, bg=PANEL_BG, bd=1, relief="solid", highlightthickness=1)
    card.place(relx=0.5, rely=0.5, anchor=tk.CENTER, width=420, height=200)
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
            writeName(current_id, formatted)
            new_window.destroy()
            open_smile_window(current_id, formatted)
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

# Show a "Smile!" confirmation card and then take a picture after a short delay.
def open_smile_window(current_id, name):
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

# Render the styled "Smile!" message inside a container (card or window).
def display_smile_message(container):
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

# Take a picture using camera.takePic, then either proceed to process attendance or show failure UI.
def take_picture_and_record(window, current_id, name):
    now = datetime.now()
    global folder
    folder = f"images/{current_id}-{name}"
    if not os.path.isdir(folder):
        os.makedirs(folder)

    file_date = now.strftime("%I-%M-%p-%Y-%m-%d")
    global picName
    picName = f"{name}__{file_date}.jpeg"
    confirmation = takePic(f"{name}__{file_date}", f"{current_id}-{name}")

    window.destroy()
    if (confirmation == None):
        process_attendance(current_id, name)
    else:
        open_fail_window(current_id, name)

# Display camera failure dialog and allow approved override binding (binding kept, UI text removed).
def open_fail_window(current_id, name):
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

# Render the message shown on camera failure dialogs.
def display_fail_message(container):
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

# Record attendance to the local DB and start a background thread to push data to Google.
def process_attendance(current_id, name, hasPic = True):
    now = datetime.now()
    formatted_time = now.strftime("%I:%M %p")
    formatted_date = now.strftime("%Y-%m-%d")

    action = action_var.get()
    event = event_var.get()

    reason = None
    if event == "Internship":
        if action == "out":
            if now.hour < 18 or (now.hour == 18 and now.minute < 45):
                reason = early_sign_out()
            else:
                reason = None
        else:
            if now.hour > 15 or (now.hour == 15 and now.minute > 45):
                reason = late_sign_in()
            else:
                reason = None
    elif event == "Volunteering":
        reason = volunteering_event_window()
    elif event == "Build Season":
        reason = "Build Season"

    full_date = f"Signed {action} at: {formatted_time}, Date: {formatted_date}"
    writeData(current_id, name, full_date, reason)

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

    load = open_loading_window()
    if (hasPic):
        threading.Thread(
            target=push_to_google,
            args=(current_id, name, full_date, event, reason, load)
        ).start()
    else:
        threading.Thread(
            target=push_to_google,
            args=(current_id, name, full_date, event, reason, load, False)
        ).start()

# Open a loading dialog while background push is happening.
def open_loading_window():
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

# Render the text inside the loading dialog.
def display_loading_message(container):
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

# Popup for selecting a volunteering event when "Volunteering" is selected.
def volunteering_event_window():
    new_window = Toplevel(root)
    new_window.title("Select An Event")
    center_window(new_window, width=460, height=260)
    new_window.configure(bg=BG_MAIN)
    new_window.focus_force()

    card = tk.Frame(new_window, bg=PANEL_BG, bd=1, relief="solid")
    card.place(relx=0.5, rely=0.5, anchor=tk.CENTER, width=420, height=200)
    try:
        card.configure(highlightbackground=CARD_BORDER)
    except Exception:
        pass

    Label(card, text="Select your volunteering event:", bg=PANEL_BG, fg=TEXT, font=tk_font_small).pack(pady=(14, 8))

    volunteering_var = StringVar(value="None")
    eventDropdown = OptionMenu(card, volunteering_var, *volunteeringList)
    eventDropdown.configure(font=tk_font_small, bg=OPTION_MENU_BG, fg=OPTION_MENU_FG, bd=0, relief="flat")
    try:
        eventDropdown["menu"].configure(bg=OPTION_MENU_BG, fg=OPTION_MENU_FG, activebackground=ACCENT_DARK, activeforeground=OPTION_MENU_FG)
    except Exception:
        pass
    eventDropdown.pack(pady=6)

    event = None

    def returnEvent(event_arg=None):
        nonlocal event
        event = volunteering_var.get()
        if event == "None":
            messagebox.showerror("Error", "Select an event", parent=new_window)
        else:
            new_window.destroy()
            print(event)

    Button(card, text="Submit", command=lambda: returnEvent(), bg=ACCENT, fg="white", bd=0,
           font=tk_font_small, activebackground=ACCENT_DARK, padx=12, pady=8).pack(pady=(8, 12))

    # Bind Enter to submit the selected event (both on window and on dropdown)
    new_window.bind("<Return>", lambda e: returnEvent())
    eventDropdown.bind("<Return>", lambda e: returnEvent())

    center_and_fit(new_window, card, pad_x=80, pad_y=80)
    root.wait_window(new_window)
    return event

# Background function: push attendance + image to Google Sheets + Drive.
def push_to_google(current_id, name, attendance_record, event, reason, load, hasPic = True):
    try:
        spreadsheet = setup_google_sheet()
        drive = setup_google_drive()

        action = action_var.get()

        if (hasPic):
            file_path = f"{folder}/{picName}"
            print(file_path)
            file_url = upload_image_to_drive(drive, file_path)
        else:
            file_path = "No Image"
            file_url = "No Image"

        if (reason not in volunteeringList) and reason != "Build Season" :
            sheet = spreadsheet.worksheet("Main Attendance")
            insert_data(sheet, action, [current_id, name, attendance_record, file_path, file_url, reason])
        elif reason == "Build Season":
            sheet = spreadsheet.worksheet("Build Season")
            insert_data(sheet, action, [current_id, name, attendance_record, file_path, file_url, reason])
        else:
            sheet = spreadsheet.worksheet(reason)
            insert_data(sheet, action, [current_id, name, attendance_record, file_path, file_url, reason])

    finally:
        root.after(0, load.destroy)
        root.after(0, lambda: messagebox.showinfo(
            "Attendance Recorded",
            f"Name: {name}\n{attendance_record}\nReason: {reason if reason else 'N/A'}"
        ))

# Helper to find the next empty row in a sheet column range.
def next_available_row(sheet, col_range):
    values = sheet.get(col_range)
    return len(values) + 1

# Insert sign-in/sign-out data into the appropriate columns on the sheet.
def insert_data(sheet, action, data):
    if(action == "in"):
        row = next_available_row(sheet, "A:A")
        sheet.update(f"A{row}:F{row}", [data])
    else:
        row = next_available_row(sheet, "H:H")
        sheet.update(f"H{row}:M{row}", [data])

# Ask user for a reason to early sign out; return the collected reason string.
def early_sign_out():
    reason_window = Toplevel(root)
    reason_window.title("Reason for Early Sign-Out")
    center_window(reason_window, width=460, height=220)
    reason_window.configure(bg=BG_MAIN)
    reason_window.focus_force()

    card = tk.Frame(reason_window, bg=PANEL_BG, bd=1, relief="solid")
    card.place(relx=0.5, rely=0.5, anchor=tk.CENTER, width=420, height=180)
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

    center_and_fit(reason_window, card, pad_x=80, pad_y=80)
    root.wait_window(reason_window)
    reason = "Early sign out: " + reason
    return reason

# Ask user for a reason to late sign in; return the collected reason string.
def late_sign_in():
    reason_window = Toplevel(root)
    reason_window.title("Reason for Late Sign-In")
    center_window(reason_window, width=460, height=220)
    reason_window.configure(bg=BG_MAIN)
    reason_window.focus_force()

    card = tk.Frame(reason_window, bg=PANEL_BG, bd=1, relief="solid")
    card.place(relx=0.5, rely=0.5, anchor=tk.CENTER, width=420, height=180)
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

    center_and_fit(reason_window, card, pad_x=80, pad_y=80)
    root.wait_window(reason_window)
    reason = "Late Sign In: " + reason
    return reason

# --------------------------
# Build main UI (fonts created before widgets)
# --------------------------
root = tk.Tk()
root.title("Attendance System")
center_window(root, width=1000, height=720)

action_var = StringVar(value="in")
event_var = StringVar(value="Internship")

root.attributes("-fullscreen", True)
root.bind("<Escape>", lambda event: root.attributes("-fullscreen", False))

# Initialize fonts (so widgets can use them)
load_private_font(os.path.join("fonts", "Poppins-Regular.ttf"))
create_fonts()

# Header
header = tk.Frame(root, bg="#FFFFFF", bd=1, relief="solid")
header.pack(fill="x", padx=24, pady=(20, 10))
header_title = Label(header, text="Attendance System", font=tk_font_large, bg="#FFFFFF", fg="#1F2D3D")
header_title.pack(side="left", padx=20, pady=18)

# Options button
options_btn = tk.Button(header, text="⚙️ Options", command=lambda: open_options_window(), bg="#FFFFFF", fg="#1F2D3D",
                        font=tk_font_small, bd=0, activebackground="#0B63C7")
options_btn.pack(side="right", padx=16, pady=12)

# Who's Here button
tracking_btn = tk.Button(header, text="Who's here?", command=lambda: open_whos_here_window(), bg="#FFFFFF", fg="#1F2D3D",
                        font=tk_font_small, bd=0, activebackground="#0B63C7")
tracking_btn.pack(side="right", padx=16, pady=12)


# Main panel
main_card = tk.Frame(root, bg="#FFFFFF", bd=1, relief="solid")
main_card.pack(expand=True, padx=24, pady=12, ipadx=10, ipady=10)
try:
    main_card.configure(highlightbackground=THEMES["Light"]["CARD_BORDER"])
except Exception:
    pass

# Inputs column
inputs_frame = tk.Frame(main_card, bg="#FFFFFF")
inputs_frame.pack(side="left", fill="both", expand=True, padx=28, pady=20)

Label(inputs_frame, text="Enter your ID:", font=tk_font_medium, bg="#FFFFFF", fg="#1F2D3D").pack(anchor="w", pady=(6, 8))
id_entry = Entry(inputs_frame, font=tk_font_medium, bd=0, bg="#FFFFFF", justify="center")
id_entry.pack(fill="x", pady=(0, 12), ipady=10)
style_entry(id_entry)
id_entry.bind("<Return>", lambda event: scan_id())

# Controls column
controls_frame = tk.Frame(main_card, bg="#FFFFFF")
controls_frame.pack(side="right", fill="both", expand=True, padx=28, pady=20)

Label(controls_frame, text="Why are you here:", font=tk_font_small, bg="#FFFFFF", fg="#1F2D3D").pack(anchor="w", pady=(6, 6))

if len(volunteeringList) > 0:
    eventsList = ["Internship", "Build Season", "Volunteering"]
else:
    eventsList = ["Internship", "Build Season"]

w = OptionMenu(controls_frame, event_var, *eventsList)
w.config(font=tk_font_small)
w.pack(anchor="w", pady=(0, 12))
# make sure initial OptionMenu uses the theme's menu colors
try:
    w["menu"].configure(bg=THEMES[ui_theme]["OPTION_MENU_BG"], fg=THEMES[ui_theme]["OPTION_MENU_FG"],
                       activebackground=THEMES[ui_theme]["ACCENT_DARK"], activeforeground=THEMES[ui_theme]["OPTION_MENU_FG"])
except Exception:
    pass
# bind Enter on the optionmenu to trigger no-op selection (keeps behavior consistent)
w.bind("<Return>", lambda e: None)

Label(controls_frame, text="Select Action:", font=tk_font_small, bg="#FFFFFF", fg="#1F2D3D").pack(anchor="w", pady=(6, 6))
Radiobutton(controls_frame, text="Sign In", font=tk_font_smedium, variable=action_var, value="in", bg="#FFFFFF").pack(anchor="w")
Radiobutton(controls_frame, text="Sign Out", font=tk_font_smedium, variable=action_var, value="out", bg="#FFFFFF").pack(anchor="w")

# Action row
action_row = tk.Frame(root, bg="#F3F6FA")
action_row.pack(fill="x", padx=24, pady=(6, 24))
enter_btn = tk.Button(action_row, text="Enter", font=tk_font_smedium, command=lambda: scan_id(),
                      bg="#1565C0", fg="white", bd=0, activebackground="#0B63C7", padx=18, pady=10)
enter_btn.pack(side="right")

# Footer
footer = tk.Frame(root, bg="#F3F6FA")
footer.pack(fill="x", padx=24, pady=(0, 18))
footer_label = Label(footer, text="Tip: Press Esc to exit fullscreen.", font=tk_font_small, bg="#F3F6FA", fg="#5D6D7E")
footer_label.pack(side="left", padx=6, pady=6)

# --------------------------
# "Who's Here" dialog: show currently signed-in people (freely resizable with scrollable list)
def open_whos_here_window():
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
        if not current:
            Label(scrollable_frame, text="No one is currently signed in.", bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=FOOTER_TEXT if FOOTER_TEXT else THEMES["Light"]["FOOTER_TEXT"], font=wh_font_small).pack(pady=8, padx=8)
            return
        
        # Adjust wraplength based on canvas width
        try:
            canvas.update_idletasks()
            avail_w = max(200, canvas.winfo_width() - 40)
        except Exception:
            avail_w = 400
        
        # Sort by timestamp and create labels
        for name, ts in sorted(current.items(), key=lambda x: x[1]):
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
    
    btn_row = tk.Frame(container, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"]) 
    btn_row.pack(fill="x", pady=(6, 12), padx=12)
    refresh_btn = tk.Button(btn_row, text="Refresh", command=populate, bg=ACCENT if ACCENT else THEMES["Light"]["ACCENT"], fg="white", bd=0, font=wh_font_small_btn, activebackground=ACCENT_DARK if ACCENT_DARK else THEMES["Light"]["ACCENT_DARK"], padx=12, pady=6)
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
# Options dialog 
# --------------------------

# Open the Options dialog with scrollable canvas and scale sliders
def open_options_window():
    opts = Toplevel(root)
    opts.title("Options")
    opts.configure(bg=BG_MAIN if BG_MAIN else THEMES["Light"]["BG_MAIN"])
    opts.focus_force()
    center_window(opts, width=750, height=500)

    # Outer card frame
    card = tk.Frame(opts, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], bd=1, relief="solid")
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

    # When the options window is resized, ensure the embedded window width follows
    resize_after_opts = None
    def _on_opts_resize(event=None):
        nonlocal resize_after_opts
        try:
            if resize_after_opts is not None:
                root.after_cancel(resize_after_opts)
        except Exception:
            pass
        def _do():
            try:
                canvas.itemconfig(window_id, width=canvas.winfo_width())
                canvas.configure(scrollregion=canvas.bbox("all"))
            except Exception:
                pass
        resize_after_opts = root.after(120, _do)
    opts.bind('<Configure>', _on_opts_resize)

    # Theme selector
    tk.Label(scrollable_frame, text="Theme:", bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=TEXT if TEXT else THEMES["Light"]["TEXT"], font=tk_font_small).pack(anchor="w", padx=18, pady=(16, 4))
    theme_var_local = StringVar(value=ui_theme)
    theme_menu = OptionMenu(scrollable_frame, theme_var_local, "Light", "Dark")
    theme_menu.configure(font=tk_font_small, bg=OPTION_MENU_BG if OPTION_MENU_BG else THEMES["Light"]["OPTION_MENU_BG"], fg=OPTION_MENU_FG if OPTION_MENU_FG else THEMES["Light"]["OPTION_MENU_FG"], bd=0, relief="flat")
    try:
        theme_menu["menu"].configure(bg=OPTION_MENU_BG if OPTION_MENU_BG else THEMES["Light"]["OPTION_MENU_BG"],
                                     fg=OPTION_MENU_FG if OPTION_MENU_FG else THEMES["Light"]["OPTION_MENU_FG"],
                                     activebackground=ACCENT_DARK if ACCENT_DARK else THEMES["Light"]["ACCENT_DARK"],
                                     activeforeground=OPTION_MENU_FG if OPTION_MENU_FG else THEMES["Light"]["OPTION_MENU_FG"])
    except Exception:
        pass
    theme_menu.pack(anchor="w", padx=18, pady=(0, 12))

    # Main UI Scale slider
    tk.Label(scrollable_frame, text="Main UI Scale (0.5x - 2.0x):", bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=TEXT if TEXT else THEMES["Light"]["TEXT"], font=tk_font_small).pack(anchor="w", padx=18, pady=(10, 4))
    main_scale_var = tk.DoubleVar(value=main_ui_scale)
    main_scale_label = tk.Label(scrollable_frame, text=f"{main_ui_scale:.2f}x", bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=TEXT if TEXT else THEMES["Light"]["TEXT"], font=tk_font_small)
    main_scale_label.pack(anchor="w", padx=18)
    
    def update_main_scale_label(val):
        main_scale_label.config(text=f"{float(val):.2f}x")
    
    main_scale_slider = tk.Scale(scrollable_frame, from_=0.5, to=2.0, resolution=0.1, orient="horizontal", variable=main_scale_var, 
                                 command=update_main_scale_label, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], 
                                 fg=TEXT if TEXT else THEMES["Light"]["TEXT"], highlightthickness=0, troughcolor=ACCENT if ACCENT else THEMES["Light"]["ACCENT"])
    main_scale_slider.pack(fill="x", padx=18, pady=(0, 12))

    # Who's Here Scale slider
    tk.Label(scrollable_frame, text="Who's Here Scale (0.5x - 2.0x):", bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=TEXT if TEXT else THEMES["Light"]["TEXT"], font=tk_font_small).pack(anchor="w", padx=18, pady=(10, 4))
    whos_here_scale_var = tk.DoubleVar(value=whos_here_scale)
    whos_here_scale_label = tk.Label(scrollable_frame, text=f"{whos_here_scale:.2f}x", bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=TEXT if TEXT else THEMES["Light"]["TEXT"], font=tk_font_small)
    whos_here_scale_label.pack(anchor="w", padx=18)
    
    def update_whos_here_scale_label(val):
        whos_here_scale_label.config(text=f"{float(val):.2f}x")
    
    whos_here_scale_slider = tk.Scale(scrollable_frame, from_=0.5, to=2.0, resolution=0.1, orient="horizontal", variable=whos_here_scale_var,
                                      command=update_whos_here_scale_label, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"],
                                      fg=TEXT if TEXT else THEMES["Light"]["TEXT"], highlightthickness=0, troughcolor=ACCENT if ACCENT else THEMES["Light"]["ACCENT"])
    whos_here_scale_slider.pack(fill="x", padx=18, pady=(0, 20))

    # Buttons at bottom of card (not in scrollable area)
    btn_frame = tk.Frame(card, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"])
    btn_frame.pack(fill="x", pady=(0, 10), padx=18)
    
    def apply_and_close(event_arg=None):
        nonlocal theme_var_local, main_scale_var, whos_here_scale_var
        global ui_theme, main_ui_scale, whos_here_scale
        ui_theme = theme_var_local.get()
        main_ui_scale = main_scale_var.get()
        whos_here_scale = whos_here_scale_var.get()
        apply_ui_settings()
        # Trigger manual refresh of Who's Here window if open
        refresh_whos_here_window()
        # Adjust other open dialogs/windows to the new scale
        try:
            adjust_all_toplevels_to_scale()
        except Exception:
            pass
        opts.destroy()
    
    apply_btn = tk.Button(btn_frame, text="Apply", command=apply_and_close, bg=ACCENT if ACCENT else THEMES["Light"]["ACCENT"], fg="white",
                          font=tk_font_small, bd=0, activebackground=ACCENT_DARK if ACCENT_DARK else THEMES["Light"]["ACCENT_DARK"], padx=12, pady=8)
    apply_btn.pack(side="right")
    close_btn = tk.Button(btn_frame, text="Close", command=lambda: opts.destroy(), bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=TEXT if TEXT else THEMES["Light"]["TEXT"],
                          font=tk_font_small, bd=0, padx=12, pady=8)
    close_btn.pack(side="right", padx=(0, 8))

    # Bind Enter to apply
    opts.bind("<Return>", lambda e: apply_and_close())

# Apply UI settings once widgets exist
apply_ui_settings()

# Start application loop
root.mainloop()
