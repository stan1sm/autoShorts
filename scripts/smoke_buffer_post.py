"""Live smoke test — NOT run in CI. Posts ONE draft to a designated channel.

Verifies against the real Buffer API: auth, the organizations/channels
queries, and the current createPost assets format. The post is created with
saveToDraft=True, so nothing publishes; delete the draft in the Buffer UI
afterwards.

Usage:
    set BUFFER_API_KEY=...            (or export on POSIX)
    python scripts/smoke_buffer_post.py <platform> <public-video-url>

Example:
    python scripts/smoke_buffer_post.py youtube https://example.com/test.mp4
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from shorts.buffer.client import BufferClient  # noqa: E402
from shorts.buffer.posting import build_post_input  # noqa: E402
from shorts.config import PostingConfig  # noqa: E402


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] not in ("youtube", "instagram", "tiktok"):
        print(__doc__)
        return 1
    platform, video_url = sys.argv[1], sys.argv[2]

    client = BufferClient()
    orgs = client.organizations()
    print(f"organizations: {[(o['id'], o.get('name')) for o in orgs]}")
    channels = client.channels(orgs[0]["id"])
    print(f"channels: {[(c.service, c.id, c.displayName or c.name) for c in channels]}")

    match = next((c for c in channels if c.service.lower() == platform), None)
    if match is None:
        print(f"no connected {platform} channel — connect one in Buffer first")
        return 1

    clip = {
        "file": "clips/smoke_test.mp4",
        "title": "Smoke test — please ignore",
        "description": "Created by scripts/smoke_buffer_post.py. Safe to delete.",
        "hashtags": {platform: ["#test"]},
    }
    cfg = PostingConfig(enabled=True, draft_only=True)  # draft: never publishes
    post_input = build_post_input(clip, platform, match.id, video_url, cfg)
    print(f"createPost input: {post_input.to_variables()['input']}")

    post = client.create_post(post_input)
    print(f"OK — draft created: id={post.id} status={post.status} dueAt={post.dueAt}")
    print("Delete it in the Buffer UI when done.")
    client.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
