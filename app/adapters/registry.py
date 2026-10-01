"""Builds {platform: SocialPublisher} from config. This function is the ONLY
place that names concrete adapter classes — app/lib/publishing.py (the
worker) only ever does registry[platform].publish(...). Swapping which class
backs a platform, or adding a new platform, is a one-line change here and
nothing else; that's what Probe 6 (swap an adapter, zero business-logic
changes) actually tests."""
from app.adapters.discord_bot import DiscordBotPublisher
from app.adapters.mocks import (
    MockInstagramPublisher,
    MockLinkedInPublisher,
    MockMastodonPublisher,
    MockXPublisher,
)
from app.adapters.base import SocialPublisher


def build_registry(conn, *, overrides: dict[str, SocialPublisher] | None = None) -> dict:
    registry = {
        "discord": DiscordBotPublisher(),
        "x": MockXPublisher(conn),
        "linkedin": MockLinkedInPublisher(conn),
        "instagram": MockInstagramPublisher(conn),
        "mastodon": MockMastodonPublisher(conn),
    }
    if overrides:
        registry.update(overrides)
    return registry
