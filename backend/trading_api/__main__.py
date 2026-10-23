"""Run the local-only API with fixed, conservative server settings."""

import logging
import sys

import uvicorn

from trading_api.config import ConfigurationError, load_settings
from trading_api.logging import configure_logging


def main() -> int:
    configure_logging()
    logger = logging.getLogger("trading_api")
    try:
        if len(sys.argv) != 1:
            raise ConfigurationError("Command-line overrides are not supported.")
        settings = load_settings()
    except ConfigurationError:
        logger.error("configuration_invalid")
        return 2

    # Reject invalid configuration before importing the HTTP application stack.
    from trading_api.application import create_app

    try:
        application = create_app(settings)
    except Exception:
        logger.error("configuration_invalid")
        return 2
    logger.info("server_starting")
    uvicorn.run(
        application,
        host="127.0.0.1",
        port=settings.port,
        workers=1,
        reload=False,
        proxy_headers=False,
        forwarded_allow_ips="",
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
