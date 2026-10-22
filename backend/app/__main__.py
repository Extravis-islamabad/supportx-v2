"""Production entry point: `python -m app` serves the API with uvicorn (no reload).

Host and port come from SUPPORTX_HTTP_HOST / SUPPORTX_HTTP_PORT. Logging is configured by the
app factory, so uvicorn's own log config is disabled and its access log replaced by ours.
"""

import uvicorn

from app.core.config import get_settings


def main() -> None:
    """Serve the app factory with uvicorn."""
    settings = get_settings()
    uvicorn.run(
        "app.main:create_app",
        factory=True,
        host=settings.http_host,
        port=settings.http_port,
        log_config=None,
        access_log=False,
        proxy_headers=True,
        server_header=False,
    )


if __name__ == "__main__":  # pragma: no cover - module entry point
    main()
