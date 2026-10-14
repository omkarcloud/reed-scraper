"""Configuration for the Reed Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT        port the API listens on (default 8000)
    REED_PROXY  proxy URL for every request, e.g. http://user:pass@host:port
                (default: none — direct). reed.co.uk answered every page and
                JSON route on the first try from one IP, with no challenge, so
                you very likely don't need this. Set it only if you start
                seeing 403 / 429 at high volume.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

# Block fallback: after a 403 / 429 new sessions may switch to a separate
# proxy for REED_BLOCK_COOLDOWN seconds. Off here — with REED_PROXY set
# every request already goes through it.
REED_BLOCK_COOLDOWN = 900


def reed_proxy():
    """Proxy URL for a new session (None = direct)."""
    return os.environ.get("REED_PROXY") or None


def reed_fallback_proxy():
    """Proxy for a blocked worker (None = no fallback; see above)."""
    return None
