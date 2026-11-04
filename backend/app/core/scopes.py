"""API key scopes from permission keys (REQ-INT-021, D-128).

Pure, shared by the policy layer (identity_access) and the published contract (`x-scopes` in
the OpenAPI document).

A permission `<area>.<action>` needs the scope `<area>:read` when its action views, reads,
searches, lists or exports, and `<area>:write` otherwise.
"""

READ_ACTIONS = frozenset({"view", "read", "export", "search", "list"})


def scope_of(permission: str) -> str:
    """`incidents.view` → `incidents:read`; `incidents.create` → `incidents:write`."""
    area, _, action = permission.partition(".")
    kind = "read" if action.split("_", 1)[0] in READ_ACTIONS else "write"
    return f"{area}:{kind}"
