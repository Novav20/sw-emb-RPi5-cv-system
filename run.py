# run.py
import signal
import sys
from app import start_mdns_and_app, shutdown_app, logger # Import from app package

def signal_handler(sig, frame):
    logger.info('Flask app received interrupt signal, shutting down...')
    shutdown_app() # Call our cleanup function
    sys.exit(0)

if __name__ == '__main__':
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)  # Ctrl+C
    signal.signal(signal.SIGTERM, signal_handler) # kill command

    logger.info("Application starting...")
    try:
        start_mdns_and_app(host='0.0.0.0', port=5000, debug=False)
    except Exception as e:
        logger.error(f"Failed to start application: {e}", exc_info=True)
    finally:
        # This finally block in run.py might not always be reached if Flask's run()
        # handles KeyboardInterrupt internally without re-raising.
        # The signal handler is a more robust way for cleanup.
        logger.info("Application run.py finished.") 
        # Ensure shutdown_app is called if not by signal (e.g. natural exit of start_mdns_and_app)
        # This is a bit redundant if signals handle it, but safe.
        # shutdown_app() # This might cause issues if called twice. Signal handler is better.