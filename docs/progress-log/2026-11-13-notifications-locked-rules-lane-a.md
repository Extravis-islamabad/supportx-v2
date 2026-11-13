### 2026-11-13 — Locked notification rules (lane A, for WP-057 S2b)

Lane C's S2b-1 security notices (new-device sign-in, lock-out, password and MFA changed) must reach
the person even when a tenant admin, who may be the attacker, would rather they did not. `required`
only stopped the person's own opt-out; an admin could still switch the rule off or drop the
recipient.

- `NotificationEvent.locked` (app/shared/notifications/ports.py): the shipped default always applies.
- The engine ignores a saved rule for a locked event, including one saved before the lock.
- PUT and DELETE `/notifications/rules/{code}` refuse with 409 `notification_rule_locked`; the
  rule's `locked` field shows it; the rules screen shows "Fixed for security" with every control
  disabled and no reset.
- Break-glass sign-in alerts are locked too.
- No migration. Tests: tests/db/test_notifications_api.py (locked rule), console notifications test.
