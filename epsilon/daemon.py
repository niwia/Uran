#!/usr/bin/env python3
"""Epsilon Daemon — Standalone & systemd socket-activated bridge server.

Epsilon - at0-m and uran companion.
Listens on 127.0.0.1:1952 and receives commands from the Photar userscript.
"""

import argparse
import logging
import os
import sys
import threading
import time
from pathlib import Path

# Ensure uran_backend is discoverable from this script's location
_PROJECT_DIR = str(Path(__file__).resolve().parent.parent)
if _PROJECT_DIR not in sys.path:
    sys.path.insert(0, _PROJECT_DIR)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("Epsilon")

from uran_backend.epsilon_server import (  # noqa: E402
    DEFAULT_HOST,
    DEFAULT_IDLE_TIMEOUT,
    DEFAULT_PORT,
    StandaloneHTTPHandler,
    ThreadedEpsilonHTTPServer,
    get_systemd_listen_fd,
    is_port_in_use,
)
from uran_backend.plugin_api import default_services  # noqa: E402


class IdleShutdownTimer:
    """Watchdog that terminates the process after inactivity under socket activation."""

    def __init__(self, timeout_sec: int, on_timeout):
        self.timeout_sec = timeout_sec
        self.on_timeout = on_timeout
        self.last_activity = time.time()
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()

    def touch(self):
        self.last_activity = time.time()

    def stop(self):
        self._stop_event.set()

    def _run(self):
        while not self._stop_event.wait(5):
            elapsed = time.time() - self.last_activity
            if elapsed >= self.timeout_sec:
                logger.info(
                    "Idle timeout reached (%ds with no requests). Exiting to release memory.",
                    self.timeout_sec,
                )
                self.on_timeout()
                break


def main():
    parser = argparse.ArgumentParser(
        description="Epsilon - at0-m and uran companion"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help=f"Port to bind when running standalone (default: {DEFAULT_PORT})",
    )
    parser.add_argument(
        "--host",
        type=str,
        default=DEFAULT_HOST,
        help=f"Host to bind when running standalone (default: {DEFAULT_HOST})",
    )
    parser.add_argument(
        "--socket-activated",
        action="store_true",
        help="Run under systemd socket activation with automatic idle shutdown",
    )
    parser.add_argument(
        "--idle-timeout",
        type=int,
        default=DEFAULT_IDLE_TIMEOUT,
        help=f"Idle shutdown timeout in seconds when socket-activated (default: {DEFAULT_IDLE_TIMEOUT})",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Check status of Epsilon and exit",
    )

    args = parser.parse_args()

    # Preflight status check
    if args.status:
        active = is_port_in_use(args.port, args.host)
        print(f"Epsilon port {args.port} active: {active}")
        sys.exit(0 if active else 1)

    logger.info("Initializing Uran 0.6.3 service engine for Epsilon...")
    services = default_services()

    # Check for systemd socket activation descriptor
    inherited_sock = get_systemd_listen_fd()
    is_socket_activated = args.socket_activated or (inherited_sock is not None)

    if inherited_sock:
        logger.info("Inherited listening socket from systemd (FD=3)")
        server_address = inherited_sock.getsockname()
    else:
        if is_port_in_use(args.port, args.host):
            logger.error(
                "Port %s:%s is already in use! Is Uran or another Epsilon instance running?",
                args.host,
                args.port,
            )
            sys.exit(1)
        server_address = (args.host, args.port)

    # Configure HTTP request handler
    StandaloneHTTPHandler.services = services

    httpd = ThreadedEpsilonHTTPServer(
        server_address, StandaloneHTTPHandler, inherited_socket=inherited_sock
    )

    # Idle watchdog under socket activation
    timer = None
    if is_socket_activated and args.idle_timeout > 0:

        def _do_shutdown():
            threading.Thread(target=httpd.shutdown, daemon=True).start()

        timer = IdleShutdownTimer(args.idle_timeout, _do_shutdown)
        StandaloneHTTPHandler.on_activity = timer.touch
        timer.start()
        logger.info(
            "Socket-activated mode enabled: will shut down after %ds of inactivity",
            args.idle_timeout,
        )

    logger.info("Epsilon bridge active and waiting for Photar on %s:%s", args.host, args.port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutdown requested via KeyboardInterrupt")
    finally:
        if timer:
            timer.stop()
        httpd.server_close()
        logger.info("Epsilon server stopped cleanly.")


if __name__ == "__main__":
    main()
