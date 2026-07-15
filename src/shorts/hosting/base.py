"""Abstract hosting backend: object storage that serves clips over HTTPS."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path


class HostingError(RuntimeError):
    pass


@dataclass
class HostedObject:
    key: str
    url: str
    expires_at: str | None  # ISO-8601, None when the URL does not expire
    file_hash: str
    uploaded: bool  # False when the object already existed with the same hash


class HostingBackend(ABC):
    """One bucket, deterministic keys. Implementations must be idempotent:
    uploading the same file twice is a no-op, a changed file overwrites."""

    @abstractmethod
    def upload(self, local_path: Path, key: str, file_hash: str) -> HostedObject:
        """Upload (or skip if unchanged) and return a fetchable URL for `key`."""

    @abstractmethod
    def url_for(self, key: str) -> tuple[str, str | None]:
        """Return (url, expires_at) for an existing object without uploading."""

    @abstractmethod
    def delete(self, key: str) -> None:
        """Remove the object; missing keys are not an error."""
