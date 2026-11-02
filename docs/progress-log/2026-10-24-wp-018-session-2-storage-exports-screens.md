### 2026-10-24 — WP-018 session 2 (storage, exports, screens)

- **Built:** see the WP-018 entry. New dependencies: `aioboto3` (approved D-054/D-076; pulls
  aiobotocore, Apache-2.0) and the dev type stubs `types-aioboto3[s3]` (MIT, D-012 helper).
- **Shared changes:** `useDateTime().formatExact` (to the second), `audit.view` opens the Admin
  area, admins' fake permissions include the audit permissions, `/audit/status` in the console
  test API.
- **Tests:** backend 937 passed (94.68 %), including 6 export tests on SeaweedFS and MinIO;
  console 55 (6 new audit screen tests); chart lint for all five profiles.
