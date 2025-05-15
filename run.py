# run.py
import signal
import sys
import logging # Add logging import for run.py itself

# Import the functions from the app package's __init__.py
from app import start_mdns_and_app_thread_safe, shutdown_app_resources, logger as app_logger 

# Configure logging for run.py if needed, or rely on app's config
logger = logging.getLogger("run_script") # Specific logger for this script
if not logger.handlers: # Avoid duplicate handlers if app already configured root logger
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)


def signal_handler(sig, frame):
    logger.info(f'Received signal {sig}, initiating graceful shutdown...')
    shutdown_app_resources() # Call the cleanup function from app package
    sys.exit(0)

if __name__ == '__main__':
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler) # kill command

    logger.info("Application starting via run.py...")
    try:
        # Call the function from app package to start everything
        start_mdns_and_app_thread_safe(host='0.0.0.0', port=5000, debug=False)
    except SystemExit:
        logger.info("Application exited via SystemExit (likely from signal handler).")
    except Exception as e:
        logger.error(f"Unhandled exception in run.py during app execution: {e}", exc_info=True)
        # Ensure cleanup is attempted even on unexpected error during startup/run
        shutdown_app_resources() 
    finally:
        # This finally block in run.py itself is for run.py's own lifecycle.
        # The actual app resource cleanup (like mDNS thread) should be handled by shutdown_app_resources.
        logger.info("run.py script finished.")