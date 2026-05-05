from __future__ import annotations

import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        log_entry: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for attr in dir(record):
            if attr.startswith("event_") and not attr.startswith("event_msg"):
                value = getattr(record, attr, None)
                if value is not None:
                    key = attr.removeprefix("event_")
                    log_entry[key] = value
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])
        return json.dumps(log_entry, default=str)


class EventFields:
    def __init__(self, **fields: str | int | None) -> None:
        self._fields = fields

    def inject(self, record: logging.LogRecord) -> None:
        for key, value in self._fields.items():
            if value is not None:
                setattr(record, f"event_{key}", value)


class EventLogger:
    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def bind(self, **fields: str | int | None) -> EventLogger:
        child = self._logger.getChild("bound")
        field_holder = EventFields(**fields)
        original = child.makeRecord

        def _make_record(*args: Any, **kwargs: Any) -> logging.LogRecord:
            record = original(*args, **kwargs)
            field_holder.inject(record)
            return record

        child.makeRecord = _make_record  # type: ignore[method-assign]
        child._event_fields = field_holder  # type: ignore[attr-defined]
        return EventLogger(child)

    def info(self, msg: str, **kwargs: str | int | None) -> None:
        extra: dict[str, str | int | None] = {}
        for k, v in kwargs.items():
            extra[f"event_{k}"] = v
        record = self._logger.makeRecord(
            self._logger.name, logging.INFO, "", 0, msg, (), None
        )
        for k, v in extra.items():
            setattr(record, k, v)
        self._logger.handle(record)

    def debug(self, msg: str, **kwargs: str | int | None) -> None:
        extra: dict[str, str | int | None] = {}
        for k, v in kwargs.items():
            extra[f"event_{k}"] = v
        record = self._logger.makeRecord(
            self._logger.name, logging.DEBUG, "", 0, msg, (), None
        )
        for k, v in extra.items():
            setattr(record, k, v)
        self._logger.handle(record)

    def warning(self, msg: str, **kwargs: str | int | None) -> None:
        extra: dict[str, str | int | None] = {}
        for k, v in kwargs.items():
            extra[f"event_{k}"] = v
        record = self._logger.makeRecord(
            self._logger.name, logging.WARNING, "", 0, msg, (), None
        )
        for k, v in extra.items():
            setattr(record, k, v)
        self._logger.handle(record)

    def error(self, msg: str, **kwargs: str | int | None) -> None:
        extra: dict[str, str | int | None] = {}
        for k, v in kwargs.items():
            extra[f"event_{k}"] = v
        record = self._logger.makeRecord(
            self._logger.name, logging.ERROR, "", 0, msg, (), None
        )
        for k, v in extra.items():
            setattr(record, k, v)
        self._logger.handle(record)

    def exception(self, msg: str, **kwargs: str | int | None) -> None:
        extra: dict[str, str | int | None] = {}
        for k, v in kwargs.items():
            extra[f"event_{k}"] = v
        record = self._logger.makeRecord(
            self._logger.name, logging.ERROR, "", 0, msg, (), sys.exc_info()
        )
        for k, v in extra.items():
            setattr(record, k, v)
        self._logger.handle(record)


def setup_logging(level: int = logging.INFO) -> EventLogger:
    logger = logging.getLogger("tenderpulse")
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
    logger.propagate = False
    return EventLogger(logger)
