"""Mock adapters for the platforms the brief explicitly forbids real-publishing
to (X, LinkedIn — and Instagram if generated). Each one 'publishes' by writing
a row to mock_publish_log (so GET /v1/mock-log?platform=x gives a real preview
of what WOULD have been posted) and returns a deterministic success — they
implement the exact same SocialPublisher interface as the real Discord
adapter, which is the whole point: the publish worker can't tell them apart."""
import json
import uuid
from datetime import datetime, timezone

from app.adapters.base import PublishResult


class _MockPublisher:
    platform = "x"  # overridden per subclass

    def __init__(self, conn):
        self._conn = conn

    def publish(self, *, body_text: str, hashtags: list[str]) -> PublishResult:
        external_id = f"mock_{self.platform}_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            """INSERT INTO mock_publish_log
                   (platform, body_text, hashtags, external_id, posted_at)
               VALUES (?, ?, ?, ?, ?)""",
            (self.platform, body_text, json.dumps(hashtags), external_id, now),
        )
        return PublishResult(
            success=True,
            external_id=external_id,
            raw_response={"mock": True, "platform": self.platform, "id": external_id},
            error=None,
        )


class MockXPublisher(_MockPublisher):
    platform = "x"


class MockLinkedInPublisher(_MockPublisher):
    platform = "linkedin"


class MockInstagramPublisher(_MockPublisher):
    platform = "instagram"


class MockMastodonPublisher(_MockPublisher):
    platform = "mastodon"
