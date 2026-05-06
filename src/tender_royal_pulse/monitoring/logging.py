from __future__ import annotations

import json
import logging
import sys
from collections.abc import Mapping
from datetime import UTC, datetime
from types import TracebackType
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


class _BoundLogger(logging.Logger):
    """Logger subclass that injects EventFields into every log record."""

    def __init__(self, name: str, level: int, fields: EventFields) -> None:
        super().__init__(name, level)
        self._event_fields: EventFields = fields

    # exc_info must match Logger.makeRecord's typeshed signature exactly —
    # the broader logging._ExcInfoType (which includes bool | BaseException) is
    # not accepted by the parent's stub, causing an arg-type error at super() call.
    _ExcTuple = (
        tuple[type[BaseException], BaseException, TracebackType | None]
        | tuple[None, None, None]
        | None
    )

    def makeRecord(  # noqa: N802  (stdlib uses camelCase)
        self,
        name: str,
        level: int,
        fn: str,
        lno: int,
        msg: object,
        args: logging._ArgsType,
        exc_info: _ExcTuple,
        func: str | None = None,
        extra: Mapping[str, object] | None = None,
        sinfo: str | None = None,
    ) -> logging.LogRecord:
        record = super().makeRecord(
            name, level, fn, lno, msg, args, exc_info, func, extra, sinfo
        )
        self._event_fields.inject(record)
        return record


class EventLogger:
    def __init__(self, logger: logging.Logger) -> None:
        self._logger = logger

    def bind(self, **fields: str | int | None) -> EventLogger:
        field_holder = EventFields(**fields)
        # Register the child logger through the stdlib Manager so that parent
        # linking, level propagation, and handler lookup all work correctly
        # without directly assigning to Logger.parent (which mypy flags).
        child_name = self._logger.name + ".bound"
        child_logger = _BoundLogger(child_name, self._logger.level, field_holder)
        child_logger.manager = self._logger.manager
        self._logger.manager.loggerDict[child_name] = child_logger
        child_logger.propagate = True
        return EventLogger(child_logger)

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
    logger = logging.getLogger("tender_royal_pulse")
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(JSONFormatter())
        logger.addHandler(handler)
    logger.propagate = False
    return EventLogger(logger)
