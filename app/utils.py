# app/utils.py
from datetime import datetime

def get_formatted_timestamp():
    """Returns a string timestamp like YYYYMMDD_HHMMSS_ffffff"""
    return datetime.now().strftime('%Y%m%d_%H%M%S_%f')

# You can add other helper functions here later