"""Agent configuration. The API key comes only from the environment and is never shown, logged or serialized."""
from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_MODEL = "anthropic/claude-sonnet-4.5"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class Secret:
    """Holds a secret string. repr and str are masked so it cannot leak through logs, tracebacks or f-strings."""

    __slots__ = ("_value",)

    def __init__(self, value: str):
        self._value = value or ""

    def reveal(self) -> str:
        return self._value

    def __bool__(self) -> bool:
        return bool(self._value)

    def __repr__(self) -> str:
        return "Secret('***')"

    def __str__(self) -> str:
        return "***"

    def __format__(self, spec: str) -> str:
        return "***"

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Secret) and self._value == other._value

    def __hash__(self) -> int:
        return hash(self._value)

    def __reduce__(self):  # never pickle the value
        raise TypeError("Secret cannot be serialized")


@dataclass(frozen=True)
class AgentSettings:
    api_key: Secret = field(default_factory=lambda: Secret(""))
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    timeout_s: float = 60.0
    max_retries: int = 3
    rate_per_minute: int = 10
    max_input_chars: int = 400_000

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @classmethod
    def from_env(cls) -> AgentSettings:
        return cls(
            api_key=Secret(os.environ.get("OPENROUTER_API_KEY", "").strip()),
            model=os.environ.get("OPENROUTER_MODEL", "").strip() or DEFAULT_MODEL,
        )
