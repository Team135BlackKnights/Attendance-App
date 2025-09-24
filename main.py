import os
from PIL import ImageFont
from datetime import datetime
import sqlite3 as sql
import tkinter as tk
from tkinter import messagebox, Label, Entry, Button, Toplevel, Radiobutton, StringVar, OptionMenu
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

# Ensure the table is created
createTable()

#Get the list of open sheets
global volunteeringList
volunteeringList = list_sheets()
print(volunteeringList)
#Removes the first two values, which are always the same and not volunteering
volunteeringList.pop(0)
volunteeringList.pop(0)


# Function to handle scanning the ID
def scan_id(event=None):
    """Handles the Scan ID button press or Enter key event."""
    try:
        current_id = int(id_entry.get())
        if len(str(current_id)) != 6 or current_id < 0:
            raise ValueError("Invalid length")
    except ValueError as e:
        messagebox.showerror("Error", f"Invalid ID: {str(e)}")
        return

    id_entry.delete(0, tk.END)  # Clear the ID entry box

    # Fetch name from the database
    name = getName(current_id)
    if not name:  # If name is not found, prompt to enter a new one
        ask_name_window(current_id)
    else:  # If found, proceed to attendance and photo
        open_smile_window(current_id, name)

# Function to open a window for entering a new name
def ask_name_window(current_id):
    new_window = Toplevel(root)
    new_window.title("Enter Name")
    center_window(new_window, width=300, height=200)

    # Make the new window auto-focused
    new_window.focus_force()

    Label(new_window, text="Enter your first AND last name:").pack(pady=10)
    name_entry = Entry(new_window)
    name_entry.pack()

    # Focus the entry field as soon as the window opens
    name_entry.focus()

    def save_name(event=None):
        """Handles the Save Name button press or Enter key event."""
        name = name_entry.get()
        name = name.capitalize()
        
        if name:
            writeName(current_id, name)
            new_window.destroy()
            open_smile_window(current_id, name)
        else:
            messagebox.showerror("Error", "Name cannot be empty.", parent = new_window)

    # Bind the Enter key to the save_name function
    name_entry.bind("<Return>", save_name)
    Button(new_window, text="Submit", command=save_name).pack(pady=10)

# Function to open the smile window
def open_smile_window(current_id, name):
    smile_window = Toplevel(root)
    smile_window.title("Smile!")
    center_window(smile_window, width=400, height=300)

    # Make the smile window auto-focused
    smile_window.focus_force()

    # Display the "Smile!" message immediately
    display_smile_message(smile_window)

    # After half a second, take a picture and process attendance
    smile_window.after(500, lambda: take_picture_and_record(smile_window, current_id, name))

# Function to display a styled "Smile!" message
def display_smile_message(window):
    for widget in window.winfo_children():
        widget.destroy()  # Clear existing widgets

    smile_label = Label(
        window,
        text="😊 Smile! 😊",
        font=("Helvetica", 32, "bold"),
        fg="#4CAF50",
        bg="#FFFFFF"
    )
    smile_label.pack(expand=True, fill=tk.BOTH)

# Function to take a picture and record attendance
def take_picture_and_record(window, current_id, name):
    

    # Take the picture
    now = datetime.now()
    global folder
    folder = f"images/{current_id}-{name}"
    if not os.path.isdir(folder):
        os.makedirs(folder)

    file_date = now.strftime("%I-%M-%p-%Y-%m-%d")
    global picName
    picName = f"{name}__{file_date}.jpeg"
    confirmation = takePic(f"{name}__{file_date}", f"{current_id}-{name}")

    window.destroy()  # Close the smile window

    if (confirmation == None):
        # Record attendance and push to Google Sheets
        process_attendance(current_id, name)
    else:
        open_fail_window(current_id, name)


def open_fail_window(current_id, name):
    fail_window = Toplevel(root)
    fail_window.title("Camera Failure")
    center_window(fail_window, width=550, height=175)

    fail_window.focus_force()
    #Override to push without picture data
    fail_window.bind("<Control-o>", lambda event: process_attendance(current_id, name, False))

    display_fail_message(fail_window)

    return(fail_window)


# Function to display a loading screen
def display_fail_message(window):
    for widget in window.winfo_children():
        widget.destroy()  # Clear existing widgets

    loading_label = Label(
        window,
        text="Failed to take a picture, try again.",
        font=("Helvetica", 26, "bold"),
        fg="#CA2B16",
        bg="#FFFFFF"
    )
    loading_label.pack(expand=True, fill=tk.BOTH)
    

# Function to process attendance
def process_attendance(current_id, name, hasPic = True):
    now = datetime.now()
    formatted_time = now.strftime("%I:%M %p")
    formatted_date = now.strftime("%Y-%m-%d")

    # Get sign-in or sign-out 
    action = action_var.get()
    # Get event
    event = event_var.get()

    # Checks what the event is, will put the event in the "Reason" collumn if not Internship
    # If is Internship: Check if the action is performed at the correct time and if not, asks for a reason they are late/early
    reason = None
    if event == "Internship":
        if action == "out":
            if now.hour < 18 or (now.hour == 18 and now.minute < 45):
                reason = early_sign_out()  # Ask for reason
            else:
                reason = None
        else:
            if now.hour > 15 or (now.hour == 15 and now.minute > 45):
                reason = late_sign_in()  # Ask for reason
            else:
                reason = None
    elif event == "Volunteering":
        reason = volunteering_event_window()
    elif event == "Build Season":
        reason = "Build Season"
            

    full_date = f"Signed {action} at: {formatted_time}, Date: {formatted_date}"

    # Store the attendance in the database
    writeData(current_id, name, full_date, reason)
    
    # Display a loading screen
    load = open_loading_window()

    # Push data to Google Sheets on a seperate thread so the loading screen can render in
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


def open_loading_window():
    loading_window = Toplevel(root)
    loading_window.title("Loading...")
    center_window(loading_window, width=400, height=125)


    # Make the  window auto-focused
    loading_window.focus_force()

    # Display the message immediately
    display_loading_message(loading_window)

    return(loading_window)


# Function to display a loading screen
def display_loading_message(window):
    for widget in window.winfo_children():
        widget.destroy()  # Clear existing widgets

    loading_label = Label(
        window,
        text="Loading, please wait...",
        font=("Helvetica", 26, "bold"),
        fg="#4CAF50",
        bg="#FFFFFF"
    )
    loading_label.pack(expand=True, fill=tk.BOTH)

# Function to open a window for entering a new name
def volunteering_event_window():
    new_window = Toplevel(root)
    new_window.title("Select An Event")
    center_window(new_window, width=300, height=200)

    # Make the new window auto-focused
    new_window.focus_force()


    Label(new_window, text="Select your volunteering event:").pack(pady=10)

    volunteering_var = StringVar(value= "None") # Default to "None"
    eventDropdown = OptionMenu(new_window, volunteering_var, *volunteeringList)
    eventDropdown.config(font=tk_font_small)
    eventDropdown.pack()

    event = None

    def returnEvent():
        """Handles the button press."""
        nonlocal event
        event = volunteering_var.get()
        
        if event == "None":
            messagebox.showerror("Error", "Select an event", parent = new_window)
        else:
            new_window.destroy()
            print(event)   
     
    Button(new_window, text="Submit", command=lambda: returnEvent()).pack(pady=10)
    root.wait_window(new_window)  # Wait until the window is closed
    return event  # Return the event after the window is closed

def push_to_google(current_id, name, attendance_record, event, reason, load, hasPic = True):
    """Push attendance data to Google Sheets and put the images in a folder"""
    try:
        spreadsheet = setup_google_sheet()
        drive = setup_google_drive()
        
        if (hasPic):
            # Define file to upload
            file_path = f"{folder}/{picName}"   # image file path
            print(file_path)
            
            # Upload image to the subfolder and get its URL
            file_url = upload_image_to_drive(drive, file_path)
        else:
            file_path = "No Image"
            file_url = "No Image"
        
        # Append a new row with the data
        if (reason not in volunteeringList) and reason != "Build Season" :
            sheet = spreadsheet.worksheet("Main Attendance")  # Select the correct sheet
            sheet.append_row([current_id, name, attendance_record, file_path, file_url, reason])  
        elif reason == "Build Season":
            sheet = spreadsheet.worksheet("Build Season")  
            sheet.append_row([current_id, name, attendance_record, file_path, file_url, reason]) 
        else:
            sheet = spreadsheet.worksheet(reason)  
            sheet.append_row([current_id, name, attendance_record, file_path, file_url]) 

    finally:
        # Close loading window and show confirmation
        root.after(0, load.destroy)
        root.after(0, lambda: messagebox.showinfo(
            "Attendance Recorded", 
            f"Name: {name}\n{attendance_record}\nReason: {reason if reason else 'N/A'}"
        ))       





def early_sign_out():
    reason_window = Toplevel(root)
    reason_window.title("Reason for Early Sign-Out")
    center_window(reason_window, width=300, height=150)

    # Make the reason window auto-focused
    reason_window.focus_force()

    Label(reason_window, text="Enter reason for early sign-out:").pack(pady=10)
    reason_entry = Entry(reason_window)
    reason_entry.pack(pady=5)

    # Focus the entry field as soon as the window opens
    reason_entry.focus()

    reason = None  # Declare reason variable

    def save_reason():
        """Handles the Save Reason button press."""
        nonlocal reason  # Use the nonlocal declaration to access the outer variable
        reason = reason_entry.get()
        if reason:
            reason_window.destroy()
        else:
            messagebox.showerror("Error", "Reason cannot be empty.", parent = reason_window)


    # Bind the Enter key to the save_reason function
    reason_entry.bind("<Return>", lambda event: save_reason())

    Button(reason_window, text="Submit", command=save_reason).pack(pady=10)
    root.wait_window(reason_window)  # Wait until the window is closed
    reason = "Early sign out: " + reason
    return reason  # Return the reason after the window is closed

def late_sign_in():
    reason_window = Toplevel(root)
    reason_window.title("Reason for Late Sign-In")
    center_window(reason_window, width=300, height=150)

    # Make the reason window auto-focused
    reason_window.focus_force()

    Label(reason_window, text="Enter reason for late sign-in:").pack(pady=10)
    reason_entry = Entry(reason_window)
    reason_entry.pack(pady=5)

    # Focus the entry field as soon as the window opens
    reason_entry.focus()

    reason = None  # Declare reason variable

    def save_reason():
        """Handles the Save Reason button press."""
        nonlocal reason  # Use the nonlocal declaration to access the outer variable
        reason = reason_entry.get()
        if reason:
            reason_window.destroy()
        else:
            messagebox.showerror("Error", "Reason cannot be empty.", parent = reason_window)


    # Bind the Enter key to the save_reason function
    reason_entry.bind("<Return>", lambda event: save_reason())

    Button(reason_window, text="Submit", command=save_reason).pack(pady=10)
    root.wait_window(reason_window)  # Wait until the window is closed
    reason = "Late Sign In: " + reason
    return reason  # Return the reason after the window is closed


# Function to center any window on the screen
def center_window(window, width=500, height=400):
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    x = (screen_width // 2) - (width // 2)
    y = (screen_height // 2) - (height // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")


# Initialize the Tkinter window
root = tk.Tk()
root.title("Attendance System")
center_window(root)

# Make the window fullscreen
root.attributes("-fullscreen", True)
# Exit fullscreen with the Escape key
root.bind("<Escape>", lambda event: root.attributes("-fullscreen", False))

# Make custom font, must be intalled on system lest it default to Ariel
font_path = "Poppins-Regular"  
tk_font_large = font.Font(family="Poppins", size=48)
tk_font_medium = font.Font(family="Poppins", size=36)
tk_font_smedium = font.Font(family="Poppins", size=28)
tk_font_small = font.Font(family="Poppins", size=18)

# Variable to hold the selected action (sign-in or sign-out)
action_var = StringVar(value="in")  # Default to "in"
# Variable to help the selected event (Internship, Volunteering, or Build Season)
event_var = StringVar(value= "Internship") # Default to "Internship"

# GUI Layout
Label(root, text="Attendance System", font=tk_font_large).pack(pady=10)

Label(root, text="Enter your ID:", font=tk_font_medium).pack(pady=5)
id_entry = Entry(root, font=tk_font_medium)
id_entry.pack(pady=5)
id_entry.bind("<Return>", lambda event: scan_id())  # Bind Enter key to scan_id function

# Dropdown menu for specific event leading to being in the lab
Label(root, text="Why are you here:", font=tk_font_small).pack(pady=5)
if len(volunteeringList) > 0:
    eventsList = ["Internship", "Build Season", "Volunteering"]
else :
    eventsList = ["Internship", "Build Season"]
w = OptionMenu(root, event_var, *eventsList)
w.config(font=tk_font_small)
w.pack()

# Radio buttons for selecting sign-in or sign-out
Label(root, text="Select Action:", font=tk_font_small).pack(pady=5)
Radiobutton(root, text="Sign In", font=tk_font_smedium, variable=action_var, value="in").pack()
Radiobutton(root, text="Sign Out", font=tk_font_smedium, variable=action_var, value="out").pack()

# Scan ID Button
Button(root, text="Enter", font=tk_font_smedium, command=lambda: scan_id()).pack(pady=10)

# Start the Tkinter event loop
root.mainloop()