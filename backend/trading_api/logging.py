"""Allowlisted structured events, without raw messages, arguments, or tracebacks."""

import json
import logging
import logging.config
import re

EVENTS = frozenset(
    {"server_starting", "configuration_invalid", "request_completed", "request_failed"}
)


class SafeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = (
            record.msg if isinstance(record.msg, str) and record.msg in EVENTS else "server_event"
        )
        payload: dict[str, str | int] = {"level": record.levelname, "event": event}
        request_id = getattr(record, "request_id", None)
        if isinstance(request_id, str) and re.fullmatch(r"[0-9a-f]{32}", request_id):
            payload["request_id"] = request_id
        status = getattr(record, "status", None)
        if type(status) is int and 100 <= status <= 599:
            payload["status"] = status
        return json.dumps(payload, separators=(",", ":"))


def configure_logging() -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": True,
            "formatters": {"safe": {"()": SafeFormatter}},
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "safe",
                    "stream": "ext://sys.stderr",
                }
            },
            "root": {"level": "INFO", "handlers": ["console"]},
            "loggers": {
                "trading_api": {"level": "INFO", "handlers": [], "propagate": True},
                "uvicorn": {"level": "INFO", "handlers": [], "propagate": True},
                "uvicorn.error": {"level": "INFO", "handlers": [], "propagate": True},
                "uvicorn.access": {"level": "CRITICAL", "handlers": [], "propagate": False},
            },
        }
    )
