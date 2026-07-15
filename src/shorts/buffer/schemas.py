"""Pydantic models mirroring the Buffer GraphQL input/output types we use.

Field names match the GraphQL schema exactly (camelCase) so `to_variables()`
can serialize without an alias layer. Only the fields this app sends are
modelled — the schema has more, and unknown response fields are ignored.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


# --- inputs (CreatePostInput and friends) ---

class VideoMetadataInput(BaseModel):
    thumbnailOffset: int | None = None  # seconds into the video


class VideoAssetInput(BaseModel):
    url: str
    metadata: VideoMetadataInput | None = None


class AssetInput(BaseModel):
    """Post-May-2026 assets shape: one wrapper object per asset, typed by key."""
    video: VideoAssetInput


class InstagramPostMetadataInput(BaseModel):
    type: Literal["post", "story", "reel"] = "reel"
    firstComment: str | None = None


class TikTokPostMetadataInput(BaseModel):
    pass  # thumbnail is controlled via VideoMetadataInput.thumbnailOffset


class YoutubePostMetadataInput(BaseModel):
    title: str
    categoryId: str | None = None
    privacy: Literal["public", "unlisted", "private"] | None = None
    madeForKids: bool | None = None
    notifySubscribers: bool | None = None


class PostInputMetaData(BaseModel):
    instagram: InstagramPostMetadataInput | None = None
    tiktok: TikTokPostMetadataInput | None = None
    youtube: YoutubePostMetadataInput | None = None


class CreatePostInput(BaseModel):
    channelId: str
    text: str
    assets: list[AssetInput]
    schedulingType: Literal["automatic"] = "automatic"
    mode: Literal["addToQueue", "customScheduled", "shareNext"] = "addToQueue"
    dueAt: str | None = None  # ISO-8601 UTC, only with mode=customScheduled
    saveToDraft: bool = False
    metadata: PostInputMetaData | None = None

    def to_variables(self) -> dict:
        return {"input": self.model_dump(exclude_none=True)}


# --- outputs ---

class BufferPost(BaseModel):
    id: str
    status: str | None = None
    dueAt: str | None = None


class BufferChannel(BaseModel):
    id: str
    service: str
    name: str | None = None
    displayName: str | None = None
