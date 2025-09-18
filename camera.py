# Code for taking and saving a picture

import cv2
import numpy as np
import time
import os

def increase_gamma(image, gamma=2):
    # Build a lookup table for gamma correction
    inv_gamma = 1.0 / gamma
    table = np.array([((i / 255.0) ** inv_gamma) * 255 for i in range(256)], dtype=np.uint8)
    return cv2.LUT(image, table)

def takePic(picname, folder):
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)  # Use DirectShow backend on Windows

    # Set lower resolution
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    ret, frame = cap.read()
    if ret:
        # Apply gamma correction
        frame_gamma_corrected = increase_gamma(frame, 3)

        # Save the image with the corrected gamma
        cv2.imwrite(f"images/{folder}/{picname}.jpeg", frame_gamma_corrected)
        print(f"Image saved as '{picname}.jpeg'.")
    else:
        print("Error: Couldn't capture an image.")

    cap.release()
    cv2.destroyAllWindows()