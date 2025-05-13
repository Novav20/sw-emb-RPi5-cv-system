
import time
import logging
from zeroconf import ServiceBrowser, Zeroconf

logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')

class SimpleListener:
    def remove_service(self, zeroconf, type, name):
        logging.info(f"Service {name} removed")

    def add_service(self, zeroconf, type, name):
        info = zeroconf.get_service_info(type, name)
        logging.info(f"Service {name} ADDED, info: {info}")
    
    def update_service(self, zeroconf, type, name): # Add this
        logging.debug(f"Service {name} updated.")
        # You could try get_service_info again here if needed
        # info = zeroconf.get_service_info(type, name)
        # logging.info(f"Service {name} UPDATED, info: {info}")


zc = Zeroconf()
listener = SimpleListener()
# Use the same service type your ESP32 is advertising
browser = ServiceBrowser(zc, "_http._tcp.local.", listener)
logging.info("Browsing for _http._tcp.local. services for 60 seconds...")

try:
    time.sleep(60) # Browse for a minute
except KeyboardInterrupt:
    pass
finally:
    logging.info("Closing zeroconf...")
    zc.close()
