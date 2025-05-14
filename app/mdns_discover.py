import logging
import socket
import time
from zeroconf import ServiceBrowser, Zeroconf, ServiceInfo, BadTypeInNameException
import threading

logger = logging.getLogger(__name__)

# --- mDNS Configuration --- (Can be moved to a config module later)
ESP32_MDNS_HOSTNAME_BASE = "my-esp32-cam"
ESP32_SERVICE_TYPE = "_http._tcp.local."

class ESP32Listener:
    def __init__(self, target_hostname_base, service_info_dict, service_info_lock):
        self.target_hostname_base = target_hostname_base.lower()
        self.service_info_dict = service_info_dict # Reference to the global dict
        self.service_info_lock = service_info_lock # Reference to its lock
        logger.info(f"mDNS Listener initialized for hostname base: '{self.target_hostname_base}'")

    def _update_esp32_info(self, ip_address, port, service_name=""):
        with self.service_info_lock:
            new_url = f"http://{ip_address}:{port}/capture"
            if self.service_info_dict.get("url") != new_url:
                logger.info(
                    f"mDNS: Updating ESP32 info. URL: {new_url} for service '{service_name}'"
                )
            self.service_info_dict["ip"] = ip_address
            self.service_info_dict["port"] = port
            self.service_info_dict["url"] = new_url
            self.service_info_dict["last_seen"] = time.time()

    def remove_service(self, zeroconf_instance, type, name):
        logger.info(f"mDNS: Service {name} removed.")
        if self.target_hostname_base in name.lower():
            logger.warning(f"mDNS: A service potentially matching target ('{name}') removed.")
            with self.service_info_lock:
                # Check if it was indeed our currently known service
                current_ip = self.service_info_dict.get("ip")
                info_to_check = None
                try:
                    info_to_check = zeroconf_instance.get_service_info(type, name, timeout=500) # Quick check if still resolvable
                except: pass

                # A more reliable way to check if it's "ours" is if the name itself was stored.
                # Or, if the ip/port matched.
                # For now, let's assume if a service with target_hostname_base in its name is removed,
                # we should clear our cached info.
                # This might lead to brief unavailability if other unrelated services with similar names exist.
                self.service_info_dict["url"] = None
                self.service_info_dict["ip"] = None
                self.service_info_dict["port"] = None


    def add_service(self, zeroconf_instance, type, name):
        info = None
        try:
            info = zeroconf_instance.get_service_info(type, name, timeout=2000)
        except BadTypeInNameException:
            logger.debug(f"mDNS: Ignoring service with bad type: {name}")
            return
        except Exception as e:
            logger.warning(f"mDNS: Could not get info for service {name}: {e}")
            return

        if info and info.server and info.addresses and info.port is not None:
            discovered_hostname_base = info.server.split('.')[0].lower()
            if discovered_hostname_base == self.target_hostname_base:
                ip_address_str = socket.inet_ntoa(info.addresses[0])
                port = info.port
                logger.info(f"mDNS: Discovered TARGET ESP32 '{name}' (Server: {info.server}) at {ip_address_str}:{port}")
                self._update_esp32_info(ip_address_str, port, name)

    def update_service(self, zeroconf_instance, type, name):
        logger.debug(f"mDNS: Service {name} updated. Re-processing.")
        self.add_service(zeroconf_instance, type, name)

# Global Zeroconf instances for the thread
_zc_instance_thread = None
_browser_instance_thread = None

def mdns_browser_thread_target_stoppable(stop_event, service_info_dict_ref, service_info_lock_ref):
    global _zc_instance_thread, _browser_instance_thread
    
    # Make the current thread know about its stop_event for cleaner checking
    threading.current_thread().stop_event = stop_event

    try:
        listener = ESP32Listener(ESP32_MDNS_HOSTNAME_BASE, service_info_dict_ref, service_info_lock_ref)
        _zc_instance_thread = Zeroconf()
        logger.info(f"mDNS Thread: Starting browser for '{ESP32_SERVICE_TYPE}' (target: {ESP32_MDNS_HOSTNAME_BASE})...")
        _browser_instance_thread = ServiceBrowser(_zc_instance_thread, ESP32_SERVICE_TYPE, listener=listener)
        
        while not threading.current_thread().stop_event.is_set():
            time.sleep(0.5) # Check stop event periodically
            # ServiceBrowser does its work in its own internal threads managed by Zeroconf

    except Exception as e:
        logger.error(f"mDNS Thread: Unhandled exception: {e}", exc_info=True)
    finally:
        logger.info("mDNS Thread: Exiting and cleaning up Zeroconf resources.")
        if _browser_instance_thread:
            try: _browser_instance_thread.cancel()
            except: pass
        if _zc_instance_thread:
            try: _zc_instance_thread.close()
            except: pass
        _zc_instance_thread = None
        _browser_instance_thread = None