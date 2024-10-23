import cv2
import time


def takePic(picname, folder):
    cap = cv2.VideoCapture(0, cv2.CAP_DSHOW)  # Use DirectShow backend on Windows

    # Set lower resolution
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    # Warm up the camera
    time.sleep(2)

    ret, frame = cap.read()
    if ret:
        cv2.imwrite(f"images//{folder}//{picname}.jpg", frame)
        print(f"Image saved as '{picname}.jpg'")
    else:
        print("Error: Couldn't capture an image.")

    cap.release()
    cv2.destroyAllWindows()
