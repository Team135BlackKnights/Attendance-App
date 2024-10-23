from databaseMain import *
from camera import *
from datetime import datetime
import time
import os

# Ensure the table is created
createTable()

# Ask for the ID
while True:
    id = input("Scan the id: ")
    try:
        id = int(id)
    except ValueError:
        print("Bogus ID, has letters")
        continue
    if len(str(id)) != 6 or id < 0:
        print("Bogus ID, not PHM compliant")
        continue
    break

# Check if the ID already exists in any previous entry
name = getName(id)  # Try to fetch the name associated with this ID
# If the name doesn't exist, ask for it
if name is None:
    name = input("What's your name?: ")
    writeName(id, name)  # This stores the ID the first time
print(f"Hello {name}")
# Get current date and time
now = datetime.now()

# Format the time in 12-hour format with AM/PM
formatted_time = now.strftime("%I:%M %p")  # %I for 12-hour format, %M for minutes, %p for AM/PM
formatted_date = now.strftime("%Y-%m-%d") 

fullDate = f"Time scanned: {formatted_time}, Date scanned: {formatted_date}"

print(fullDate)

#Record a picture
fileDate = now.strftime("%I-%M-%p-%Y-%m-%d")
print("Smile! Look into the green light.")
if not os.path.isdir(f"images//{id}-{name}"):
    os.makedirs(f"images//{id}-{name}")
pic = takePic((name + "__" + fileDate), f"{id}-{name}")
print(pic)

# Insert a new entry with the current date and name
conn = sql.connect('data.db')
c = conn.cursor()
c.execute('INSERT INTO attendance (id, name, date) VALUES (?, ?, ?)', (id, name, fullDate))
conn.commit()
conn.close()

# Display the confirmation
print(f"Name: {name}")
print(f"Date and Time: {fullDate}")