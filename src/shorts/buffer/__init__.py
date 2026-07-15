"""Thin typed wrapper around Buffer's GraphQL API (https://api.buffer.com/graphql).

Uses the current (post-May-2026) schema: assets are `[AssetInput!]` where each
entry wraps a `video: { url, metadata }` input. The deprecated v1 REST API
(api.bufferapp.com) is intentionally not used anywhere.
"""

from .client import BufferAPIError, BufferClient, BufferMutationError

__all__ = ["BufferAPIError", "BufferClient", "BufferMutationError"]
