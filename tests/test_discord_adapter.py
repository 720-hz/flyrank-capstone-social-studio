"""Proves DiscordBotPublisher's request-building and response-parsing without
any network access, via httpx's MockTransport. The genuinely-real call (a
live bot token posting into a live channel) is out of sandbox reach — see
DESIGN.md and EVIDENCE.md for that transcript, captured on a real machine."""
import json

import httpx

from app.adapters.discord_bot import DiscordBotPublisher


def test_publish_success_parses_message_id():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bot test-token"
        assert request.url.path == "/api/v10/channels/12345/messages"
        body = json.loads(request.content)
        assert "hello world" in body["content"]
        assert "#demo" in body["content"]
        return httpx.Response(200, json={"id": "999888777"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    publisher = DiscordBotPublisher(bot_token="test-token", channel_id="12345", client=client)

    result = publisher.publish(body_text="hello world", hashtags=["#demo"])
    assert result["success"] is True
    assert result["external_id"] == "999888777"
    assert result["error"] is None


def test_publish_http_error_is_captured_not_raised():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "401: Unauthorized"})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    publisher = DiscordBotPublisher(bot_token="bad-token", channel_id="12345", client=client)

    result = publisher.publish(body_text="hello", hashtags=[])
    assert result["success"] is False
    assert result["external_id"] is None
    assert "401" in result["error"]


def test_publish_without_credentials_fails_fast_no_network_call():
    publisher = DiscordBotPublisher(bot_token="", channel_id="")
    result = publisher.publish(body_text="hello", hashtags=[])
    assert result["success"] is False
    assert "not configured" in result["error"]
