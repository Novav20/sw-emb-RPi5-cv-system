# app/__init__.py
import logging
from flask import Flask
import threading
import os

# --- Global variable and lock for thread safety (for mDNS discovered info) ---
esp32_service_info = {
    "url": None, "ip": None, "port": None, "last_seen": 0
}
esp32_service_info_lock = threading.Lock()

# --- RPi-side Image ID Counter ---
rpi_image_id_counter = 0
rpi_image_id_counter_lock = threading.Lock()

# --- mDNS Thread Management ---
mdns_thread_instance = None
mdns_thread_stop_event = threading.Event() # This will be passed to the thread

# Create Flask app instance FIRST
app_flask_instance = Flask(__name__) # Can be 'app' or any other name, this is the instance.
                                   # Let's stick with app_flask_instance for clarity.

# Configure basic logging (can be done before or after app creation)
# If using app.logger, do it after app_flask_instance is created.
# For global logging.basicConfig, order is less critical.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__) # Logger for this __init__ module

# --- Configuration for Flask app ---
APP_ROOT = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(APP_ROOT)
# Update the upload folder to point to 'output/uploads'
app_flask_instance.config['UPLOAD_FOLDER'] = os.path.join(PROJECT_ROOT, 'output', 'uploads')
os.makedirs(app_flask_instance.config['UPLOAD_FOLDER'], exist_ok=True)
logger.info(f"Upload folder set to: {app_flask_instance.config['UPLOAD_FOLDER']}")

# --- Import other app modules AFTER app_flask_instance is defined ---
# These modules might import 'app_flask_instance' from 'app' (this file)
from app import routes  # routes.py will import app_flask_instance from app
from app import mdns_discover 
from app import log_manager 

# Initialize logging system (needs UPLOAD_FOLDER from app_flask_instance.config)
log_manager.init_logging(app_flask_instance.config['UPLOAD_FOLDER'])

# --- Application factory pattern or direct run functions (optional here) ---
# The start_mdns_and_app and shutdown_app can remain here or move to run.py if preferred
# For simplicity, let's keep them here for now.

def start_mdns_and_app_thread_safe(host='0.0.0.0', port=5000, debug=False): # Renamed for clarity
    global mdns_thread_instance # Ensure we're modifying the package-level global
    
    logger.info("Attempting to start mDNS discovery thread...")
    if not mdns_thread_instance or not mdns_thread_instance.is_alive():
        # Pass the shared data structures and stop event to the thread target
        mdns_thread_instance = threading.Thread(
            target=mdns_discover.mdns_browser_thread_target_stoppable, 
            args=(mdns_thread_stop_event, esp32_service_info, esp32_service_info_lock), 
            daemon=True
        )
        mdns_thread_instance.start()
        logger.info("mDNS discovery thread successfully started.")
    else:
        logger.info("mDNS discovery thread already running.")
    
    logger.info(f"Starting Flask web server on {host}:{port}...")
    try:
        # Note: Flask's app.run() is blocking. It will only return when the server stops.
        app_flask_instance.run(host=host, port=port, debug=debug, use_reloader=False)
    except Exception as e:
        logger.error(f"Flask server run failed: {e}", exc_info=True)
        # Ensure mDNS thread is signaled to stop if Flask fails to start/run
        shutdown_app_resources() # Call the cleanup

def shutdown_app_resources(): # Renamed for clarity
    global mdns_thread_instance, mdns_thread_stop_event
    logger.info("Initiating application resource shutdown (mDNS thread)...")
    if mdns_thread_instance and mdns_thread_instance.is_alive():
        mdns_thread_stop_event.set() # Signal the thread to stop
        mdns_thread_instance.join(timeout=5) # Wait for thread to finish
        if mdns_thread_instance.is_alive():
            logger.warning("mDNS thread did not exit cleanly within timeout.")
        else:
            logger.info("mDNS thread stopped.")
    else:
        logger.info("mDNS thread was not running or already stopped.")
    mdns_thread_instance = None # Clear the instance
    logger.info("Application resource cleanup complete.")