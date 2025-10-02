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
tablet_mode = False  # if True, use larger fonts/layout

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

# --------------------------
# Fonts
# --------------------------
tk_font_large = None
tk_font_medium = None
tk_font_smedium = None
tk_font_small = None

# Create and assign font sizes based on tablet_mode.
def create_fonts():
    global tk_font_large, tk_font_medium, tk_font_smedium, tk_font_small
    if tablet_mode:
        tk_font_large = font.Font(family="Poppins", size=56)
        tk_font_medium = font.Font(family="Poppins", size=42)
        tk_font_smedium = font.Font(family="Poppins", size=34)
        tk_font_small = font.Font(family="Poppins", size=22)
    else:
        tk_font_large = font.Font(family="Poppins", size=48)
        tk_font_medium = font.Font(family="Poppins", size=36)
        tk_font_smedium = font.Font(family="Poppins", size=28)
        tk_font_small = font.Font(family="Poppins", size=18)

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
        # Try to add some internal padding on platforms that permit it:
        try:
            entry_ipady = 8 if not tablet_mode else 12
            # ipady must be set when packing; set a small internal height by configuring 'ipady' during pack in creation sites
        except Exception:
            pass
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
# Options dialog (UI only)
# --------------------------

# Open the Options dialog: toggle tablet mode & theme and apply them to the UI.
def open_options_window():
    opts = Toplevel(root)
    opts.title("Options")
    opts.resizable(True, True)
    opts.configure(bg=BG_MAIN if BG_MAIN else THEMES["Light"]["BG_MAIN"])
    opts.focus_force()

    card = tk.Frame(opts, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], bd=1, relief="solid")
    card.place(relx=0.5, rely=0.5, anchor="center")
    try:
        card.configure(highlightbackground=CARD_BORDER if CARD_BORDER else THEMES["Light"]["CARD_BORDER"])
    except Exception:
        pass

    tablet_var = BooleanVar(value=tablet_mode)
    tablet_row = tk.Frame(card, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"])
    tablet_row.pack(fill="x", pady=(16, 6), padx=18)
    tk.Label(tablet_row, text="Tablet Mode (larger UI):", bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=TEXT if TEXT else THEMES["Light"]["TEXT"], font=tk_font_small).pack(side="left")
    tablet_chk = Checkbutton(tablet_row, variable=tablet_var, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], selectcolor=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"])
    tablet_chk.pack(side="right")

    tk.Label(card, text="Theme:", bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=TEXT if TEXT else THEMES["Light"]["TEXT"], font=tk_font_small).pack(anchor="w", padx=18, pady=(10, 4))
    theme_var_local = StringVar(value=ui_theme)
    theme_menu = OptionMenu(card, theme_var_local, "Light", "Dark")
    theme_menu.configure(font=tk_font_small, bg=OPTION_MENU_BG if OPTION_MENU_BG else THEMES["Light"]["OPTION_MENU_BG"], fg=OPTION_MENU_FG if OPTION_MENU_FG else THEMES["Light"]["OPTION_MENU_FG"], bd=0, relief="flat")
    try:
        theme_menu["menu"].configure(bg=OPTION_MENU_BG if OPTION_MENU_BG else THEMES["Light"]["OPTION_MENU_BG"],
                                     fg=OPTION_MENU_FG if OPTION_MENU_FG else THEMES["Light"]["OPTION_MENU_FG"],
                                     activebackground=ACCENT_DARK if ACCENT_DARK else THEMES["Light"]["ACCENT_DARK"],
                                     activeforeground=OPTION_MENU_FG if OPTION_MENU_FG else THEMES["Light"]["OPTION_MENU_FG"])
    except Exception:
        pass
    theme_menu.pack(anchor="w", padx=18)

    btn_frame = tk.Frame(card, bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"])
    btn_frame.pack(fill="x", pady=(18, 8), padx=18)
    def apply_and_close(event_arg=None):
        nonlocal theme_var_local, tablet_var
        global ui_theme, tablet_mode
        ui_theme = theme_var_local.get()
        tablet_mode = tablet_var.get()
        apply_ui_settings()
        opts.destroy()
    apply_btn = tk.Button(btn_frame, text="Apply", command=apply_and_close, bg=ACCENT if ACCENT else THEMES["Light"]["ACCENT"], fg="white",
                          font=tk_font_small, bd=0, activebackground=ACCENT_DARK if ACCENT_DARK else THEMES["Light"]["ACCENT_DARK"], padx=12, pady=8)
    apply_btn.pack(side="right")
    close_btn = tk.Button(btn_frame, text="Close", command=lambda: opts.destroy(), bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=TEXT if TEXT else THEMES["Light"]["TEXT"],
                          font=tk_font_small, bd=0)
    close_btn.pack(side="right", padx=(0, 8))

    # Bind Enter to apply (so Enter works for Options dialog)
    opts.bind("<Return>", lambda e: apply_and_close())

    # size card to content and center
    card.update_idletasks()
    card_width = max(card.winfo_reqwidth(), 340)
    card_height = max(card.winfo_reqheight(), 160)
    card.place_configure(width=card_width, height=card_height)
    center_and_fit(opts, card, pad_x=80, pad_y=80)

# Apply UI settings once widgets exist
apply_ui_settings()

# Start application loop
root.mainloop()
