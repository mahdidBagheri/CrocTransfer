import os
import sys
import subprocess
import random
import string
import logging

def setup_logging(log_file='croc_debug.log'):
    """Configures the global logging format and file."""
    logging.basicConfig(
        filename=log_file,
        level=logging.DEBUG,
        format='%(asctime)s - %(levelname)s - %(message)s'
    )
    logging.info("=== Croc GUI Started ===")

def get_7z_path():
    """Finds the 7-Zip executable path depending on the OS."""
    if sys.platform == 'win32':
        paths = [r"C:\Program Files\7-Zip\7z.exe", r"C:\Program Files (x86)\7-Zip\7z.exe"]
        for p in paths:
            if os.path.exists(p):
                return p
    try:
        subprocess.run(["7z"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return "7z"
    except FileNotFoundError:
        return None

def generate_transfer_code(length=6):
    """Generates a random, easy-to-read transfer code."""
    chars = string.ascii_lowercase + string.digits
    prefixes = ["send", "data", "blue", "red", "fast"]
    random_str = ''.join(random.choices(chars, k=length))
    return f"{random.choice(prefixes)}-{random_str}"