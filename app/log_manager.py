# app/log_manager.py
import csv
import os
import logging
from threading import Lock # For thread-safe file writing
from datetime import datetime # For ISO timestamp formatting

logger = logging.getLogger(__name__)

LOG_FILE_NAME = 'image_capture_log.csv'
LOG_FILE_PATH = None # Will be set in init_logging
CSV_HEADER = [
    'rpi_iso_timestamp',
    'rpi_image_id',
    'saved_filename',
    'image_size_bytes',
    'fetch_duration_ms',
    'esp32_url_used'
]

_log_file_lock = Lock() # To prevent concurrent writes to the CSV

def init_logging(upload_folder_path):
    """
    Initializes the logging system, creating the log file and writing headers if needed.
    Should be called once when the Flask app starts.
    """
    global LOG_FILE_PATH
    # Place log file in the 'output' directory within the project root
    LOG_FILE_PATH = os.path.join(os.path.dirname(upload_folder_path), LOG_FILE_NAME)
    
    logger.info(f"Image capture log will be saved to: {LOG_FILE_PATH}")

    with _log_file_lock:
        try:
            # Check if file exists to avoid writing headers multiple times
            file_exists = os.path.isfile(LOG_FILE_PATH)
            
            # Open in append mode ('a'), create if not exists ('+'), newline='' for csv
            with open(LOG_FILE_PATH, mode='a+', newline='') as csvfile:
                writer = csv.writer(csvfile)
                if not file_exists or os.path.getsize(LOG_FILE_PATH) == 0:
                    writer.writerow(CSV_HEADER)
                    logger.info(f"CSV log header written to {LOG_FILE_PATH}")
        except IOError as e:
            logger.error(f"Error initializing log file {LOG_FILE_PATH}: {e}")


def log_capture_event(rpi_datetime_obj, rpi_image_id, saved_filename, 
                      image_size_bytes, fetch_duration_ms, esp32_url_used): # Changed first arg
    """
    Logs a single image capture event to the CSV file.
    """
    if LOG_FILE_PATH is None:
        logger.error("Log file path not initialized. Call init_logging first.")
        return

    # Format the datetime object to ISO 8601 string for consistent logging
    rpi_iso_timestamp_str = rpi_datetime_obj.isoformat() if rpi_datetime_obj else "N/A"

    log_row = [
        rpi_iso_timestamp_str, # Use ISO formatted timestamp
        rpi_image_id,
        saved_filename,
        image_size_bytes,
        fetch_duration_ms,
        esp32_url_used
    ]

    with _log_file_lock:
        try:
            with open(LOG_FILE_PATH, mode='a', newline='') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow(log_row)
            # Use a more concise debug log here, as the full row can be long
            logger.debug(f"Logged event to CSV for image ID: {rpi_image_id}") 
        except IOError as e:
            logger.error(f"Error writing to log file {LOG_FILE_PATH}: {e}")
        except Exception as e:
            logger.error(f"Unexpected error during CSV logging: {e}", exc_info=True)