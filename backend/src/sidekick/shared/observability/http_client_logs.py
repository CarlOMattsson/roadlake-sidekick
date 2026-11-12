"""The HTTP client libraries whose loggers write request URLs.

httpx and httpcore log `HTTP Request: GET <url>` at INFO and connection details at DEBUG, and the
same libraries exist twice here (`httpx2` and `httpcore2` are what FastMCP's OAuth verifier uses).
A push endpoint, a topic or an OAuth callback URL is a capability, so these loggers are held at
WARNING in every process before any request is made. A logger level covers the child loggers
(`httpcore.connection` and so on) as well.
"""

import logging

HTTP_CLIENT_LOGGERS = ("httpx", "httpcore", "httpx2", "httpcore2")


def silence_http_client_loggers() -> None:
    """Hold every HTTP client library logger at WARNING. Idempotent."""

    for name in HTTP_CLIENT_LOGGERS:
        logging.getLogger(name).setLevel(logging.WARNING)
