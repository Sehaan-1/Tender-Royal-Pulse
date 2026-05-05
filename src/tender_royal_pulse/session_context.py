from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SessionContext(BaseModel):
    """Session context for Playwright browser state.

    Schema versioning via `version` field enables future migrations.
    """

    model_config = ConfigDict(
        extra="forbid",
        validate_assignment=True,
    )

    version: int = Field(default=1, ge=1, description="Schema version for migration compatibility")
    storage_state: dict[str, Any] | None = Field(default=None, description="Playwright context.storage_state()")
    user_agent: str | None = Field(default=None, description="Custom user agent string")
    created_at: datetime | None = Field(default_factory=lambda: datetime.now(UTC), description="Context creation timestamp")

    def to_playwright_storage_state(self) -> dict[str, Any] | None:
        """Return storage_state in format expected by Playwright."""
        return self.storage_state

    @classmethod
    def from_playwright_storage_state(
        cls,
        storage_state: dict[str, Any] | None,
        user_agent: str | None = None,
    ) -> "SessionContext":
        """Create SessionContext from Playwright storage state."""
        return cls(
            version=1,
            storage_state=storage_state,
            user_agent=user_agent,
            created_at=datetime.now(UTC),
        )
