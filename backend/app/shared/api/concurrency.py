"""Optimistic concurrency over HTTP: ETag from the record version, If-Match on writes (WP-008).

CLAUDE.md rule g, architecture.md §10. Every editable record has an integer `version`. Its ETag is
the version as a strong entity tag (`"7"`):

    GET    /things/1           → 200, ETag: "7"     (If-None-Match: "7" → 304, no body)
    PATCH  /things/1           If-Match: "7" → 200, ETag: "8"
    PATCH  /things/1           (no If-Match) → 428 precondition_required
    PATCH  /things/1           If-Match: "6" → 409 version_conflict (expected/current version)

`If-Match: *` is refused: it would mean "overwrite whatever is there", which is exactly what the
version check exists to prevent.
"""

import re
from typing import Annotated

from fastapi import Depends, Header, Request, Response

from app.core.errors import BadRequest, PreconditionRequired

_ETAG = re.compile(r'^(W/)?"(\d{1,18})"$')


def etag_for(version: int) -> str:
    """Strong ETag for a record version."""
    return f'"{version}"'


def parse_etag(value: str) -> int:
    """Version from an ETag (`"7"`; a weak `W/"7"` is accepted too). 400 `invalid_etag` else."""
    match = _ETAG.fullmatch(value.strip())
    if match is None:
        raise BadRequest(code="invalid_etag")
    return int(match.group(2))


def set_etag(response: Response, version: int) -> None:
    """Add the ETag header to a single-record response."""
    response.headers["ETag"] = etag_for(version)


def not_modified(request: Request, version: int) -> Response | None:
    """A 304 response when the client already has this version (If-None-Match), else None."""
    sent = request.headers.get("if-none-match")
    if sent is None:
        return None
    tags = {tag.strip() for tag in sent.split(",")}
    if "*" in tags or etag_for(version) in tags or f"W/{etag_for(version)}" in tags:
        return Response(status_code=304, headers={"ETag": etag_for(version)})
    return None


def expected_version(
    if_match: Annotated[
        str | None,
        Header(
            alias="If-Match",
            description='Required. The ETag of the version you read, e.g. "7".',
        ),
    ] = None,
) -> int:
    """FastAPI dependency for PATCH/PUT/DELETE: the version the client read."""
    if if_match is None or not if_match.strip():
        raise PreconditionRequired(params={"header": "If-Match"})
    if if_match.strip() == "*" or "," in if_match:
        raise BadRequest(code="invalid_etag")
    return parse_etag(if_match)


ExpectedVersion = Annotated[int, Depends(expected_version)]
"""Use as an endpoint parameter: `version: ExpectedVersion`."""
