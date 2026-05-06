from __future__ import annotations

import hashlib
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from tender_royal_pulse.normalization.dates import parse_date, parse_datetime
from tender_royal_pulse.normalization.money import parse_indian_money
from tender_royal_pulse.normalization.text import clean_text

if TYPE_CHECKING:
    from collections.abc import Callable

_HASHER: Callable[[str], str] = lambda s: hashlib.sha256(s.encode()).hexdigest()  # noqa: E731


class Attachment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: str
    doc_type: str | None = None
    description: str | None = None
    url: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _normalize_fields(cls, data: object) -> object:
        if isinstance(data, dict):
            for key in ("filename", "doc_type", "description", "url"):
                val = data.get(key)
                if isinstance(val, str):
                    data[key] = clean_text(val)
        return data


class TenderMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str | None = None
    task_id: str | None = None
    fetched_at: datetime | None = None
    fetcher_used: str = "eprocure_dom.playwright"
    # Bump whenever parse logic changes so callers can re-process historical
    # records that were stored under an older version.
    parse_version: str = "1.1.0"
    page_index: int | None = None
    row_index: int | None = None
    # Keys are field names; values are short error descriptions.  Presence of
    # a key means that field was attempted but failed to parse — distinct from
    # a field that was simply absent on the page (value stays None).
    parse_errors: dict[str, str] | None = None


class ErrorEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    error_class: str
    error_message: str
    task_id: str | None = None
    tender_id: str | None = None
    timestamp: datetime | None = None
    resolved: bool = False


class RunSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    status: str = "running"
    tasks_total: int = 0
    tasks_completed: int = 0
    tasks_failed: int = 0
    tenders_collected: int = 0
    tenders_new: int = 0
    tenders_updated: int = 0
    started_at: datetime | None = None
    finished_at: datetime | None = None
    errors: list[ErrorEvent] = Field(default_factory=list)


class Tender(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    source: str = Field(default="eprocure")
    tender_id: str
    title: str | None = None
    reference_number: str | None = None
    org_chain: str | None = None
    tender_type: str | None = None
    category: str | None = None
    tender_value: Decimal | None = None
    emd_amount: Decimal | None = None
    doc_fee: Decimal | None = None
    currency: str = Field(default="INR")
    closing_date: datetime | None = None
    opening_date: datetime | None = None
    published_date: datetime | None = None
    detail_url: str | None = None
    attachments: list[Attachment] = Field(default_factory=list)
    meta: TenderMeta | None = None
    raw_json: dict[str, Any] | None = None

    @property
    def canonical_url_hash(self) -> str:
        components = [
            self.source,
            self.tender_id,
            self.reference_number or "",
            self.title or "",
            self.org_chain or "",
        ]
        canonical = "|".join(components)
        return _HASHER(canonical)

    @model_validator(mode="before")
    @classmethod
    def _normalize_fields(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data

        date_fields = ("closing_date", "opening_date", "published_date")
        for key in date_fields:
            raw_val = data.get(key)
            if isinstance(raw_val, str):
                dt_parsed = parse_datetime(raw_val)
                if dt_parsed is not None:
                    data[key] = dt_parsed
                else:
                    date_parsed = parse_date(raw_val)
                    if date_parsed is not None:
                        data[key] = date_parsed

        money_fields = ("tender_value", "emd_amount", "doc_fee")
        for key in money_fields:
            raw_val = data.get(key)
            if isinstance(raw_val, str):
                money_parsed = parse_indian_money(raw_val)
                if money_parsed is not None:
                    data[key] = money_parsed[0]
            elif isinstance(raw_val, (int, float)):
                data[key] = Decimal(str(raw_val))

        text_fields = (
            "title",
            "reference_number",
            "org_chain",
            "tender_type",
            "category",
            "tender_id",
            "detail_url",
            "source",
        )
        for key in text_fields:
            raw_val = data.get(key)
            if isinstance(raw_val, str):
                data[key] = clean_text(raw_val)

        attachments = data.get("attachments")
        if isinstance(attachments, list):
            data["attachments"] = [
                Attachment(**a) if isinstance(a, dict) else a for a in attachments
            ]

        meta_val = data.get("meta")
        if isinstance(meta_val, dict):
            data["meta"] = TenderMeta(**meta_val)

        return data

    def to_canonical_key(self) -> str:
        return f"{self.source}|{self.tender_id}"

    def to_csv_row(self) -> dict[str, str]:
        return {
            "source": self.source,
            "tender_id": self.tender_id,
            "canonical_url_hash": self.canonical_url_hash,
            "title": self.title or "",
            "reference_number": self.reference_number or "",
            "org_chain": self.org_chain or "",
            "tender_type": self.tender_type or "",
            "category": self.category or "",
            "tender_value": str(self.tender_value) if self.tender_value is not None else "",
            "emd_amount": str(self.emd_amount) if self.emd_amount is not None else "",
            "doc_fee": str(self.doc_fee) if self.doc_fee is not None else "",
            "currency": self.currency,
            "closing_date": self.closing_date.isoformat() if self.closing_date else "",
            "opening_date": self.opening_date.isoformat() if self.opening_date else "",
            "published_date": self.published_date.isoformat() if self.published_date else "",
            "detail_url": self.detail_url or "",
            "attachment_count": str(len(self.attachments)),
            "fetched_at": self.meta.fetched_at.isoformat() if (self.meta and self.meta.fetched_at) else "",
            "run_id": self.meta.run_id or "" if self.meta else "",
        }
