### 2026-11-04 — WP-040 AD/LDAP built end to end; connector defaults started (lane B)

- **#175 (draft, full-ci), AD/LDAP through Keycloak federation (D-118, D-130).**
  - Service with its guards: the licence add-on, a single-tenant realm, the federation account
    installed, and plain LDAP only by an audited choice. The bind password is sealed.
  - The consumers worker writes the component and mappers as `supportx-federation`, records
    pending, applied or failed, and audits every use.
  - API `/integrations/ldap-directories`. The people sync uses the Entra engine and rules: a
    person disabled in AD or gone from it is a leaver, and an empty answer changes nobody.
  - Console section with live state. Labels in en, ar and ur.
  - Integration test against a throwaway Keycloak 26.8.1 and a test-only slapd image (heavy CI
    job "ldap federation"). It found two bugs, both fixed:
    - Keycloak's own username mapper was deleted by the replace-all step;
    - reading people and syncing need user rights, so they use `supportx-identity`, and the
      federation account keeps manage-realm only.
  - The migration is now 0056 (lane C's #176 took 0055) and follows main's 0054.
- **#185 (draft, full-ci), connector defaults per tenant (D-041; migration 0057).**
  - The failing threshold, error retention and new-directory interval, with RLS, API, audit,
    outbox and their use sites. Next: its labels and settings card once lane C's #181 lands.
  - The secret rotation reminder isn't built yet, so it has no setting (follow-up).
- **CI.**
  - #179 (two stack-smoke shards, Playwright's own run limit): first in the merge queue. Next:
    3 shards, because Playwright splits by test count and shard 1 still reaches 35 minutes.
  - #184 (flaky tampered-cursor tests) queued.
- **Reviews.**
  - #178: approved, including D-129.
  - #176: final approval.
  - Lane A builds REQ-NTF-024 action links in WP-030 s3 under lane B's review, with five
    security conditions (coordinator agreed).
- **Resume.**
  1. After #181: move #175's labels into the module label files, then #185's labels and its
     settings card.
  2. The 3-shard CI PR.
  3. #175 out of draft once its full-ci run (including "ldap federation") is green.
- **Parked for the product owner:** D-126 (the Dependabot rule; writing it was refused by this
  session's permission check).
