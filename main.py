import os
import sys
from PIL import ImageFont
from datetime import datetime
import tkinter as tk
from tkinter import messagebox, Label, Entry, Button, Toplevel, Radiobutton, StringVar, OptionMenu, BooleanVar, Checkbutton, Scale, HORIZONTAL
import driveUpload
from camera import takePic
from tkinter import font
import threading

# --- Begin: Embedding Poppins (runtime only) --------------------------------
if os.name == "nt":
    import ctypes
    FR_PRIVATE = 0x10

def _get_base_path():
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))

def load_private_font(filename):
    font_path = os.path.join(_get_base_path(), filename)
    if os.name == "nt" and os.path.exists(font_path):
        try:
            ctypes.windll.gdi32.AddFontResourceExW(font_path, FR_PRIVATE, 0)
        except Exception:
            pass
    return font_path

# =========================
# Compatibility wrappers that delegate to driveUpload helpers
# These preserve the original function names used throughout your app.
# =========================

API_BASE_URL = "http://127.0.0.1:8080/api"
PARENT_FOLDER_ID = "PARENT_FOLDER_ID"
VOLUNTEER_SPREADSHEET_TITLE = "VOLUNTEER_SPREADSHEET_TITLE"
ATTENDANCE_SPREADSHEET_TITLE = "ATTENDANCE_SPREADSHEET_TITLE"
DB_SPREADSHEET_TITLE = "DB_SPREADSHEET_TITLE"


def list_sheets():
    """
    Return a simple Python list of subsheet names for the volunteer spreadsheet.
    Delegates to driveUpload.list_subsheets which returns a JSON-like dict.
    """
    title = VOLUNTEER_SPREADSHEET_TITLE
    if not title:
        # If no configured spreadsheet, return empty list (preserves UI behavior)
        return []
    resp = driveUpload.list_subsheets(spreadsheet_title=title)
    if isinstance(resp, dict) and resp.get("status") == "success":
        return resp.get("sheets", [])
    # if driveUpload returned an error dict or unexpected value, return [] to avoid crashing UI
    return []

def getName(target_id):
    """
    Lookup name by ID via driveUpload.find_id.
    Returns the name string, or None if not found.
    """
    # prefer Attendance Database tab by default
    sheet_tab = "Attendance Database"
    try:
        if DB_SPREADSHEET_TITLE:
            resp = driveUpload.find_id(sheet_tab, str(target_id), spreadsheet_title=DB_SPREADSHEET_TITLE)
        else:
            resp = driveUpload.find_id(sheet_tab, str(target_id))
    except Exception:
        return None

    if not isinstance(resp, dict):
        return None

    if resp.get("status") == "success":
        return resp.get("name")
    # not found or error
    return None

def writeName(target_id, name):
    """
    Write an ID->Name mapping using driveUpload.write_id_name.
    Returns the underlying response (dict) or an error dict.
    """
    try:
        if DB_SPREADSHEET_TITLE:
            return driveUpload.write_id_name(str(target_id), name, spreadsheet_title=DB_SPREADSHEET_TITLE, sheet_tab="Attendance Database")
        else:
            return driveUpload.write_id_name(str(target_id), name, sheet_tab="Attendance Database")
    except Exception as e:
        return {"status": "error", "message": str(e)}

def writeData(target_id, name, date_str, reason=None, image_url=None, sheet_tab="Attendance"):
    """
    Append an attendance row via driveUpload.write_row.
    Keeps the original row order ["ID","Name","Date","Reason","Image URL"].
    """
    row = [str(target_id), name, date_str, reason if reason else "", image_url if image_url else ""]
    try:
        if ATTENDANCE_SPREADSHEET_TITLE:
            return driveUpload.write_row(row, sheet_tab, spreadsheet_title=ATTENDANCE_SPREADSHEET_TITLE)
        else:
            return driveUpload.write_row(row, sheet_tab)
    except Exception as e:
        return {"status": "error", "message": str(e)}

def push_to_google(current_id, name, full_date, event, reason, loading_window, hasPic=True):
    """
    Background worker that:
      - uploads the picture (if available and PARENT_FOLDER_ID provided) via driveUpload.upload_image
      - calls driveUpload.record_attendance with the assembled payload
    Closes the loading_window at the end (preserves previous behavior).
    """
    try:
        image_url = None
        # The app stores picName and folder as globals when picture was taken
        if hasPic and 'picName' in globals() and 'folder' in globals():
            image_path = os.path.join(folder, picName)
            if os.path.exists(image_path) and PARENT_FOLDER_ID:
                try:
                    upload_resp = driveUpload.upload_image(image_path, PARENT_FOLDER_ID, folder_name="Attendance Images")
                    if isinstance(upload_resp, dict) and upload_resp.get("status") == "success":
                        # driveUpload returns {"status":"success","file":{...,"webViewLink":...}}
                        image_url = upload_resp.get("file", {}).get("webViewLink")
                except Exception:
                    image_url = None

        payload = {
            "id": str(current_id),
            "name": name,
            "date": full_date,
            "reason": reason,
            "image_url": image_url
        }
        if ATTENDANCE_SPREADSHEET_TITLE:
            payload["spreadsheet_title"] = ATTENDANCE_SPREADSHEET_TITLE
        if event:
            payload["sheet_tab"] = event

        try:
            driveUpload.record_attendance(payload)
        except Exception:
            # swallow exceptions to avoid crashing background thread; UI only depends on completion
            pass

    finally:
        # close loading UI
        try:
            loading_window.destroy()
        except Exception:
            pass

# =========================
# End wrappers
# =========================

# Get the list of open sheets 
global volunteeringList
volunteeringList = list_sheets()
print(volunteeringList)
if len(volunteeringList) >= 2:
    volunteeringList.pop(0)
    volunteeringList.pop(0)

# --------------------------
# UI state variables
# --------------------------
ui_theme = "Light"
ui_scale = 1.0  # default scale factor
popup_scale = 1.25  # additional popup scaling factor (tweakable)

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
        "CARD_BORDER": "#D0D7DF",
        "BUTTON_ACTIVE": "#0B63C7",
        "INPUT_BG": "#FFFFFF",
        "FOOTER_TEXT": "#5D6D7E",
        "OPTION_MENU_BG": "#FFFFFF",
        "OPTION_MENU_FG": "#1F2D3D"
    },
    "Dark": {
        "BG_MAIN": "#0B0D0F",
        "PANEL_BG": "#111417",
        "ACCENT": "#1B6ED6",
        "ACCENT_DARK": "#144E8A",
        "TEXT": "#C9D6E1",
        "POSITIVE": "#6FC17A",
        "NEGATIVE": "#FF6B6B",
        "CARD_BORDER": "#2C3E50",
        "BUTTON_ACTIVE": "#144E8A",
        "INPUT_BG": "#0A1116",
        "FOOTER_TEXT": "#94A9BD",
        "OPTION_MENU_BG": "#111417",
        "OPTION_MENU_FG": "#C9D6E1"
    }
}

# theme globals
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
def center_window(window, width=500, height=400, scale_factor=1.0):
    """
    Center a window on screen. Optional scale_factor multiplies width/height
    (used to ensure popups are slightly larger than their content at high ui_scale).
    """
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    width = int(width * scale_factor)
    height = int(height * scale_factor)
    x = (screen_width // 2) - (width // 2)
    y = (screen_height // 2) - (height // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")

def center_and_fit(window, inner_widget, pad_x=60, pad_y=60, max_width=None, max_height=None, scale_factor=1.0):
    """
    Size the window around inner_widget but cap to screen. scale_factor is applied
    to the computed size (use popup_scale > 1 to make popups larger in proportion to content).
    """
    window.update_idletasks()
    req_w = inner_widget.winfo_reqwidth() + pad_x
    req_h = inner_widget.winfo_reqheight() + pad_y
    # apply the popup scale factor here
    req_w = int(req_w * scale_factor)
    req_h = int(req_h * scale_factor)

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

def create_fonts():
    global tk_font_large, tk_font_medium, tk_font_smedium, tk_font_small
    base_sizes = {"large": 48, "medium": 36, "smedium": 28, "small": 18}
    tk_font_large = font.Font(family="Poppins", size=int(base_sizes["large"] * ui_scale))
    tk_font_medium = font.Font(family="Poppins", size=int(base_sizes["medium"] * ui_scale))
    tk_font_smedium = font.Font(family="Poppins", size=int(base_sizes["smedium"] * ui_scale))
    tk_font_small = font.Font(family="Poppins", size=int(base_sizes["small"] * ui_scale))

# --------------------------
# Styling helpers
# --------------------------
def style_optionmenu(optmenu):
    try:
        # Thin grey/neutral border with consistent background/foreground
        optmenu.configure(
            font=tk_font_small,
            bg=OPTION_MENU_BG,
            fg=OPTION_MENU_FG,
            activebackground=ACCENT_DARK,
            activeforeground=OPTION_MENU_FG,
            bd=2,
            relief="solid",
            highlightthickness=1,
            highlightbackground=CARD_BORDER,
            cursor="hand2"
        )
        m = optmenu["menu"]
        m.configure(
            bg=OPTION_MENU_BG,
            fg=OPTION_MENU_FG,
            activebackground=ACCENT_DARK,
            activeforeground=OPTION_MENU_FG,
            bd=0,
            relief="flat"
        )
    except Exception:
        pass

def style_entry(entry):
    try:
        thick = 3 if ui_theme == "Dark" else 2
        entry.configure(
            bg=INPUT_BG, fg=TEXT, insertbackground=TEXT,
            bd=1, relief="solid", font=tk_font_small,
            highlightthickness=thick, highlightbackground=CARD_BORDER, highlightcolor=ACCENT,
            justify="center"
        )
    except Exception:
        pass

# --------------------------
# Apply theme and restyle widgets
# --------------------------
def apply_ui_settings():
    global BG_MAIN, PANEL_BG, ACCENT, ACCENT_DARK, TEXT, POSITIVE, NEGATIVE
    global CARD_BORDER, BUTTON_ACTIVE, INPUT_BG, FOOTER_TEXT, OPTION_MENU_BG, OPTION_MENU_FG

    theme = THEMES.get(ui_theme, THEMES["Light"])
    BG_MAIN = theme["BG_MAIN"]
    PANEL_BG = theme["PANEL_BG"]
    ACCENT = theme["ACCENT"]
    ACCENT_DARK = theme["ACCENT_DARK"]
    TEXT = theme["TEXT"]
    POSITIVE = theme["POSITIVE"]
    NEGATIVE = theme["NEGATIVE"]
    # More distinctive grey border for dark mode (clearly visible)
    CARD_BORDER = "#8A8A8A" if ui_theme == "Dark" else theme["CARD_BORDER"]
    BUTTON_ACTIVE = theme["BUTTON_ACTIVE"]
    INPUT_BG = theme["INPUT_BG"]
    FOOTER_TEXT = theme["FOOTER_TEXT"]
    OPTION_MENU_BG = theme["OPTION_MENU_BG"]
    OPTION_MENU_FG = theme["OPTION_MENU_FG"]

    load_private_font(os.path.join("fonts", "Poppins-Regular.ttf"))
    create_fonts()

    try:
        root.configure(bg=BG_MAIN)
    except NameError:
        pass

    # style widgets recursively
    def recursive_style(widget, parent_is_main_card=False):
        for child in widget.winfo_children():
            try:
                cname = child.__class__.__name__
                # Nested ID and action frames remain borderless
                skip_border = cname == "Frame" and parent_is_main_card and child in [inputs_frame, controls_frame]
                if cname == "Frame":
                    if skip_border:
                        child.configure(bg=PANEL_BG, bd=0, relief="flat")
                    else:
                        # All other sections get distinctive border
                        child.configure(bg=PANEL_BG, bd=2, relief="solid", highlightbackground=CARD_BORDER)
                elif cname == "Label":
                    child.configure(bg=PANEL_BG, fg=TEXT, font=tk_font_small)
                elif cname == "Entry":
                    style_entry(child)
                elif cname == "Button":
                    child.configure(bg=ACCENT, fg="white", font=tk_font_small, activebackground=ACCENT_DARK)
                elif cname == "OptionMenu":
                    # remove any white borders in dark mode and use CARD_BORDER
                    style_optionmenu(child)
                    child.configure(highlightbackground=CARD_BORDER)
                elif cname == "Radiobutton":
                    child.configure(bg=PANEL_BG, fg=TEXT, font=tk_font_smedium, selectcolor=PANEL_BG, activebackground=PANEL_BG, activeforeground=TEXT)
                elif cname == "Checkbutton":
                    child.configure(bg=PANEL_BG, fg=TEXT, selectcolor=PANEL_BG)
                elif cname == "Scale":
                    # Improve slider aesthetics for dark mode:
                    try:
                        child.configure(bg=PANEL_BG, fg=TEXT, highlightbackground=CARD_BORDER, troughcolor=ACCENT_DARK, activebackground=ACCENT)
                        # set sliderlength and width proportionally (best-effort)
                        child.configure(sliderlength=max(12, int(22 * ui_scale)), width=max(8, int(10 * ui_scale)))
                    except Exception:
                        pass
            except Exception:
                pass
            recursive_style(child, parent_is_main_card=(cname == "Frame" and child == main_card))

    try:
        recursive_style(root)
    except Exception:
        pass

    try:
        footer_label.configure(bg=BG_MAIN, fg=FOOTER_TEXT, font=tk_font_small)
    except Exception:
        pass

# --------------------------
# Popup + shadow helper
# --------------------------
def create_popup_with_shadow(parent, base_width, base_height, title="Popup"):
    """
    Creates a Toplevel popup with a subtle shadow frame behind the main card in dark mode.
    base_width/base_height are logical (pre-ui_scale) sizes; card sizes are multiplied by ui_scale.
    Returns (popup_window, card_frame).
    """
    popup = Toplevel(parent)
    popup.title(title)
    popup.configure(bg=BG_MAIN)
    popup.focus_force()
    popup.resizable(False, False)

    # compute scaled sizes
    w = int(base_width * ui_scale)
    h = int(base_height * ui_scale)

    # shadow offset for dark mode (larger offset gives more pronounced shadow)
    shadow_offset = int(6 * ui_scale) if ui_theme == "Dark" else 0
    shadow_color = "#1A1A1A" if ui_theme == "Dark" else PANEL_BG

    # place shadow (slightly larger) behind
    shadow = tk.Frame(popup, bg=shadow_color, bd=0, relief="flat")
    shadow.place(relx=0.5, rely=0.5, anchor="center", width=max(2, w + shadow_offset), height=max(2, h + shadow_offset))

    # main card (above shadow)
    card = tk.Frame(popup, bg=PANEL_BG, bd=2, relief="solid", highlightbackground=CARD_BORDER)
    card.place(relx=0.5, rely=0.5, anchor="center", width=w, height=h)

    # center & fit using the card size but apply popup_scale so the window is slightly larger than content
    center_and_fit(popup, card, pad_x=int(80 * ui_scale), pad_y=int(80 * ui_scale), scale_factor=popup_scale)
    return popup, card

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
    new_window, card = create_popup_with_shadow(root, base_width=460, base_height=260, title="Enter Name")
    new_window.configure(bg=BG_MAIN)

    try:
        card.configure(highlightbackground=CARD_BORDER)
    except Exception:
        pass

    Label(card, text="Enter your first AND last name:", bg=PANEL_BG, fg=TEXT, font=tk_font_small, wraplength=int(380 * ui_scale), justify="center").pack(pady=(int(16 * ui_scale), int(6 * ui_scale)))

    name_entry = Entry(card, font=tk_font_small, bd=0, justify="center", bg=INPUT_BG, width=34)
    name_entry.pack(fill="x", pady=4, ipadx=int(10 * ui_scale), ipady=int(8 * ui_scale))
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
    btn_frame.pack(pady=(int(8 * ui_scale), int(12 * ui_scale)), fill="x", padx=int(18 * ui_scale))
    submit_btn = tk.Button(btn_frame, text="Submit", command=save_name, bg=ACCENT, fg="white",
                           font=tk_font_small, bd=0, activebackground=ACCENT_DARK, padx=int(12 * ui_scale), pady=int(8 * ui_scale))
    submit_btn.pack(side="right")

    # Bind Enter to submit (both on the entry and the popup window)
    name_entry.bind("<Return>", lambda e: save_name())
    new_window.bind("<Return>", lambda e: save_name())

    new_window.transient(root)
    new_window.grab_set()
    root.wait_window(new_window)

# Show a "Smile!" confirmation card and then take a picture after a short delay.
def open_smile_window(current_id, name):
    smile_window, card = create_popup_with_shadow(root, base_width=480, base_height=320, title="Smile!")
    try:
        card.configure(highlightbackground=CARD_BORDER)
    except Exception:
        pass

    display_smile_message(card)
    # ensure the window is sized to the scaled content
    center_and_fit(smile_window, card, pad_x=int(80 * ui_scale), pad_y=int(80 * ui_scale), scale_factor=popup_scale)
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
    fail_window, card = create_popup_with_shadow(root, base_width=680, base_height=220, title="Camera Failure")
    fail_window.bind("<Control-o>", lambda event: process_attendance(current_id, name, False))

    try:
        card.configure(highlightbackground=CARD_BORDER)
    except Exception:
        pass

    display_fail_message(card)
    center_and_fit(fail_window, card, pad_x=int(80 * ui_scale), pad_y=int(80 * ui_scale), scale_factor=popup_scale)
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
        wraplength=int(580 * ui_scale),
        justify="center"
    )
    loading_label.pack(expand=True, fill=tk.BOTH, padx=int(12 * ui_scale), pady=int(10 * ui_scale))

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
    # replaced local sqlite write with API-backed writeData (compat wrapper)
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
    loading_window, card = create_popup_with_shadow(root, base_width=500, base_height=180, title="Loading...")
    try:
        card.configure(highlightbackground=CARD_BORDER)
    except Exception:
        pass

    display_loading_message(card)
    center_and_fit(loading_window, card, pad_x=int(80 * ui_scale), pad_y=int(80 * ui_scale), scale_factor=popup_scale)
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
        wraplength=int(420 * ui_scale),
        justify="center"
    )
    loading_label.pack(expand=True, fill=tk.BOTH, padx=int(12 * ui_scale), pady=int(12 * ui_scale))

# Popup for selecting a volunteering event when "Volunteering" is selected.
def volunteering_event_window():
    new_window, card = create_popup_with_shadow(root, base_width=460, base_height=260, title="Select An Event")

    try:
        card.configure(highlightbackground=CARD_BORDER)
    except Exception:
        pass

    Label(card, text="Select your volunteering event:", bg=PANEL_BG, fg=TEXT, font=tk_font_small).pack(pady=(int(14 * ui_scale), int(8 * ui_scale)))

    volunteering_var = StringVar(value="None")
    eventDropdown = OptionMenu(card, volunteering_var, *volunteeringList)
    eventDropdown.configure(font=tk_font_small)
    style_optionmenu(eventDropdown)
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
           font=tk_font_small, activebackground=ACCENT_DARK, padx=int(12 * ui_scale), pady=int(8 * ui_scale)).pack(pady=(int(8 * ui_scale), int(12 * ui_scale)))

    # Bind Enter to submit the selected event (both on window and on dropdown)
    new_window.bind("<Return>", lambda e: returnEvent())
    try:
        eventDropdown.bind("<Return>", lambda e: returnEvent())
    except Exception:
        pass

    center_and_fit(new_window, card, pad_x=int(80 * ui_scale), pad_y=int(80 * ui_scale), scale_factor=popup_scale)
    new_window.transient(root)
    new_window.grab_set()
    root.wait_window(new_window)
    return event



# Ask user for a reason to early sign out; return the collected reason string.
def early_sign_out():
    reason_window, card = create_popup_with_shadow(root, base_width=460, base_height=220, title="Reason for Early Sign-Out")
    try:
        card.configure(highlightbackground=CARD_BORDER)
    except Exception:
        pass

    Label(card, text="Enter reason for early sign-out:", bg=PANEL_BG, fg=TEXT, font=tk_font_small, wraplength=int(380 * ui_scale)).pack(pady=(int(12 * ui_scale), int(6 * ui_scale)))
    reason_entry = Entry(card, font=tk_font_small, bd=0, bg=INPUT_BG)
    reason_entry.pack(pady=5, ipadx=int(6 * ui_scale), ipady=int(8 * ui_scale))
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
           font=tk_font_small, activebackground=ACCENT_DARK, padx=int(12 * ui_scale), pady=int(8 * ui_scale)).pack(pady=(int(8 * ui_scale), int(10 * ui_scale)))

    # Bind Enter both on the entry and on the window
    reason_entry.bind("<Return>", lambda e: save_reason())
    reason_window.bind("<Return>", lambda e: save_reason())

    center_and_fit(reason_window, card, pad_x=int(80 * ui_scale), pad_y=int(80 * ui_scale), scale_factor=popup_scale)
    reason_window.transient(root)
    reason_window.grab_set()
    root.wait_window(reason_window)
    reason = "Early sign out: " + reason
    return reason

# Ask user for a reason to late sign in; return the collected reason string.
def late_sign_in():
    reason_window, card = create_popup_with_shadow(root, base_width=460, base_height=220, title="Reason for Late Sign-In")
    try:
        card.configure(highlightbackground=CARD_BORDER)
    except Exception:
        pass

    Label(card, text="Enter reason for late sign-in:", bg=PANEL_BG, fg=TEXT, font=tk_font_small, wraplength=int(380 * ui_scale)).pack(pady=(int(12 * ui_scale), int(6 * ui_scale)))
    reason_entry = Entry(card, font=tk_font_small, bd=0, bg=INPUT_BG)
    reason_entry.pack(pady=5, ipadx=int(6 * ui_scale), ipady=int(8 * ui_scale))
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
           font=tk_font_small, activebackground=ACCENT_DARK, padx=int(12 * ui_scale), pady=int(8 * ui_scale)).pack(pady=(int(8 * ui_scale), int(10 * ui_scale)))

    # Bind Enter
    reason_entry.bind("<Return>", lambda e: save_reason())
    reason_window.bind("<Return>", lambda e: save_reason())

    center_and_fit(reason_window, card, pad_x=int(80 * ui_scale), pad_y=int(80 * ui_scale), scale_factor=popup_scale)
    reason_window.transient(root)
    reason_window.grab_set()
    root.wait_window(reason_window)
    reason = "Late Sign In: " + reason
    return reason

# --------------------------
# Build main UI (fonts created before widgets)
# --------------------------
root = tk.Tk()
root.title("Attendance System")
center_window(root, width=int(1000*ui_scale), height=int(720*ui_scale))

action_var = StringVar(value="in")
event_var = StringVar(value="Internship")

root.attributes("-fullscreen", True)
root.bind("<Escape>", lambda event: root.attributes("-fullscreen", False))

load_private_font(os.path.join("fonts", "Poppins-Regular.ttf"))
create_fonts()

# Header
header = tk.Frame(root, bg="#FFFFFF", bd=1, relief="solid")
header.pack(fill="x", padx=int(24*ui_scale), pady=(int(20*ui_scale), int(10*ui_scale)))
header_title = Label(header, text="Attendance System", font=tk_font_large, bg="#FFFFFF", fg="#1F2D3D")
header_title.pack(side="left", padx=int(20*ui_scale), pady=int(18*ui_scale))

# Options button
options_btn = tk.Button(header, text="⚙️ Options", command=lambda: open_options_window(), bg="#FFFFFF", fg="#1F2D3D",
                        font=tk_font_small, bd=0, activebackground="#0B63C7")
options_btn.pack(side="right", padx=int(16*ui_scale), pady=int(12*ui_scale))

# Main panel
main_card = tk.Frame(root, bg="#FFFFFF", bd=2, relief="solid")
main_card.pack(expand=True, padx=int(24*ui_scale), pady=int(12*ui_scale), ipadx=int(10*ui_scale), ipady=int(10*ui_scale))

inputs_frame = tk.Frame(main_card, bg="#FFFFFF", bd=0, relief="flat", highlightthickness=0)
inputs_frame.pack(side="left", fill="both", expand=True, padx=int(28*ui_scale), pady=int(20*ui_scale))

Label(inputs_frame, text="Enter your ID:", font=tk_font_medium, bg="#FFFFFF", fg="#1F2D3D").pack(anchor="w", pady=(int(6*ui_scale), int(8*ui_scale)))
id_entry = Entry(inputs_frame, font=tk_font_medium, bd=0, bg="#FFFFFF", justify="center")
id_entry.pack(fill="x", pady=(0, int(12*ui_scale)), ipady=int(10*ui_scale))
style_entry(id_entry)
id_entry.bind("<Return>", lambda event: scan_id())

controls_frame = tk.Frame(main_card, bg="#FFFFFF", bd=0, relief="flat", highlightthickness=0)
controls_frame.pack(side="right", fill="both", expand=True, padx=int(28*ui_scale), pady=int(20*ui_scale))

Label(controls_frame, text="Why are you here:", font=tk_font_small, bg="#FFFFFF", fg="#1F2D3D").pack(anchor="w", pady=(int(6*ui_scale), int(6*ui_scale)))
eventsList = ["Internship", "Build Season", "Volunteering"] if len(volunteeringList) > 0 else ["Internship", "Build Season"]
w = OptionMenu(controls_frame, event_var, *eventsList)
w.config(font=tk_font_small)
style_optionmenu(w)  # apply consistent border styling
w.pack(anchor="w", pady=(0, int(12*ui_scale)))
try:
    w["menu"].configure(bg=THEMES[ui_theme]["OPTION_MENU_BG"], fg=THEMES[ui_theme]["OPTION_MENU_FG"],
                       activebackground=THEMES[ui_theme]["ACCENT_DARK"], activeforeground=THEMES[ui_theme]["OPTION_MENU_FG"])
except Exception:
    pass
w.bind("<Return>", lambda e: None)

Label(controls_frame, text="Select Action:", font=tk_font_small, bg="#FFFFFF", fg="#1F2D3D").pack(anchor="w", pady=(int(6*ui_scale), int(6*ui_scale)))
Radiobutton(controls_frame, text="Sign In", font=tk_font_smedium, variable=action_var, value="in", bg="#FFFFFF").pack(anchor="w")
Radiobutton(controls_frame, text="Sign Out", font=tk_font_smedium, variable=action_var, value="out", bg="#FFFFFF").pack(anchor="w")

# Action row
action_row = tk.Frame(root, bg="#F3F6FA")
action_row.pack(fill="x", padx=int(24*ui_scale), pady=(int(6*ui_scale), int(24*ui_scale)))
enter_btn = tk.Button(action_row, text="Enter", font=tk_font_smedium, command=lambda: scan_id(),
                      bg="#1565C0", fg="white", bd=0, activebackground="#0B63C7", padx=int(18*ui_scale), pady=int(10*ui_scale))
enter_btn.pack(side="right")

# Footer
footer = tk.Frame(root, bg="#F3F6FA")
footer.pack(fill="x", padx=int(24*ui_scale), pady=(0, int(18*ui_scale)))
footer_label = Label(footer, text="Tip: Press Esc to exit fullscreen.", font=tk_font_small, bg="#F3F6FA", fg="#5D6D7E")
footer_label.pack(side="left", padx=int(6*ui_scale), pady=int(6*ui_scale))

# --------------------------
# Options dialog 
# --------------------------
def open_options_window():
    opts, card = create_popup_with_shadow(root, base_width=340, base_height=200, title="Options")
    try:
        card.configure(highlightbackground=CARD_BORDER)
    except Exception:
        pass

    # UI Scale slider
    tk.Label(card, text="UI Scale:", bg=PANEL_BG, fg=TEXT, font=tk_font_small).pack(anchor="w", padx=18, pady=(12, 4))
    scale_var = tk.DoubleVar(value=ui_scale)
    scale_slider = Scale(
        card, variable=scale_var, from_=0.5, to=2.0, resolution=0.1, orient=HORIZONTAL, length=int(200*ui_scale),
        bg=PANEL_BG, fg=TEXT,
        troughcolor=ACCENT_DARK, activebackground=ACCENT,
        sliderlength=max(12, int(22 * ui_scale)), width=max(8, int(10 * ui_scale))
    )
    scale_slider.pack(padx=18, pady=(0, 12))

    # Theme
    tk.Label(card, text="Theme:", bg=PANEL_BG, fg=TEXT, font=tk_font_small).pack(anchor="w", padx=18, pady=(4, 4))
    theme_var_local = StringVar(value=ui_theme)
    theme_menu = OptionMenu(card, theme_var_local, "Light", "Dark")
    style_optionmenu(theme_menu)
    try:
        theme_menu["menu"].configure(bg=OPTION_MENU_BG, fg=OPTION_MENU_FG,
                                     activebackground=ACCENT_DARK,
                                     activeforeground=OPTION_MENU_FG)
    except Exception:
        pass
    theme_menu.pack(anchor="w", padx=18)

    btn_frame = tk.Frame(card, bg=PANEL_BG)
    btn_frame.pack(fill="x", pady=(18, 8), padx=18)
    def apply_and_close(event_arg=None):
        nonlocal theme_var_local, scale_var
        global ui_theme, ui_scale
        ui_theme = theme_var_local.get()
        ui_scale = scale_var.get()
        apply_ui_settings()
        opts.destroy()
    apply_btn = tk.Button(btn_frame, text="Apply", command=apply_and_close, bg=ACCENT if ACCENT else THEMES["Light"]["ACCENT"], fg="white",
                          font=tk_font_small, bd=0, activebackground=ACCENT_DARK if ACCENT_DARK else THEMES["Light"]["ACCENT_DARK"], padx=int(12*ui_scale), pady=int(8*ui_scale))
    apply_btn.pack(side="right")
    close_btn = tk.Button(btn_frame, text="Close", command=lambda: opts.destroy(), bg=PANEL_BG if PANEL_BG else THEMES["Light"]["PANEL_BG"], fg=TEXT if TEXT else THEMES["Light"]["TEXT"],
                          font=tk_font_small, bd=0)
    close_btn.pack(side="right", padx=(0, 8))

    opts.bind("<Return>", lambda e: apply_and_close())

    # size card to content and center (apply popup_scale)
    card.update_idletasks()
    card_width = max(card.winfo_reqwidth(), int(340*ui_scale))
    card_height = max(card.winfo_reqheight(), int(160*ui_scale))
    card.place_configure(width=card_width, height=card_height)
    center_and_fit(opts, card, pad_x=int(80*ui_scale), pad_y=int(80*ui_scale), scale_factor=popup_scale)

# --------------------------
# Initialize UI settings
# --------------------------
apply_ui_settings()
root.mainloop()
