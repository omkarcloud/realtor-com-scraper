"""Configuration for the Realtor Com Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT               port the API listens on (default 8000)
    REALTOR_COM_PROXY  proxy URL for every request, e.g. http://user:pass@host:port
                       (default: none — direct). Realtor.com's GraphQL gateway
                       answered a home connection and a cloud server alike,
                       with no rate limit seen at about one request a second,
                       so you very likely don't need this. Set it only if you
                       start seeing failures at high volume.

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

# After a block (403 / 429), a worker thread keeps using the cooldown proxy
# below for this many seconds before going back to realtor_com_proxy().
REALTOR_COM_BLOCK_HOLD_S = 600

REALTOR_COM_PROXY = os.environ.get("REALTOR_COM_PROXY") or None


def realtor_com_proxy():
    """The proxy for one curl session (None = direct)."""
    return os.environ.get("REALTOR_COM_PROXY") or None


def realtor_com_cooldown_proxy():
    """The proxy a thread uses for REALTOR_COM_BLOCK_HOLD_S after a block:
    the same REALTOR_COM_PROXY (None = direct). The session is rebuilt on
    every retry, so a rotating proxy hands the retry a fresh exit."""
    return os.environ.get("REALTOR_COM_PROXY") or None
