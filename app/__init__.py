import logging
from flask import Flask
import threading # For mdns_thread_stop_event
import os

# Configure basic logging (can be centralized here)
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# --- Global variable and lock for thread safety (for mDNS discovered info) ---
# This needs to be accessible by mdns_discover and routes
esp32_service_info = {
    "url": None,
    "ip": None,
    "port": None,
    "last_seen": 0
}
esp32_service_info_lock = threading.Lock()

# --- RPi-side Image ID Counter ---
rpi_image_id_counter = 0
rpi_image_id_counter_lock = threading.Lock()

# --- mDNS Thread Management ---
mdns_thread_instance = None
mdns_thread_stop_event = threading.Event()


# Create Flask app instance
app_flask_instance = Flask(__name__) # Renamed to avoid conflict with 'app' package name

# Configuration (can be moved here or to a config.py)
app_flask_instance.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'uploads') # Note '..'
os.makedirs(app_flask_instance.config['UPLOAD_FOLDER'], exist_ok=True)

# Import routes after app is created to avoid circular imports
from app import routes 
# Import mDNS discovery to start it
from app import mdns_discover

def start_mdns_and_app(host='0.0.0.0', port=5000, debug=False):
    global mdns_thread_instance
    if not mdns_thread_instance or not mdns_thread_instance.is_alive():
        mdns_thread_instance = threading.Thread(
            target=mdns_discover.mdns_browser_thread_target_stoppable, 
            args=(mdns_thread_stop_event, esp32_service_info, esp32_service_info_lock), # Pass globals
            daemon=True
        )
        mdns_thread_instance.start()
        logger.info("mDNS discovery thread started from app initializer.")
    
    logger.info("Starting Flask web server...")
    app_flask_instance.run(host=host, port=port, debug=debug, use_reloader=False)

def shutdown_app():
    logger.info("Initiating mDNS thread shutdown...")
    if mdns_thread_instance and mdns_thread_instance.is_alive():
        mdns_thread_stop_event.set()
        mdns_thread_instance.join(timeout=5)
        if mdns_thread_instance.is_alive():
            logger.warning("mDNS thread did not exit cleanly.")
    logger.info("Application cleanup complete.")

# You might not need to call start_mdns_and_app here if run.py does it.
# This __init__.py primarily sets up the app instance and imports.