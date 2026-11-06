"""D17 (REQ-PRB-080): a problems client (the mobile app) needs only the public API.

Every problem screen's operation is published in the OpenAPI document under /api/v1, so the
list, the record and its actions work for any client of the same API (P2), never a
screen-only route.
"""

from app.main import create_app
from conftest import make_settings

NEEDED = {
    ("get", "/api/v1/problems"),
    ("get", "/api/v1/problems/views"),
    ("post", "/api/v1/problems"),
    ("get", "/api/v1/problems/{record_id}"),
    ("patch", "/api/v1/problems/{record_id}"),
    ("post", "/api/v1/problems/{record_id}/actions/{action}"),
    ("post", "/api/v1/problems/{record_id}/assign"),
    ("get", "/api/v1/problems/{record_id}/links"),
    ("post", "/api/v1/problems/{record_id}/incidents"),
    ("post", "/api/v1/problems/{record_id}/known-error"),
    ("get", "/api/v1/problems/known-errors"),
    ("get", "/api/v1/problems/{record_id}/tasks"),
    ("get", "/api/v1/problems/{record_id}/worklogs"),
    ("get", "/api/v1/problems/{record_id}/history"),
    ("get", "/api/v1/problems/assignees"),
    ("get", "/api/v1/incidents/{record_id}/causing-problem"),
    ("get", "/api/v1/problem-repeats/hits"),
    ("post", "/api/v1/problem-repeats/hits/{hit_id}/handle"),
}


def test_d17_every_problem_operation_is_in_the_public_api() -> None:
    paths = create_app(make_settings()).openapi()["paths"]
    published = {(method, path) for path, ops in paths.items() for method in ops}
    assert sorted(NEEDED - published) == []
