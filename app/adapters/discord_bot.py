"""The one REAL adapter. A Discord bot posting a real message into a real
channel via Discord's REST API:

    POST https://discord.com/api/v10/channels/{channel_id}/messages
    Authorization: Bot {token}
    {"content": "<=2000 chars"}

httpx.Client is accepted as a constructor arg (not imported-and-called
inline) specifically so tests can pass a fake transport and prove this
adapter's request-building/response-parsing logic without any network
access — see tests/test_discord_adapter.py. The genuinely-real call (a live
token, a live channel) runs on a machine with normal internet access; this
sandbox's egress policy blocks discord.com directly (see DESIGN.md)."""
import httpx

from app.config import DISCORD_API_BASE, DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID
from app.adapters.base import PublishResult


class DiscordBotPublisher:
    platform = "discord"

    def __init__(
        self,
        *,
        bot_token: str | None = None,
        channel_id: str | None = None,
        client: httpx.Client | None = None,
    ):
        self.bot_token = bot_token if bot_token is not None else DISCORD_BOT_TOKEN
        self.channel_id = channel_id if channel_id is not None else DISCORD_CHANNEL_ID
        self._client = client

    def _client_or_default(self) -> httpx.Client:
        return self._client or httpx.Client(timeout=10.0)

    def publish(self, *, body_text: str, hashtags: list[str]) -> PublishResult:
        content = body_text
        if hashtags:
            content = f"{body_text}\n\n{' '.join(hashtags)}"

        if not self.bot_token or not self.channel_id:
            return PublishResult(
                success=False,
                external_id=None,
                raw_response={},
                error="DISCORD_BOT_TOKEN / DISCORD_CHANNEL_ID not configured",
            )

        url = f"{DISCORD_API_BASE}/channels/{self.channel_id}/messages"
        headers = {
            "Authorization": f"Bot {self.bot_token}",
            "Content-Type": "application/json",
        }

        client = self._client_or_default()
        owns_client = self._client is None
        try:
            resp = client.post(url, headers=headers, json={"content": content})
            data = {}
            try:
                data = resp.json()
            except ValueError:
                pass

            if resp.status_code in (200, 201):
                return PublishResult(
                    success=True,
                    external_id=str(data.get("id")) if data.get("id") else None,
                    raw_response=data,
                    error=None,
                )
            return PublishResult(
                success=False,
                external_id=None,
                raw_response=data,
                error=f"HTTP {resp.status_code}: {data.get('message', resp.text)}",
            )
        except httpx.HTTPError as exc:
            return PublishResult(
                success=False, external_id=None, raw_response={}, error=str(exc)
            )
        finally:
            if owns_client:
                client.close()
