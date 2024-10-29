import os
from datetime import datetime
import sqlite3 as sql
import tkinter as tk
from tkinter import messagebox, Label, Entry, Button, Toplevel, Radiobutton, StringVar
from databaseMain import *
from camera import takePic

# Ensure the table is created
createTable()

# Function to center any window on the screen
def center_window(window, width=500, height=400):
    screen_width = window.winfo_screenwidth()
    screen_height = window.winfo_screenheight()
    x = (screen_width // 2) - (width // 2)
    y = (screen_height // 2) - (height // 2)
    window.geometry(f"{width}x{height}+{x}+{y}")

# Function to handle scanning the ID
def scan_id(event=None):
    """Handles the Scan ID button press or Enter key event."""
    try:
        current_id = int(id_entry.get())
        if len(str(current_id)) != 6 or current_id < 0:
            raise ValueError("Bogus ID, too long/short")
    except ValueError as e:
        messagebox.showerror("Error", f"Invalid ID: {str(e)}, AKA has letters")
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

    Label(new_window, text="Enter your name:").pack(pady=10)
    name_entry = Entry(new_window)
    name_entry.pack()

    def save_name(event=None):
        """Handles the Save Name button press or Enter key event."""
        name = name_entry.get()
        if name:
            writeName(current_id, name)
            new_window.destroy()
            open_smile_window(current_id, name)
        else:
            messagebox.showerror("Error", "Name cannot be empty.")

    # Bind the Enter key to the save_name function
    name_entry.bind("<Return>", save_name)
    Button(new_window, text="Submit", command=save_name).pack(pady=10)

# Function to open the smile window
def open_smile_window(current_id, name):
    smile_window = Toplevel(root)
    smile_window.title("Smile!")
    center_window(smile_window, width=400, height=300)

    # Display the "Smile!" message immediately
    display_smile_message(smile_window)

    # After 2 seconds, take a picture and process attendance
    smile_window.after(2000, lambda: take_picture_and_record(smile_window, current_id, name))

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
    window.destroy()  # Close the smile window

    # Take the picture
    now = datetime.now()
    folder = f"images//{current_id}-{name}"
    if not os.path.isdir(folder):
        os.makedirs(folder)

    file_date = now.strftime("%I-%M-%p-%Y-%m-%d")
    takePic(f"{name}__{file_date}", f"{current_id}-{name}")

    # Record attendance
    process_attendance(current_id, name)

# Function to process attendance
def process_attendance(current_id, name):
    now = datetime.now()
    formatted_time = now.strftime("%I:%M %p")
    formatted_date = now.strftime("%Y-%m-%d")

    # Get sign-in or sign-out action
    action = action_var.get()
    full_date = f"Signed {action} at: {formatted_time}, Date: {formatted_date}"

    # Store the attendance in the database
    conn = sql.connect('data.db')
    c = conn.cursor()
    c.execute('INSERT INTO attendance (id, name, date) VALUES (?, ?, ?)',
              (current_id, name, full_date))
    conn.commit()
    conn.close()

    # Confirm attendance recording
    messagebox.showinfo("Attendance Recorded", f"Name: {name}\n{full_date}")

# Initialize the Tkinter window
root = tk.Tk()
root.title("Attendance System")
center_window(root)

# Variable to hold the selected action (sign-in or sign-out)
action_var = StringVar(value="in")  # Default to "in"

# GUI Layout
Label(root, text="Attendance System", font=("Arial", 24)).pack(pady=10)

Label(root, text="Enter your ID:").pack(pady=5)
id_entry = Entry(root, width=30)
id_entry.pack(pady=5)
id_entry.bind("<Return>", scan_id)  # Bind Enter key to scan_id function

# Radio buttons for selecting sign-in or sign-out
Label(root, text="Select Action:").pack(pady=5)
Radiobutton(root, text="Sign In", variable=action_var, value="in").pack()
Radiobutton(root, text="Sign Out", variable=action_var, value="out").pack()

# Scan ID Button
Button(root, text="Scan ID", command=scan_id).pack(pady=10)

# Start the Tkinter event loop
root.mainloop()
