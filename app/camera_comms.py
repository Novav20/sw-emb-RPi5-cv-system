# app/camera_comms.py
import requests
import logging
import time # For timing the fetch

logger = logging.getLogger(__name__)

def fetch_image_from_esp32(capture_url):
    """
    Fetches an image from the ESP32.
    Returns a tuple (image_data, content_type, error_message, status_code, fetch_duration_ms)
    error_message is None on success. status_code is HTTP status.
    """
    if not capture_url:
        return None, None, "ESP32 capture URL is not known.", 503, 0

    try:
        start_time = time.monotonic()
        logger.info(f"Requesting image from ESP32: {capture_url}")
        response = requests.get(capture_url, timeout=20) # 20-second timeout
        duration_ms = (time.monotonic() - start_time) * 1000
        
        response.raise_for_status() # Raises HTTPError for 4xx/5xx status

        image_data = response.content
        content_type = response.headers.get('Content-Type', '').lower()
        
        if not image_data:
            logger.error("ESP32 returned empty image data.")
            return None, content_type, "ESP32 returned empty image data", response.status_code, duration_ms
            
        logger.info(f"Received {len(image_data)} bytes from ESP32 (Content-Type: {content_type}) in {duration_ms:.2f} ms.")
        return image_data, content_type, None, response.status_code, duration_ms

    except requests.exceptions.Timeout:
        logger.error(f"Timeout connecting to ESP32 at {capture_url}")
        return None, None, "Timeout: ESP32 camera did not respond.", 504, (time.monotonic() - start_time) * 1000
    except requests.exceptions.ConnectionError:
        logger.error(f"Connection error to ESP32 at {capture_url}")
        return None, None, "Connection Error: Could not connect to ESP32 camera.", 502, (time.monotonic() - start_time) * 1000
    except requests.exceptions.HTTPError as e:
        logger.error(f"HTTP error from ESP32: {e.response.status_code} - {e.response.text}")
        return None, None, f"ESP32 Error: {e.response.status_code} - {e.response.text}", e.response.status_code, (time.monotonic() - start_time) * 1000
    except Exception as e:
        logger.error(f"Unexpected error fetching image: {e}", exc_info=True)
        return None, None, f"An internal server error occurred: {e}", 500, (time.monotonic() - start_time) * 1000