"""Centralized credential loading from .env file."""

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

DB_DSN = os.environ["BBT_DB_DSN"]
CMV4_DSN = os.environ["CMV4_DB_DSN"]

ALPACA_ENDPOINT = os.getenv("ALPACA_ENDPOINT", "https://paper-api.alpaca.markets")
ALPACA_KEYS = {
    "Alpha":   {"key": os.environ["ALPACA_ALPHA_KEY"],   "secret": os.environ["ALPACA_ALPHA_SECRET"]},
    "Bravo":   {"key": os.environ["ALPACA_BRAVO_KEY"],   "secret": os.environ["ALPACA_BRAVO_SECRET"]},
    "Charlie": {"key": os.environ["ALPACA_CHARLIE_KEY"], "secret": os.environ["ALPACA_CHARLIE_SECRET"]},
}

if os.getenv("ALPACA_LIVE_KEY"):
    ALPACA_KEYS["LiveMedusa"] = {"key": os.environ["ALPACA_LIVE_KEY"], "secret": os.environ["ALPACA_LIVE_SECRET"]}
