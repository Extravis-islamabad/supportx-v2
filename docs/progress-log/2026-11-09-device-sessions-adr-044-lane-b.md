### 2026-11-09 — Signed-in devices and verified mobile links (ADR-044 items 3 and 5; lane B; #249)

ADR-044 was accepted by Haider on 2026-11-09 (#244).

- **Device sessions (item 5):**
  - every BFF session is indexed per person in Valkey (client, platform, app version, started,
    last used), encrypted like the sessions, and cleaned as sessions end;
  - My account lists the person's sessions, "this device" marked, and ends any one
    (`/api/v1/auth/sessions`);
  - an admin with people rights does the same for a person in their drawer's Devices tab
    (`/api/v1/identity/people/{id}/sessions`);
  - ending one ends that device's sign-in at once (the next call answers 401), audited as
    `session.ended`, and the lists refresh live on the person's own channel.
- **Verified links (item 3):**
  - the chart's `mobile` values name the app builds an installation trusts (iOS Team and bundle
    IDs; the Android package with its signing fingerprints) and the fixed return path
    (`/mobile/auth`);
  - the web pods serve `/.well-known/apple-app-site-association` and `assetlinks.json` from them;
    when nothing is named, there is no ConfigMap and both answer 404;
  - the mobile team moves the redirect from `supportx://` to `https://<host>/mobile/auth`
    (#236).
- **Retry safety:** the session index's HSET, HGETALL and HDEL are listed as safe to repeat in
  `app/core/valkey.py` (#278).
- **Tests:** the identity module tests, `tests/db/test_auth_bff.py`, the console session tests,
  and `tests/test_chart_mobile_links.py`; the nginx paths were checked in the web base image.
