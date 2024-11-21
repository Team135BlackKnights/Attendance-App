import subprocess
import sys

# List of required dependencies
dependencies = [
    "pillow", "gspread", "google-api-python-client",
    "oauth2client", "sqlite3", "tk", "pyglet", "opencv-python"
]

def install_dependencies():
    """Installs required dependencies if not already installed."""
    for package in dependencies:
        try:
            __import__(package)  # Check if the package is installed
        except ImportError:
            print(f"Installing {package}...")
            subprocess.check_call([sys.executable, "-m", "pip", "install", package])

# Install dependencies
install_dependencies()
