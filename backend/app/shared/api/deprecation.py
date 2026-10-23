"""Deprecating an endpoint (architecture.md §10: deprecation headers, 12-month sunset; WP-008).

    OLD_SEARCH = Deprecation(since=date(2026, 11, 1), sunset=date(2027, 11, 1),
                             link="https://docs.supportx.example/api/v1/search")

    @router.get("/old-search", deprecated=True, dependencies=[OLD_SEARCH.dependency])

Every response then carries (RFC 9745 / RFC 8594):

    Deprecation: @1793491200
    Sunset: Mon, 01 Nov 2027 00:00:00 GMT
    Link: <https://docs...>; rel="deprecation"

`deprecated=True` marks the operation in the OpenAPI document, so generated clients warn too.
"""

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from email.utils import format_datetime
from typing import Any

from fastapi import Depends, Response

MIN_SUNSET_NOTICE = timedelta(days=365)


@dataclass(frozen=True)
class Deprecation:
    """When an endpoint was deprecated and when it goes away."""

    since: date
    sunset: date
    link: str | None = None

    def __post_init__(self) -> None:
        """Refuse a sunset sooner than the promised notice period."""
        if self.sunset - self.since < MIN_SUNSET_NOTICE:
            msg = "architecture.md §10 promises at least 12 months between deprecation and sunset"
            raise ValueError(msg)

    def headers(self) -> dict[str, str]:
        """The three headers."""
        since = datetime.combine(self.since, datetime.min.time(), tzinfo=UTC)
        sunset = datetime.combine(self.sunset, datetime.min.time(), tzinfo=UTC)
        headers = {
            "Deprecation": f"@{int(since.timestamp())}",
            "Sunset": format_datetime(sunset, usegmt=True),
        }
        if self.link:
            headers["Link"] = f'<{self.link}>; rel="deprecation"'
        return headers

    @property
    def dependency(self) -> Any:  # noqa: ANN401 - a FastAPI Depends marker
        """`dependencies=[deprecation.dependency]`."""

        async def add_headers(response: Response) -> None:
            response.headers.update(self.headers())

        return Depends(add_headers)
