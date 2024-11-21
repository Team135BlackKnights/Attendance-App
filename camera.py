# Code for taking and saving a picture

import cv2
import time
import os

''' Theoretical version if I can make the folder secure
def takePic(picname, folder):
    # Check if the folder path exists, and create it if it doesn’t
    directory = f"S:/Robotics/Attendance Images/{folder}"
    if not os.path.exists(directory):
        try:
            os.makedirs(directory)
        except Exception as e:
            print(f"Error: Couldn't create directory {directory}. Exception: {e}")
            return

    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)  # Use DirectShow backend on Windows

    # Set lower resolution
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    # Warm up the camera
    time.sleep(2)

    ret, frame = cap.read()
    if ret:
        try:
            cv2.imwrite(f"{directory}/{picname}.jpg", frame)
            print(f"Image saved as '{picname}.jpg' in '{directory}'")
        except Exception as e:
            print(f"Error: Couldn't save the image. Exception: {e}")
    else:
        print("Error: Couldn't capture an image.")

    cap.release()
    cv2.destroyAllWindows()
    '''

def takePic(picname, folder):
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)  # Use DirectShow backend on Windows

    # Set lower resolution
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    # Warm up the camera
    time.sleep(2)

    ret, frame = cap.read()
    if ret:
        cv2.imwrite(f"images/{folder}/{picname}.jpeg", frame)
        print(f"Image saved as '{picname}.jpg'")
    else:
        print("Error: Couldn't capture an image.")

    cap.release()
    cv2.destroyAllWindows()

