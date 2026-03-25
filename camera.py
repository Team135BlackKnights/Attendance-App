"""
Camera capture utilities for the Attendance App.

Captures a single frame from the default webcam (DirectShow backend on Windows),
applies gamma correction to improve image brightness, and saves it as a JPEG.

Public functions:
    increase_gamma  -- Apply gamma correction to a BGR image array.
    takePic         -- Capture one frame from the webcam and save it to disk.
"""

import cv2
import numpy as np
import time
import os

def increase_gamma(image, gamma=2):
    """Apply gamma correction to brighten a BGR image.

    Builds a lookup table mapping each pixel value [0, 255] through the
    inverse-gamma power curve and applies it via cv2.LUT for efficiency.

    Args:
        image: A NumPy array in BGR format (as returned by cv2.read).
        gamma: Gamma exponent.  Values > 1 brighten; < 1 darken.  Default is 2.

    Returns:
        A new NumPy array of the same shape with corrected pixel values.
    """
    # Build a lookup table for gamma correction
    inv_gamma = 1.0 / gamma
    table = np.array([((i / 255.0) ** inv_gamma) * 255 for i in range(256)], dtype=np.uint8)
    return cv2.LUT(image, table)

def takePic(picname, folder):
    """Capture a single frame from the default webcam and save it as a JPEG.

    Opens camera index 0 (DirectShow backend on Windows), reads one frame,
    applies gamma correction, then writes the image to
    ``images/<folder>/<picname>.jpeg``.

    Args:
        picname: Base filename (no extension) for the saved image.
        folder:  Subdirectory inside ``images/`` where the file is written.
                 The caller is responsible for ensuring the directory exists.

    Returns:
        None on success; the string ``"fail"`` if the frame could not be read.
    """
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)  # Use DirectShow backend on Windows

    # Set lower resolution
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    ret, frame = cap.read()
    if ret:
        # Apply gamma correction
        frame_gamma_corrected = increase_gamma(frame)

        # Save the image with the corrected gamma
        cv2.imwrite(f"images/{folder}/{picname}.jpeg", frame_gamma_corrected)
        print(f"Image saved as '{picname}.jpeg'.")
    else:
        print("Error: Couldn't capture an image.")
        return("fail")

    cap.release()
    cv2.destroyAllWindows()