"""
Titan-Net Server - Main Entry Point
Starts both WebSocket and HTTP servers
"""

import asyncio
import logging
import os
import signal
import sys
from datetime import datetime
from server import TitanNetServer
from http_server import TitanNetHTTPServer
from honeypot import HoneypotServer
from auth_log_monitor import AuthLogMonitor
from hackback import HackBackProtocol
from config import Config
from models import Database

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
        self.honeypot_server = None
        self.auth_log_monitor = None
        self.running = False

    async def start_servers(self):
        """Start both WebSocket and HTTP servers"""
        try:
            # ONE Database instance, shared by both servers. Passing the same
            # object means both servers route every write through the same
            # ``_writer_lock`` (RLock) and ``_writer_executor`` (single
            # db-writer thread). Without this, the two services raced at the
            # SQLite level and produced ``database is locked`` on every
            # concurrent login + HTTP write (root cause of the 2026-05-03
            # outage). The Database class is now a per-process singleton too,
            # so even if a future caller forgets to pass ``db=`` it still
            # gets the same instance.
            shared_db = Database()

            # Create server instances
            self.websocket_server = TitanNetServer(
                host=self.config.WEBSOCKET_HOST,
                port=self.config.WEBSOCKET_PORT,
                db=shared_db,
            )

            # Resolve optional static web root for the accessible browser
            # portal — defaults to ``<server-dir>/web`` if present.
            _server_dir = os.path.dirname(os.path.abspath(__file__))
            _default_web = os.path.join(_server_dir, 'web')
            web_root = os.environ.get('WEB_ROOT', _default_web)
            if not os.path.isdir(web_root):
                web_root = None

            self.http_server = TitanNetHTTPServer(
                host=self.config.HTTP_HOST,
                port=self.config.HTTP_PORT,
                upload_dir=self.config.UPLOAD_DIR,
                db=shared_db,
                # Share Cerberus so HTTP traffic is gated by the same
                # ban / lockdown decisions that protect WebSocket logins.
                cerberus=self.websocket_server.cerberus,
                web_root=web_root,
            )
            # Let HTTP layer push events (e.g. oauth_connected) to live WS clients
            self.http_server.ws_server = self.websocket_server

            logger.info("=" * 60)
            logger.info("Titan-Net Server Starting...")
            logger.info("=" * 60)

            # Start SSH Honeypot (fake shell trap) on primary port 2222
            # Presents fake Ubuntu SSH login - lets attacker into fake shell
            # after 2 password attempts, traps them, escalates Cerberus to CERBERUS
            try:
                honeypot_port = int(os.environ.get('HONEYPOT_PORT', 2222))
                self.honeypot_server = HoneypotServer(
                    host='0.0.0.0',
                    port=honeypot_port,
                    cerberus=self.websocket_server.cerberus,
                    log_dir='logs'
                )
                self.honeypot_server.start()
                logger.info(
                    f"SSH Honeypot: port {honeypot_port} "
                    f"(fake shell trap - escalates to CERBERUS on 2nd login attempt)"
                )
            except Exception as e:
                logger.warning(f"Honeypot failed to start: {e}")

            # Start HackBack Tar Pit on secondary port 2223
            # Tar pit traps SSH bots in infinite slow banner data
            # Catches mass scanners that hit multiple alternate SSH ports
            try:
                tar_pit_port = int(os.environ.get('TAR_PIT_PORT', 2223))
                hackback = self.websocket_server.hackback
                hackback.start_tar_pit(port=tar_pit_port)
                logger.info(
                    f"HackBack Tar Pit: port {tar_pit_port} "
                    f"(traps SSH bots in infinite slow data)"
                )
            except Exception as e:
                logger.warning(f"Tar pit failed to start (non-critical): {e}")

            # Start Auth Log Monitor (real SSH failed login detection)
            try:
                auth_log_path = os.environ.get('AUTH_LOG_PATH', '/var/log/auth.log')
                self.auth_log_monitor = AuthLogMonitor(
                    cerberus=self.websocket_server.cerberus,
                    auth_log_path=auth_log_path,
                    poll_interval=1.0
                )
                if self.auth_log_monitor.start():
                    logger.info(f"Auth log monitor: watching {auth_log_path}")
                else:
                    logger.warning("Auth log monitor: disabled (file not found or no permission)")
            except Exception as e:
                logger.warning(f"Auth log monitor failed to start (non-critical): {e}")

            # Start HTTP server
            await self.http_server.start()
            logger.info(f"HTTP API: http://{self.config.HTTP_HOST}:{self.config.HTTP_PORT}")

            # Start WebSocket server (this will run forever)
            logger.info(f"WebSocket: ws://{self.config.WEBSOCKET_HOST}:{self.config.WEBSOCKET_PORT}")
            logger.info("=" * 60)
            logger.info("DANGEROUS CERBERUS PROTOCOL: ACTIVE")
            logger.info("  - Auto-firewall bans (iptables + ufw)")
            logger.info("  - Subnet intelligence (auto-ban /24)")
            logger.info("  - Persistent ban database (survives restart)")
            logger.info("HACKBACK PROTOCOL: ACTIVE")
            logger.info("  - Tar pit (traps SSH bots in infinite data)")
            logger.info("  - Cloud IP instant-ban (zero tolerance)")
            logger.info("  - Infrastructure countermeasures (SSH shutdown + CPU exhaust)")
            logger.info("  - Annihilate mode (cloud/botnet server destruction)")
            logger.info("  - Client shutdown (cerberus_shutdown to attacker clients)")
            logger.info("  - Attacker profiling & fingerprinting")
            logger.info("Server is ready to accept connections")
            logger.info("Press Ctrl+C to stop the server")
            logger.info("=" * 60)

            # Reset stuck-online users from any previous SIGKILL/crash.
            # Without this, clients that died with a hung process keep
            # showing 'online' until they manually reconnect & disconnect.
            try:
                affected = self.websocket_server.db.reset_all_online_users()
                logger.info(f"Startup: reset {affected} stuck-online users to offline, cleared room memberships")
            except Exception as e:
                logger.error(f"Startup status reset failed: {e}")

            self.running = True
            # Schedule a one-shot post-restart announcement so clients that
            # reconnect after a deploy know the brief outage is over and the
            # server is healthy. Fires 8s after start to give reconnects time.
            asyncio.create_task(self._post_restart_announcement())
            await self.websocket_server.start()

        except Exception as e:
            logger.error(f"Failed to start servers: {e}", exc_info=True)
            sys.exit(1)

    async def _post_restart_announcement(self):
        """Broadcast a 'server updated, back online' notice shortly after boot.

        Uses the same envelope as the moderator broadcast handler so clients
        render it identically (TTS + moderation.ogg + chat log entry). The
        moderator fields are filled with a synthetic system identity rather
        than impersonating a real user.
        """
        try:
            await asyncio.sleep(8)
            if not self.running or self.websocket_server is None:
                return
            ws = self.websocket_server
            # Don't spam an empty room; only announce when somebody is here.
            if not getattr(ws, 'clients', None):
                return
            message = {
                "type": "moderation_broadcast",
                "moderator_username": "Titan-Net",
                "moderator_id": 0,
                "text_message": (
                    "Serwer został zaktualizowany i jest z powrotem online. "
                    "Server has been updated and is back online."
                ),
                "voice_data": None,
                "timestamp": datetime.now().isoformat(),
            }
            try:
                await ws.broadcast(message)
                logger.info(f"Post-restart announcement sent to {len(ws.clients)} client(s)")
            except Exception as e:
                logger.warning(f"Post-restart announcement failed: {e}")
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning(f"Post-restart announcement task crashed: {e}")

    async def stop_servers(self):
        """Stop all servers"""
        logger.info("Stopping servers...")
        self.running = False
        # Stop HackBack tar pit
        if self.websocket_server and self.websocket_server.hackback:
            self.websocket_server.hackback.stop_tar_pit()
        # Stop honeypot (if fallback was used)
        if self.honeypot_server:
            self.honeypot_server.stop()
        # Stop auth log monitor
        if self.auth_log_monitor:
            self.auth_log_monitor.stop()
        # Checkpoint the WAL so the on-disk file is consistent before exit.
        # If the kernel SIGKILLs us mid-write we want -wal to be empty, not
        # carrying half-applied pages from the previous session.
        try:
            db = getattr(self.websocket_server, 'db', None) if self.websocket_server else None
            if db is not None and hasattr(db, 'checkpoint_wal'):
                db.checkpoint_wal('TRUNCATE')
        except Exception as e:
            logger.error(f"WAL checkpoint on shutdown failed: {e}")
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
