"""All tunable constants in one place — nothing below is re-derived elsewhere."""
import os
from dotenv import load_dotenv

load_dotenv()

DB_PATH = os.getenv("DB_PATH", "./social_studio.db")
PORT = int(os.getenv("PORT", "8000"))

DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL_ID = os.getenv("DISCORD_CHANNEL_ID", "")
DISCORD_API_BASE = "https://discord.com/api/v10"

ASSIGNMENT_CLAIM_TIMEOUT_SECONDS = int(os.getenv("ASSIGNMENT_CLAIM_TIMEOUT_SECONDS", "60"))

# ---- Constraint profiles -----------------------------------------------
# Every rule here is deterministic and checked by app/lib/constraints.py.
# A variant that breaks one of these stays in 'draft' with the broken rule
# named in constraint_violations — nothing downstream re-derives this.
CONSTRAINT_PROFILES = {
    "discord": {
        "max_length": 2000,
        "max_hashtags": 10,
        "forbid_shouting": False,
    },
    "x": {
        "max_length": 280,
        "max_hashtags": 3,
        "forbid_shouting": False,
    },
    "linkedin": {
        "max_length": 3000,
        "max_hashtags": 5,
        "forbid_shouting": True,
    },
    "instagram": {
        "max_length": 2200,
        "max_hashtags": 30,
        "forbid_shouting": False,
    },
    "mastodon": {
        "max_length": 500,
        "max_hashtags": 5,
        "forbid_shouting": False,
    },
}

# Which platforms get a real adapter vs. a mock adapter. Per the brief: only the
# platform(s) you actually have free, real, legitimate API/bot access to may be
# real; X/LinkedIn/Instagram are always mocked here.
REAL_PLATFORMS = {"discord"}
ALL_PLATFORMS = list(CONSTRAINT_PROFILES.keys())

# Platforms a freshly-ingested post gets variants generated for by default.
DEFAULT_VARIANT_PLATFORMS = ["discord", "x", "linkedin"]
