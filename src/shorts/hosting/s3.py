"""S3-compatible hosting backend: AWS S3, Cloudflare R2, and MinIO.

Credentials come from env vars, never from config:
  r2:    R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_ACCOUNT_ID
  s3:    AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY (or any boto3 credential source)
  minio: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY + hosting.endpoint_url
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from ..config import HostingConfig
from .base import HostedObject, HostingBackend, HostingError

_HASH_META_KEY = "sha256"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise HostingError(f"missing required env var {name}")
    return value


class S3Backend(HostingBackend):
    def __init__(self, cfg: HostingConfig):
        try:
            import boto3
        except ImportError as exc:
            raise HostingError(
                "boto3 is required for hosting — install with: pip install 'shorts-generator[posting]'"
            ) from exc

        self._cfg = cfg
        kwargs: dict = {"region_name": cfg.region if cfg.region != "auto" else None}
        if cfg.backend == "r2":
            account_id = _require_env("R2_ACCOUNT_ID")
            kwargs.update(
                endpoint_url=cfg.endpoint_url or f"https://{account_id}.r2.cloudflarestorage.com",
                aws_access_key_id=_require_env("R2_ACCESS_KEY_ID"),
                aws_secret_access_key=_require_env("R2_SECRET_ACCESS_KEY"),
                region_name="auto",
            )
        elif cfg.endpoint_url:  # minio or custom S3-compatible endpoint
            kwargs["endpoint_url"] = cfg.endpoint_url
        self._client = boto3.client("s3", **kwargs)

        if cfg.public_mode == "public_bucket" and cfg.backend != "s3" and not cfg.public_base_url:
            raise HostingError(
                "public_bucket mode on r2/minio requires hosting.public_base_url "
                "(e.g. the bucket's r2.dev URL or custom domain)"
            )

    def _remote_hash(self, key: str) -> str | None:
        try:
            head = self._client.head_object(Bucket=self._cfg.bucket, Key=key)
        except self._client.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise HostingError(f"head_object failed for {key}: {exc}") from exc
        return head.get("Metadata", {}).get(_HASH_META_KEY)

    def upload(self, local_path: Path, key: str, file_hash: str) -> HostedObject:
        uploaded = False
        if self._remote_hash(key) != file_hash:
            try:
                self._client.upload_file(
                    str(local_path),
                    self._cfg.bucket,
                    key,
                    ExtraArgs={
                        "ContentType": "video/mp4",
                        "Metadata": {_HASH_META_KEY: file_hash},
                    },
                )
            except Exception as exc:
                raise HostingError(f"upload failed for {key}: {exc}") from exc
            uploaded = True
        url, expires_at = self.url_for(key)
        return HostedObject(
            key=key, url=url, expires_at=expires_at, file_hash=file_hash, uploaded=uploaded
        )

    def url_for(self, key: str) -> tuple[str, str | None]:
        cfg = self._cfg
        if cfg.public_mode == "public_bucket":
            if cfg.public_base_url:
                return f"{cfg.public_base_url.rstrip('/')}/{key}", None
            region = cfg.region if cfg.region != "auto" else "us-east-1"
            return f"https://{cfg.bucket}.s3.{region}.amazonaws.com/{key}", None

        ttl = timedelta(days=cfg.signed_url_ttl_days)
        try:
            url = self._client.generate_presigned_url(
                "get_object",
                Params={"Bucket": cfg.bucket, "Key": key},
                ExpiresIn=int(ttl.total_seconds()),
            )
        except Exception as exc:
            raise HostingError(f"presign failed for {key}: {exc}") from exc
        expires_at = (datetime.now(timezone.utc) + ttl).isoformat()
        return url, expires_at

    def delete(self, key: str) -> None:
        try:
            self._client.delete_object(Bucket=self._cfg.bucket, Key=key)
        except Exception as exc:
            raise HostingError(f"delete failed for {key}: {exc}") from exc
