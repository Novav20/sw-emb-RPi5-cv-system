from flask import Flask, request, jsonify, render_template_string, send_from_directory
from datetime import datetime
import os
import requests
import logging
import socket # For socket.inet_ntoa
import time   # For mDNS discovery related timing
from zeroconf import ServiceBrowser, Zeroconf, ServiceInfo, BadTypeInNameException # mDNS library
import threading # To run mDNS discovery in a background thread

# --- mDNS Configuration ---
# This MUST match the hostname set in the ESP32's mDNS configuration (e.g., "esp32-cam-project")
ESP32_MDNS_HOSTNAME_BASE = "esp32-cam-project"
# Standard HTTP service type the ESP32 advertises
ESP32_SERVICE_TYPE = "_http._tcp.local."

# --- Global variable and lock for thread safety ---
# This dictionary will store the discovered service information
esp32_service_info = {
    "url": None,
    "ip": None,
    "port": None,
    "last_seen": 0 # Timestamp when last seen/updated
}
esp32_service_info_lock = threading.Lock() # Lock to protect access

# --- General Configuration ---
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)

# Configure basic logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
# You can set zeroconf's logger to WARNING to reduce its verbosity if needed
# logging.getLogger('zeroconf').setLevel(logging.WARNING)


# --- mDNS Discovery Logic ---
class ESP32Listener:
    def __init__(self, target_hostname_base):
        self.target_hostname_base = target_hostname_base.lower()
        logging.info(f"mDNS Listener initialized for hostname base: '{self.target_hostname_base}'")

    def _update_global_esp32_info(self, ip_address, port, service_name=""):
        global esp32_service_info # Using the global dict
        with esp32_service_info_lock:
            new_url = f"http://{ip_address}:{port}/capture"
            if esp32_service_info.get("url") != new_url:
                logging.info(
                    f"mDNS: Updating ESP32 info. Previous URL: {esp32_service_info.get('url')}, "
                    f"New URL: {new_url} for service '{service_name}'"
                )
            esp32_service_info["ip"] = ip_address
            esp32_service_info["port"] = port
            esp32_service_info["url"] = new_url
            esp32_service_info["last_seen"] = time.time()

    def remove_service(self, zeroconf_instance, type, name):
        logging.info(f"mDNS: Service {name} removed.")
        # If the removed service was our target, clear the global info
        # This requires knowing the full service name or checking if the IP/port match
        with esp32_service_info_lock:
            current_ip = esp32_service_info.get("ip")
            current_port = esp32_service_info.get("port")

        # More robust check: get info before it's fully removed
        # However, get_service_info might fail for a removing service.
        # Simplest: if any service with our hostname base is removed, we might need to re-evaluate.
        # For now, if *any* _http._tcp service is removed, we might log and let a subsequent
        # add_service call for our target fix it, or a request fail and prompt user.
        # A truly robust solution would track specific service instances.
        if self.target_hostname_base in name.lower():
            logging.warning(f"mDNS: A service potentially matching our target ('{name}') was removed.")
            # Consider clearing the global info if we're sure it was ours
            # For now, we'll rely on add_service to re-establish if it comes back.


    def add_service(self, zeroconf_instance, type, name):
        info = None
        try:
            info = zeroconf_instance.get_service_info(type, name, timeout=2000) # 2s timeout
        except BadTypeInNameException:
            logging.debug(f"mDNS: Ignoring service with bad type in name: {name}")
            return
        except Exception as e: # Catch other potential errors during get_service_info
            logging.warning(f"mDNS: Could not get info for service {name}: {e}")
            return

        if info and info.server and info.addresses and info.port is not None:
            # info.server is like 'esp32-cam-project.local.'
            discovered_hostname_base = info.server.split('.')[0].lower()
            if discovered_hostname_base == self.target_hostname_base:
                ip_address_bytes = info.addresses[0] # Assuming IPv4
                ip_address_str = socket.inet_ntoa(ip_address_bytes)
                port = info.port
                logging.info(f"mDNS: Discovered TARGET ESP32 service '{name}' "
                             f"(Server: {info.server}) at {ip_address_str}:{port}")
                self._update_global_esp32_info(ip_address_str, port, name)
            else:
                logging.debug(f"mDNS: Ignoring discovered service '{name}' (server: {info.server}) - "
                              f"hostname base '{discovered_hostname_base}' does not match target '{self.target_hostname_base}'.")
        else:
            logging.debug(f"mDNS: Service added '{name}', but info incomplete or timed out resolving. Info: {info}")

    def update_service(self, zeroconf_instance, type, name):
        # Called when TXT records change for a service.
        # We re-query the service as IP/port could potentially change (though unlikely for mDNS basics).
        logging.debug(f"mDNS: Service {name} updated (TXT records changed). Re-processing as add_service.")
        self.add_service(zeroconf_instance, type, name)


# --- Global Zeroconf and Thread Management ---
zc_instance = None
browser_instance = None
mdns_thread_instance = None # To hold the thread object

def mdns_browser_thread_target():
    global zc_instance, browser_instance
    try:
        listener = ESP32Listener(ESP32_MDNS_HOSTNAME_BASE)
        zc_instance = Zeroconf() # Create new instance for this thread
        logging.info(f"mDNS Discovery Thread: Starting browser for service type '{ESP32_SERVICE_TYPE}'...")
        browser_instance = ServiceBrowser(zc_instance, ESP32_SERVICE_TYPE, listener=listener)
        
        # Loop to keep this thread alive (ServiceBrowser does its work in background)
        # The thread will exit when the main program exits if it's a daemon thread.
        while not threading.current_thread().stopped(): # Custom 'stopped' attribute can be set from outside
            time.sleep(1) 

    except Exception as e:
        logging.error(f"mDNS Discovery Thread: Unhandled exception: {e}", exc_info=True)
    finally:
        logging.info("mDNS Discovery Thread: Exiting and cleaning up Zeroconf resources.")
        if browser_instance:
            try: browser_instance.cancel()
            except: pass # Ignore errors during cleanup
        if zc_instance:
            try: zc_instance.close()
            except: pass
        zc_instance = None
        browser_instance = None


# --- HTML Template ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>ESP32-CAM Remote Trigger (OV2640)</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 20px; background-color: #f4f4f4; color: #333; }
        .container { background-color: #fff; padding: 20px; border-radius: 8px; box-shadow: 0 0 10px rgba(0,0,0,0.1); }
        button { background-color: #007bff; color: white; padding: 10px 15px; border: none; border-radius: 4px; cursor: pointer; font-size: 16px; }
        button:hover { background-color: #0056b3; }
        #status { margin-top: 15px; font-weight: bold; }
        #preview { margin-top: 15px; max-width: 100%; height: auto; border: 1px solid #ddd; border-radius: 4px; display: none; }
        .error { color: #dc3545; }
        .success { color: #28a745; }
    </style>
</head>
<body>
    <div class="container">
        <h1>ESP32 Camera Control (OV2640 JPEG)</h1>
        <button id="captureBtn">Trigger ESP32 Capture</button>
        <div id="status">Initializing... Attempting to discover ESP32 via mDNS.</div>
        <img id="preview" src="" alt="Image Preview" />
    </div>
    <script>
        const captureBtn = document.getElementById('captureBtn');
        const statusDiv = document.getElementById('status');
        const previewImg = document.getElementById('preview');

        // Small function to check ESP32 status from server (optional)
        async function checkEsp32Status() {
            try {
                const response = await fetch('/esp32-status');
                const data = await response.json();
                if (data.status === 'discovered') {
                    statusDiv.textContent = `ESP32 Ready at ${data.url}. Click button to capture.`;
                    statusDiv.className = 'success';
                } else {
                    statusDiv.textContent = 'Waiting for ESP32 discovery...';
                    statusDiv.className = ''; // Neutral color
                }
            } catch (e) {
                statusDiv.textContent = 'Error checking ESP32 status. Server might be down.';
                statusDiv.className = 'error';
            }
        }

        document.addEventListener('DOMContentLoaded', () => {
            checkEsp32Status(); // Check status on load
            // Optionally, poll status periodically
            // setInterval(checkEsp32Status, 5000); 
        });
        
        captureBtn.addEventListener('click', async () => {
            statusDiv.textContent = 'Requesting image from ESP32...';
            statusDiv.className = '';
            previewImg.style.display = 'none';
            previewImg.src = '';
            captureBtn.disabled = true;

            try {
                const response = await fetch('/trigger-esp32-capture', { method: 'POST' });
                const result = await response.json();

                if (response.ok && result.status === 'success') {
                    statusDiv.textContent = `Success! Image saved as: ${result.filename}`;
                    statusDiv.className = 'success';
                    previewImg.src = `/uploads/${result.filename}?t=${Date.now()}`;
                    previewImg.style.display = 'block';
                } else {
                    statusDiv.textContent = `Error: ${result.message || 'Failed to capture or process image.'}`;
                    statusDiv.className = 'error';
                    // If ESP32 not found, prompt to check status again
                    if (response.status === 503) { 
                        statusDiv.textContent += ' Retrying mDNS discovery...';
                        setTimeout(checkEsp32Status, 2000); // Check again after a small delay
                    }
                }
            } catch (error) {
                console.error('Fetch Error:', error);
                statusDiv.textContent = `Client-side Error: ${error.message}`;
                statusDiv.className = 'error';
            } finally {
                captureBtn.disabled = false;
            }
        });
    </script>
</body>
</html>
"""

# --- Flask Routes ---
@app.route('/')
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route('/uploads/<filename>')
def display_image(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/esp32-status')
def esp32_status_route():
    """Endpoint for the frontend to check ESP32 discovery status."""
    with esp32_service_info_lock:
        url = esp32_service_info.get("url")
    if url:
        return jsonify({"status": "discovered", "url": url})
    else:
        return jsonify({"status": "not_discovered"})


@app.route('/trigger-esp32-capture', methods=['POST'])
def handle_trigger_capture():
    capture_url = None
    with esp32_service_info_lock:
        capture_url = esp32_service_info.get("url")

    logging.info(f"Trigger request. Current known ESP32 URL: {capture_url}")

    if not capture_url:
        logging.error("ESP32 Capture URL not currently known (mDNS discovery pending/failed).")
        return jsonify({"status": "error", "message": "ESP32 service not discovered. Please wait or check ESP32."}), 503

    try:
        logging.info(f"Sending GET request to ESP32 at: {capture_url}")
        esp_response = requests.get(capture_url, timeout=20)
        esp_response.raise_for_status() # Raise HTTPError for bad responses (4xx or 5xx)

        image_data = esp_response.content
        content_type = esp_response.headers.get('Content-Type', '').lower()
        
        logging.info(f"Received {len(image_data)} bytes from ESP32. Content-Type: {content_type}")
        if not image_data:
            raise ValueError("ESP32 returned empty image data")

        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
        filename_base = f'ov2640_capture_{timestamp}'
        
        if 'image/jpeg' in content_type:
            saved_filename = f"{filename_base}.jpg"
            filepath = os.path.join(UPLOAD_FOLDER, saved_filename)
            with open(filepath, 'wb') as f:
                f.write(image_data)
            logging.info(f"OV2640 JPEG image saved as {filepath}")
            return jsonify({"status": "success", "filename": saved_filename, "message": "OV2640 JPEG captured."})
        else:
            logging.warning(f"Unexpected Content-Type: {content_type}. Expected image/jpeg. Saving raw data.")
            saved_filename = f"{filename_base}_unknown.bin"
            filepath = os.path.join(UPLOAD_FOLDER, saved_filename)
            with open(filepath, 'wb') as f:
                f.write(image_data)
            # Return error because we expected JPEG for OV2640
            return jsonify({"status": "error", "message": f"Unexpected content type '{content_type}'. Raw data saved."}), 415

    except requests.exceptions.Timeout:
        logging.error(f"Timeout connecting to ESP32 at {capture_url}")
        return jsonify({"status": "error", "message": "Timeout: ESP32 camera did not respond."}), 504
    except requests.exceptions.ConnectionError:
        logging.error(f"Connection error to ESP32 at {capture_url}. Clearing cached URL for re-discovery.")
        with esp32_service_info_lock: # Clear URL to force re-discovery
            esp32_service_info["url"] = None
            esp32_service_info["ip"] = None
            esp32_service_info["port"] = None
        return jsonify({"status": "error", "message": "Connection Error: Could not connect to ESP32. Will retry discovery."}), 502
    except requests.exceptions.HTTPError as e:
        logging.error(f"HTTP error from ESP32: {e.response.status_code} - {e.response.text}")
        return jsonify({"status": "error", "message": f"ESP32 Error: {e.response.status_code} - {e.response.text}"}), e.response.status_code
    except ValueError as ve: # Catch specific errors like empty image data
        logging.error(f"Data processing error: {ve}")
        return jsonify({"status": "error", "message": str(ve)}), 500
    except Exception as e:
        logging.error(f"An unexpected error occurred in trigger_capture: {e}", exc_info=True)
        return jsonify({"status": "error", "message": f"An internal server error occurred: {e}"}), 500

# --- Main Application Startup ---
if __name__ == '__main__':
    # Custom 'stopped' event for the mDNS thread
    mdns_thread_stop_event = threading.Event()

    def mdns_browser_thread_target_stoppable(): # Wrapper for the thread target
        threading.current_thread().stopped = lambda: mdns_thread_stop_event.is_set()
        mdns_browser_thread_target() # Call original target

    mdns_thread_instance = threading.Thread(target=mdns_browser_thread_target_stoppable, daemon=True)
    mdns_thread_instance.start()
    logging.info("mDNS discovery thread started.")

    try:
        logging.info("Starting Flask web server...")
        # use_reloader=False is important when managing threads yourself
        app.run(host='0.0.0.0', port=5000, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        logging.info("Flask server shutting down (KeyboardInterrupt)...")
    finally:
        logging.info("Initiating mDNS thread shutdown...")
        if mdns_thread_instance and mdns_thread_instance.is_alive():
            mdns_thread_stop_event.set() # Signal the thread to stop
            mdns_thread_instance.join(timeout=5) # Wait for thread to finish
            if mdns_thread_instance.is_alive():
                logging.warning("mDNS thread did not exit cleanly.")
        logging.info("Application cleanup complete. Exiting.")
