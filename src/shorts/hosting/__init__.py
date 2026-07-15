"""Media hosting backends: upload clips somewhere Buffer can fetch them."""

from __future__ import annotations

from ..config import HostingConfig
from .base import HostedObject, HostingBackend, HostingError


def get_backend(cfg: HostingConfig) -> HostingBackend:
    if cfg.backend in ("r2", "s3", "minio"):
        from .s3 import S3Backend

        return S3Backend(cfg)
    raise HostingError(f"unknown hosting backend: {cfg.backend}")


__all__ = ["HostedObject", "HostingBackend", "HostingError", "get_backend"]
