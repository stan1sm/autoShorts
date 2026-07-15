"""GraphQL client for the Buffer API: auth, rate limiting, retries.

Transport is plain httpx with hand-written queries (full control, no
dependency on third-party Buffer libraries, which mostly target the dead
v1 REST API). The API key is read from BUFFER_API_KEY and never logged.
"""

from __future__ import annotations

import os
import time
from collections import deque

from .queries import CHANNELS, CREATE_POST, ORGANIZATIONS, POSTS
from .schemas import BufferChannel, BufferPost, CreatePostInput

API_ENDPOINT = "https://api.buffer.com/graphql"
_WINDOW_SECONDS = 900  # Buffer's shortest rate-limit window: 15 minutes


class BufferAPIError(RuntimeError):
    """API-level failure. `transient` says whether retrying may help."""

    def __init__(self, message: str, transient: bool = False):
        super().__init__(message)
        self.transient = transient


class BufferMutationError(BufferAPIError):
    """Buffer returned a MutationError payload (validation etc.) — permanent."""

    def __init__(self, message: str, code: str | None = None):
        super().__init__(message, transient=False)
        self.code = code


class _TokenBucket:
    """Local conservative cap so we never approach Buffer's real limits."""

    def __init__(self, max_requests: int, window_seconds: float = _WINDOW_SECONDS):
        self._max = max_requests
        self._window = window_seconds
        self._stamps: deque[float] = deque()

    def wait_time(self, now: float) -> float:
        while self._stamps and now - self._stamps[0] >= self._window:
            self._stamps.popleft()
        if len(self._stamps) < self._max:
            return 0.0
        return self._stamps[0] + self._window - now

    def record(self, now: float) -> None:
        self._stamps.append(now)


class BufferClient:
    def __init__(
        self,
        api_key: str | None = None,
        endpoint: str = API_ENDPOINT,
        max_requests_per_15min: int = 30,
        max_attempts: int = 5,
        initial_backoff_seconds: float = 2.0,
        http_client=None,  # injectable for tests (httpx.Client-compatible)
    ):
        try:
            import httpx
        except ImportError as exc:
            raise BufferAPIError(
                "httpx is required for posting — install with: pip install 'shorts-generator[posting]'"
            ) from exc

        key = api_key or os.environ.get("BUFFER_API_KEY")
        if not key:
            raise BufferAPIError("BUFFER_API_KEY is not set")
        self._endpoint = endpoint
        self._max_attempts = max_attempts
        self._initial_backoff = initial_backoff_seconds
        self._bucket = _TokenBucket(max_requests_per_15min)
        self._http = http_client or httpx.Client(timeout=60.0)
        self._headers = {"Authorization": f"Bearer {key}"}
        self._sleep = time.sleep  # patchable in tests

    # --- transport ---

    def execute(self, query: str, variables: dict | None = None) -> dict:
        """Run one GraphQL operation, returning the `data` object.

        Transient failures (429, 5xx, network errors) are retried with
        exponential backoff honoring Retry-After; anything else raises
        immediately as permanent.
        """
        import httpx

        backoff = self._initial_backoff
        last_error: BufferAPIError | None = None
        for attempt in range(1, self._max_attempts + 1):
            wait = self._bucket.wait_time(time.monotonic())
            if wait > 0:
                self._sleep(wait)
            self._bucket.record(time.monotonic())
            try:
                response = self._http.post(
                    self._endpoint,
                    json={"query": query, "variables": variables or {}},
                    headers=self._headers,
                )
            except httpx.HTTPError as exc:
                last_error = BufferAPIError(f"network error: {exc}", transient=True)
            else:
                if response.status_code == 429:
                    retry_after = response.headers.get("Retry-After")
                    if retry_after:
                        try:
                            backoff = max(backoff, float(retry_after))
                        except ValueError:
                            pass
                    last_error = BufferAPIError("rate limited (429)", transient=True)
                elif response.status_code >= 500:
                    last_error = BufferAPIError(
                        f"server error ({response.status_code})", transient=True
                    )
                elif response.status_code >= 400:
                    raise BufferAPIError(
                        f"request rejected ({response.status_code}): {response.text[:500]}"
                    )
                else:
                    payload = response.json()
                    if payload.get("errors"):
                        messages = "; ".join(
                            e.get("message", "unknown") for e in payload["errors"]
                        )
                        raise BufferAPIError(f"GraphQL errors: {messages}")
                    return payload.get("data") or {}

            if attempt < self._max_attempts:
                self._sleep(backoff)
                backoff *= 2
        assert last_error is not None
        raise last_error

    # --- typed operations ---

    def organizations(self) -> list[dict]:
        account = self.execute(ORGANIZATIONS).get("account") or {}
        return account.get("organizations") or []

    def channels(self, organization_id: str) -> list[BufferChannel]:
        data = self.execute(CHANNELS, {"organizationId": organization_id})
        return [BufferChannel.model_validate(c) for c in data.get("channels") or []]

    def create_post(self, post_input: CreatePostInput) -> BufferPost:
        data = self.execute(CREATE_POST, post_input.to_variables())
        result = data.get("createPost") or {}
        if "post" in result and result["post"]:
            return BufferPost.model_validate(result["post"])
        raise BufferMutationError(
            result.get("message", "createPost returned no post"), code=result.get("code")
        )

    def posts(
        self, organization_id: str, channel_ids: list[str] | None = None,
        status: list[str] | None = None, first: int = 50,
    ) -> list[BufferPost]:
        filter_input: dict = {}
        if channel_ids:
            filter_input["channelIds"] = channel_ids
        if status:
            filter_input["status"] = status
        variables = {
            "input": {"organizationId": organization_id, "filter": filter_input or None},
            "first": first,
            "after": None,
        }
        results: list[BufferPost] = []
        while True:
            data = self.execute(POSTS, variables)
            page = data.get("posts") or {}
            for edge in page.get("edges") or []:
                node = edge.get("node")
                if node:
                    results.append(BufferPost.model_validate(node))
            info = page.get("pageInfo") or {}
            if not info.get("hasNextPage"):
                return results
            variables["after"] = info.get("endCursor")

    def close(self) -> None:
        self._http.close()
