"""Channel resolution: Buffer channel IDs per platform, cached in the state DB."""

from __future__ import annotations

from ..state import StateStore
from .client import BufferAPIError, BufferClient

_ORG_KEY = "buffer_organization_id"

# Buffer `service` values -> our platform names (identity for the three we use,
# lowercased defensively since docs render them in mixed case).
_SERVICE_TO_PLATFORM = {
    "youtube": "youtube",
    "instagram": "instagram",
    "tiktok": "tiktok",
}


class ChannelResolutionError(RuntimeError):
    pass


def get_organization_id(state: StateStore, client: BufferClient) -> str:
    cached = state.get_value(_ORG_KEY)
    if cached:
        return cached
    orgs = client.organizations()
    if not orgs:
        raise ChannelResolutionError("Buffer account has no organizations")
    org_id = orgs[0]["id"]
    state.set_value(_ORG_KEY, org_id)
    return org_id


def refresh_channels(state: StateStore, client: BufferClient) -> dict[str, str]:
    """Query Buffer for connected channels and replace the local cache.
    Returns platform -> channel_id."""
    org_id = get_organization_id(state, client)
    mapping: dict[str, tuple[str, str | None]] = {}
    for channel in client.channels(org_id):
        platform = _SERVICE_TO_PLATFORM.get(channel.service.lower())
        if platform and platform not in mapping:  # first channel per platform wins
            mapping[platform] = (channel.id, channel.displayName or channel.name)
    state.replace_channels(mapping)
    return {p: cid for p, (cid, _) in mapping.items()}


def resolve_channels(
    state: StateStore, client_factory, platforms: list[str], refresh: bool = False
) -> dict[str, str]:
    """Return platform -> channel_id for every configured platform, using the
    cache when possible. `client_factory` is called only when a refresh is
    needed, so cached runs make zero API calls. Fails loudly on gaps."""
    mapping = {} if refresh else state.get_channels()
    if not all(p in mapping for p in platforms):
        mapping = refresh_channels(state, client_factory())
    missing = [p for p in platforms if p not in mapping]
    if missing:
        raise ChannelResolutionError(
            f"no connected Buffer channel for: {', '.join(missing)}. "
            "Connect the channel(s) in Buffer, then run: shorts buffer channels refresh"
        )
    return {p: mapping[p] for p in platforms}


__all__ = [
    "BufferAPIError",
    "ChannelResolutionError",
    "get_organization_id",
    "refresh_channels",
    "resolve_channels",
]
