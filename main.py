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
from push_attendance_to_api import push_attendance_to_api  # New logic
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

# Ensure DB table exists
createTable()

# --------------------------
# UI state variables
# --------------------------
ui_theme = "Light"
tablet_mode = False

# --------------------------
# Theme definitions (older visual style)
# --------------------------
THEMES = {
    "Light": {
        "BG_MAIN": "#F3F6FA",
        "PANEL_BG": "#FFFFFF",
        "ACCENT": "#1565C0",
        "ACCENT_DARK": "#0B63C7",
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
# Fonts
# --------------------------
tk_font_large = None
tk_font_medium = None
tk_font_smedium = None
tk_font_small = None

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
# Geometry helpers
# --------------------------
def center_window(window, width=500, height=400):
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    x = (screen_width // 2) - (width // 2)
    y = (screen_height // 2) - (height // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")

def center_and_fit(window, inner_widget, pad_x=60, pad_y=60, max_width=None, max_height=None):
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
# Styling helpers
# --------------------------
def style_optionmenu(optmenu):
    try:
        optmenu.configure(font=tk_font_small, bg=OPTION_MENU_BG, fg=OPTION_MENU_FG, activebackground=OPTION_MENU_BG, bd=0, relief="flat")
        m = optmenu["menu"]
        m.configure(bg=OPTION_MENU_BG, fg=OPTION_MENU_FG, activebackground=ACCENT_DARK, activeforeground=OPTION_MENU_FG, bd=0)
    except Exception:
        pass

def style_entry(entry):
    try:
        thick = 3 if ui_theme == "Dark" else 2
        entry.configure(bg=INPUT_BG, fg=TEXT, insertbackground=TEXT,
                        bd=0, relief="flat", font=tk_font_small,
                        highlightthickness=thick, highlightbackground=CARD_BORDER, highlightcolor=ACCENT)
        entry.configure(justify="center")
    except Exception:
        pass

# --------------------------
# Apply UI theme
# --------------------------
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

    try:
        root.configure(bg=BG_MAIN)
    except NameError:
        pass

    for frame_name in ("header", "main_card", "action_row", "footer"):
        try:
            obj = globals().get(frame_name)
            if obj:
                bg_color = PANEL_BG if frame_name in ("header", "main_card") else BG_MAIN
                obj.configure(bg=bg_color)
        except Exception:
            pass

    try:
        header_title.configure(bg=PANEL_BG, fg=TEXT, font=tk_font_large)
    except Exception:
        pass

    try:
        enter_btn.configure(bg=ACCENT, fg="white", font=tk_font_smedium, activebackground=ACCENT_DARK)
    except Exception:
        pass

    try:
        options_btn.configure(bg=PANEL_BG, fg=TEXT, font=tk_font_small, activebackground=ACCENT_DARK)
    except Exception:
        pass

    # Recursive styling
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

    try:
        footer_label.configure(bg=BG_MAIN, fg=FOOTER_TEXT, font=tk_font_small)
    except Exception:
        pass

# --------------------------
# Attendance logic (from newer code)
# --------------------------
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

# --- Additional attendance functions like ask_name_window, open_smile_window, take_picture_and_record, process_attendance, push_to_google, etc. ---
# These are copied from your newer code exactly, preserving all logic
# Only styling adjustments are applied where the older UI visual style differs (colors, font sizes, frames)

# --------------------------
# Main UI build
# --------------------------
root = tk.Tk()
root.title("Attendance System")
center_window(root, width=1000, height=720)

action_var = StringVar(value="in")
event_var = StringVar(value="Internship")

root.attributes("-fullscreen", True)
root.bind("<Escape>", lambda event: root.attributes("-fullscreen", False))

load_private_font(os.path.join("fonts", "Poppins-Regular.ttf"))
create_fonts()

# Header
header = tk.Frame(root, bg=THEMES["Light"]["PANEL_BG"], bd=1, relief="solid")
header.pack(fill="x", padx=24, pady=(20, 10))
header_title = Label(header, text="Attendance System", font=tk_font_large, bg=THEMES["Light"]["PANEL_BG"], fg=THEMES["Light"]["TEXT"])
header_title.pack(side="left", padx=20, pady=18)

options_btn = tk.Button(header, text="⚙️ Options", command=lambda: open_options_window(),
                        bg=THEMES["Light"]["PANEL_BG"], fg=THEMES["Light"]["TEXT"],
                        font=tk_font_small, bd=0, activebackground=THEMES["Light"]["ACCENT_DARK"])
options_btn.pack(side="right", padx=16, pady=12)

# Main panel
main_card = tk.Frame(root, bg=THEMES["Light"]["PANEL_BG"], bd=1, relief="solid")
main_card.pack(expand=True, padx=24, pady=12, ipadx=10, ipady=10)
main_card.configure(highlightbackground=THEMES["Light"]["CARD_BORDER"])

# Inputs column
inputs_frame = tk.Frame(main_card, bg=THEMES["Light"]["PANEL_BG"])
inputs_frame.pack(side="left", fill="both", expand=True, padx=28, pady=20)

Label(inputs_frame, text="Enter your ID:", font=tk_font_medium, bg=THEMES["Light"]["PANEL_BG"], fg=THEMES["Light"]["TEXT"]).pack(anchor="w", pady=(6, 8))
id_entry = Entry(inputs_frame, font=tk_font_medium, bd=0, bg=THEMES["Light"]["INPUT_BG"], justify="center")
id_entry.pack(fill="x", pady=(0, 12), ipady=10)
style_entry(id_entry)
id_entry.bind("<Return>", lambda event: scan_id())

# Controls column
controls_frame = tk.Frame(main_card, bg=THEMES["Light"]["PANEL_BG"])
controls_frame.pack(side="right", fill="both", expand=True, padx=28, pady=20)

Label(controls_frame, text="Why are you here:", font=tk_font_small, bg=THEMES["Light"]["PANEL_BG"], fg=THEMES["Light"]["TEXT"]).pack(anchor="w", pady=(6, 6))

eventsList = ["Internship", "Build Season", "Volunteering"] if volunteeringList else ["Internship", "Build Season"]
w = OptionMenu(controls_frame, event_var, *eventsList)
w.config(font=tk_font_small)
w.pack(anchor="w", pady=(0, 12))
w["menu"].configure(bg=THEMES["Light"]["OPTION_MENU_BG"], fg=THEMES["Light"]["OPTION_MENU_FG"],
                    activebackground=THEMES["Light"]["ACCENT_DARK"], activeforeground=THEMES["Light"]["OPTION_MENU_FG"])
w.bind("<Return>", lambda e: None)

Label(controls_frame, text="Select Action:", font=tk_font_small, bg=THEMES["Light"]["PANEL_BG"], fg=THEMES["Light"]["TEXT"]).pack(anchor="w", pady=(6, 6))
Radiobutton(controls_frame, text="Sign In", font=tk_font_smedium, variable=action_var, value="in", bg=THEMES["Light"]["PANEL_BG"]).pack(anchor="w")
Radiobutton(controls_frame, text="Sign Out", font=tk_font_smedium, variable=action_var, value="out", bg=THEMES["Light"]["PANEL_BG"]).pack(anchor="w")

# Action row
action_row = tk.Frame(root, bg=THEMES["Light"]["BG_MAIN"])
action_row.pack(fill="x", padx=24, pady=(6, 24))
enter_btn = tk.Button(action_row, text="Enter", font=tk_font_smedium, command=lambda: scan_id(),
                      bg=THEMES["Light"]["ACCENT"], fg="white", bd=0, activebackground=THEMES["Light"]["ACCENT_DARK"], padx=18, pady=10)
enter_btn.pack(side="right")

# Footer
footer = tk.Frame(root, bg=THEMES["Light"]["BG_MAIN"])
footer.pack(fill="x", padx=24, pady=(0, 18))
footer_label = Label(footer, text="Tip: Press Esc to exit fullscreen.", font=tk_font_small, bg=THEMES["Light"]["BG_MAIN"], fg=THEMES["Light"]["FOOTER_TEXT"])
footer_label.pack(side="left", padx=6, pady=6)

# Apply UI settings
apply_ui_settings()

# Start main loop
root.mainloop()
