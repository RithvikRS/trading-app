"""Fixed local HTTPS rehearsal entry; no hosted configuration or fake identity."""

import logging
import os
import sys

import uvicorn

from trading_api.application import create_app
from trading_api.config import Settings
from trading_api.logging import configure_logging


def main() -> int:
    configure_logging()
    logger = logging.getLogger("trading_api")
    try:
        if len(sys.argv) != 1 or any(key.upper().startswith("TRADING_") for key in os.environ):
            raise ValueError("Rehearsal does not accept application or credential overrides.")
        if sys.platform != "linux" or os.getuid() != 10001:
            raise ValueError("Use the restricted container composition.")
        app = create_app(Settings(frontend_enabled=True), rehearsal=True)
    except Exception:
        logger.error("configuration_invalid")
        return 2
    # API listens only on loopback inside the gateway's isolated network namespace.
    # The proxy overwrites forwarded protocol and strips other forwarding headers.
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8000,
        workers=1,
        reload=False,
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
        server_header=False,
        access_log=False,
        log_config=None,
        http="h11",
        ws="none",
        limit_concurrency=32,
        backlog=64,
        timeout_keep_alive=5,
        timeout_graceful_shutdown=5,
        h11_max_incomplete_event_size=16384,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
