"""Guard: no route lets vendor support through on a right that stands in for a `never` one (D-173).

A route that accepts any of several rights (`require_permission(A, B)`) is entered with whichever
the caller holds. If one of them is `never` for vendor support and another is a covering right
(`*.manage`) support can be granted, support enters on the covering one and does what was meant
to be never: the 2026-11-24
finding (CI delete took `cmdb.delete` or `cmdb.manage`, and support held `cmdb.manage`; see
tests/db/test_support_never_through_manage.py). Every module's routes are walked; a new mixed gate
fails here until the granted right is made `never` too, or the gate stops accepting it.

What this cannot see: a service that lets a covering right stand in (`cis.writer`), or a route
gated by one covering right alone (assets' delete, pending the product owner's decision). The
DB reproduction covers those as regressions.
"""

from app.core.authorization import PERMISSION_ATTR
from app.modules.identity_access.domain import support_access
from tooling.route_permissions import api_routes, build_app, route_dependencies


def _granted() -> frozenset[str]:
    """Every right support can hold, at either access level."""
    return frozenset(
        key
        for key, decision in support_access.SUPPORT_ACCESS.items()
        if not isinstance(decision, support_access.Never)
    )


def _never() -> frozenset[str]:
    return frozenset(
        key
        for key, decision in support_access.SUPPORT_ACCESS.items()
        if isinstance(decision, support_access.Never)
    )


def test_no_route_takes_a_granted_right_in_place_of_a_never_one() -> None:
    granted, never = _granted(), _never()
    mixed: list[str] = []
    for method, path, dependant, _endpoint in api_routes(build_app()):
        for call in route_dependencies(dependant):
            rights = getattr(call, PERMISSION_ATTR, None)
            if not rights or len(rights) < 2:
                continue
            barred = [r for r in rights if r in never]
            # A covering right (`*.manage`) held by support, accepted in place of a never one:
            # the 2026-11-24 shape. A narrow right support is meant to hold (`config.assets`)
            # beside a never broad one (`settings.manage`) is the safe way round.
            covering = [r for r in rights if r in granted and r.endswith(".manage")]
            if barred and covering:
                mixed.append(f"{method} {path}: {sorted(barred)} never, {sorted(covering)} held")
    assert mixed == [], "\n".join(mixed)


def test_cmdb_manage_is_never_for_support() -> None:
    """The CMDB's covering right (delete, restore, merge) is a tenant decision for support."""
    decided = support_access.SUPPORT_ACCESS["cmdb.manage"]
    assert isinstance(decided, support_access.Never)
    assert decided.reason == "tenant_decision"
