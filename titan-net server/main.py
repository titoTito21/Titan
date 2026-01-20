"""
Titan-Net Server - Main Entry Point
Starts both WebSocket and HTTP servers
"""

import asyncio
import logging
import signal
import sys
from server import TitanNetServer
from http_server import TitanNetHTTPServer
from config import Config

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/main.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('TitanNetMain')


class TitanNetMain:
    def __init__(self):
        self.config = Config()
        self.websocket_server = None
        self.http_server = None
        self.running = False

    async def start_servers(self):
        """Start both WebSocket and HTTP servers"""
        try:
            # Create server instances
            self.websocket_server = TitanNetServer(
                host=self.config.WEBSOCKET_HOST,
                port=self.config.WEBSOCKET_PORT
            )

            self.http_server = TitanNetHTTPServer(
                host=self.config.HTTP_HOST,
                port=self.config.HTTP_PORT,
                upload_dir=self.config.UPLOAD_DIR
            )

            logger.info("=" * 60)
            logger.info("Titan-Net Server Starting...")
            logger.info("=" * 60)

            # Start HTTP server
            await self.http_server.start()
            logger.info(f"HTTP API: http://{self.config.HTTP_HOST}:{self.config.HTTP_PORT}")

            # Start WebSocket server (this will run forever)
            logger.info(f"WebSocket: ws://{self.config.WEBSOCKET_HOST}:{self.config.WEBSOCKET_PORT}")
            logger.info("=" * 60)
            logger.info("Server is ready to accept connections")
            logger.info("Press Ctrl+C to stop the server")
            logger.info("=" * 60)

            self.running = True
            await self.websocket_server.start()

        except Exception as e:
            logger.error(f"Failed to start servers: {e}", exc_info=True)
            sys.exit(1)

    async def stop_servers(self):
        """Stop all servers"""
        logger.info("Stopping servers...")
        self.running = False
        # Cleanup if needed
        logger.info("Servers stopped")

    def handle_signal(self, sig):
        """Handle shutdown signals"""
        logger.info(f"Received signal {sig}, shutting down...")
        asyncio.create_task(self.stop_servers())


def main():
    """Main entry point"""
    titan_net = TitanNetMain()

    # Setup signal handlers
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, lambda s=sig: titan_net.handle_signal(s))
        except NotImplementedError:
            # Windows doesn't support add_signal_handler
            pass

    try:
        loop.run_until_complete(titan_net.start_servers())
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}", exc_info=True)
    finally:
        loop.run_until_complete(titan_net.stop_servers())
        loop.close()


if __name__ == "__main__":
    main()
