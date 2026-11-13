### 2026-11-13 — Lane B: mail keeps no trace of an erased person

- `app.shared.mail.forget_recipient(session, address)`: the GDPR erasure job calls it in the
  tenant's session **before** the person's address is anonymised (lane A's question on #492).
  Their address in any message's recipients becomes `erased@invalid`; a message still queued for
  others only loses them; one queued for them alone fails as `recipient_erased`; otherwise the
  subject, bodies, one-time links and attachments are cleared now instead of at
  `mail_content_retention_days`. Idempotent; exact address match (case-insensitive), never a
  substring.
- Not yet called: identity_access has no erasure job emitting `reason: erasure` today (the
  consumers that clean up on it already exist). Whoever builds the job calls this first.
- Test: test_mail_service.py (sent, queued alone, queued with another person, a near-miss address,
  another tenant, a second call).
