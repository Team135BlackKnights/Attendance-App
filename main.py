from databaseMain import *
from datetime import datetime
import time

# Get current date and time
now = datetime.now()

# Format the time in 12-hour format with AM/PM
formatted_time = now.strftime("%I:%M %p")  # %I for 12-hour format, %M for minutes, %p for AM/PM
formatted_date = now.strftime("%Y-%m-%d") 

fullDate = f"Time out: {formatted_time}, Date out: {formatted_date}"
print(fullDate)

# Ensure the table is created
createTable()

# Ask for the ID
id = input("Scan the id: ")

# Check if the ID already exists in any previous entry
name = getName(id)  # Try to fetch the name associated with this ID

# If the name doesn't exist, ask for it
if name is None:
    name = input("Give your name: ")
    writeId(id)  # This stores the ID the first time

# Insert a new entry with the current date and name
conn = sql.connect('data.db')
c = conn.cursor()
c.execute('INSERT INTO attendance (id, name, date) VALUES (?, ?, ?)', (id, name, fullDate))
conn.commit()
conn.close()

# Display the confirmation
print(f"Name: {name}")
print(f"Date and Time: {fullDate}")