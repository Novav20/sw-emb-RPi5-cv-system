# app/routes.py
import os
from flask import request, jsonify, render_template, send_from_directory # Changed to render_template
import logging
# datetime and time are not directly used in routes if utils.py handles timestamp
# but keep if other logic needs them here.

# Import the app instance and shared data/locks from app package's __init__.py
from app import app_flask_instance, esp32_service_info, esp32_service_info_lock, \
                rpi_image_id_counter, rpi_image_id_counter_lock

# Import functions from our new modules
from app.camera_comms import fetch_image_from_esp32
from app.utils import get_formatted_timestamp # Assuming you created app/utils.py

logger = logging.getLogger(__name__)

@app_flask_instance.route('/')
def index():
    # Import ESP32_MDNS_HOSTNAME_BASE from mdns_discover to pass to template
    # This ensures we always get the current config if it were to change (though it's const here)
    from app.mdns_discover import ESP32_MDNS_HOSTNAME_BASE
    return render_template('index.html', 
                           target_mdns_hostname=ESP32_MDNS_HOSTNAME_BASE,
                           target_mdns_hostname_for_js=ESP32_MDNS_HOSTNAME_BASE) # For JS access

@app_flask_instance.route('/uploads/<filename>')
def display_image(filename):
    # app_flask_instance.config['UPLOAD_FOLDER'] is set in app/__init__.py
    return send_from_directory(app_flask_instance.config['UPLOAD_FOLDER'], filename)

@app_flask_instance.route('/esp32-status')
def esp32_status_route():
    url = None # Default to None
    with esp32_service_info_lock:
        url = esp32_service_info.get("url")
    
    if url:
        return jsonify({"status": "discovered", "url": url})
    else:
        from app.mdns_discover import ESP32_MDNS_HOSTNAME_BASE # Import if needed for target name
        return jsonify({"status": "not_discovered", "target_hostname": f"{ESP32_MDNS_HOSTNAME_BASE}.local"})


@app_flask_instance.route('/trigger-esp32-capture', methods=['POST'])
def handle_trigger_capture():
    # Access shared counter via the import from app package
    global rpi_image_id_counter 

    current_capture_url = None
    with esp32_service_info_lock:
        current_capture_url = esp32_service_info.get("url")

    logger.info(f"Trigger request. Current known ESP32 URL: {current_capture_url}")

    if not current_capture_url:
        logger.error("ESP32 Capture URL not currently known (mDNS discovery pending/failed).")
        return jsonify({"status": "error", "message": "ESP32 service not discovered. Please wait or check ESP32."}), 503

    image_data, content_type, error_msg, status_code, fetch_time_ms = \
        fetch_image_from_esp32(current_capture_url)

    if error_msg:
        # If connection error, clear the cached URL to encourage re-discovery by mDNS listener
        if status_code == 502: # HTTP 502 Bad Gateway often means connection issue
            logger.warning("Connection error to ESP32. Clearing cached URL to trigger mDNS re-check.")
            with esp32_service_info_lock:
                esp32_service_info["url"] = None
                esp32_service_info["ip"] = None
                esp32_service_info["port"] = None
        return jsonify({"status": "error", "message": error_msg}), status_code

    # --- RPi-side Timestamp and ID ---
    rpi_ts_str = get_formatted_timestamp() # From app.utils
    
    current_rpi_id_val = 0
    with rpi_image_id_counter_lock:
        rpi_image_id_counter += 1
        current_rpi_id_val = rpi_image_id_counter
    
    # --- Image Saving and Response ---
    # Expecting JPEG from OV2640
    if 'image/jpeg' in content_type:
        saved_filename = f"image_{rpi_ts_str}_{current_rpi_id_val}.jpg"
        filepath = os.path.join(app_flask_instance.config['UPLOAD_FOLDER'], saved_filename)
        try:
            with open(filepath, 'wb') as f:
                f.write(image_data)
            logger.info(f"OV2640 JPEG image saved as {filepath}")
            
            # Prepare data for logging (for Wednesday's task)
            log_data_points = {
                "rpi_timestamp": rpi_ts_str, # The formatted string timestamp
                "rpi_image_id": current_rpi_id_val,
                "saved_filename": saved_filename,
                "image_size_bytes": len(image_data),
                "fetch_duration_ms": fetch_time_ms,
                "esp32_url_used": current_capture_url # Log which URL was used
            }
            logger.info(f"LOG_PREP (Success): {log_data_points}")

            return jsonify({"status": "success", "filename": saved_filename, "message": "OV2640 JPEG captured and saved."})
        except Exception as e:
            logger.error(f"Error saving image {saved_filename}: {e}", exc_info=True)
            return jsonify({"status": "error", "message": f"Failed to save image on RPi: {e}"}), 500
    else:
        # This case should ideally not happen if ESP32 is configured for JPEG
        logger.warning(f"Unexpected Content-Type from ESP32: {content_type}. Expected 'image/jpeg'.")
        saved_filename = f"image_{rpi_ts_str}_{current_rpi_id_val}_unknown_type.bin" # Save with ID/TS
        filepath = os.path.join(app_flask_instance.config['UPLOAD_FOLDER'], saved_filename)
        try:
            with open(filepath, 'wb') as f:
                f.write(image_data)
            logger.info(f"Raw data (unexpected type) saved as {filepath}")
            return jsonify({"status": "error", 
                            "message": f"Unexpected content type '{content_type}' from ESP32. Raw data saved as .bin."}), 415 # Unsupported Media Type
        except Exception as e:
            logger.error(f"Error saving raw data {saved_filename}: {e}", exc_info=True)
            return jsonify({"status": "error", "message": f"Failed to save raw image data: {e}"}), 500