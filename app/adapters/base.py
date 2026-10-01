"""The one interface every publisher — real or mock — implements. Nothing
outside app/adapters/ and app/adapters/registry.py is allowed to import a
concrete adapter class directly; the publish worker (app/lib/publishing.py)
only ever calls registry.get(platform).publish(...), which is what makes
swapping an adapter a config change, never a code change (Probe 6)."""
from typing import Protocol, TypedDict


class PublishResult(TypedDict):
    success: bool
    external_id: str | None
    raw_response: dict
    error: str | None


class SocialPublisher(Protocol):
    platform: str

    def publish(self, *, body_text: str, hashtags: list[str]) -> PublishResult:
        ...
