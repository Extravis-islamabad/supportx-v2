# 11 — Administration, users, security and audit

Parity requirements for administration (users, roles, groups, organisation structure,
customisation, settings, mail, surveys, announcements, data administration and privacy), for
sign-in and security (architecture.md §11), and for the audit log and the other admin logs
(architecture.md §7.4). Rules, ID scheme and field meanings: [README.md](README.md).

**Status:** Draft v0.1, 2026-10-24. Phase 2, first draft for product owner review.
**Owner:** Haider (Product Owner).

## Scope of this file

- **REQ-ADM-*** are administration requirements: people (technicians and requesters), their
  import, deactivation and hand-over; roles and the permission catalogue; support groups, user
  groups and organisation roles; regions, sites and departments; customisation; instance
  settings, languages, labels and branding; personal preferences; mail server settings;
  surveys; announcement authoring (the `announcements` module, ADR-024, D-032); data import,
  export, archive and retention; sandbox and configuration as code; privacy; the setup area
  itself and the licence page.
- **REQ-SEC-*** are sign-in and security requirements: authentication through Keycloak and the
  backend-for-frontend (ADR-006, D-009, D-010), local accounts and single sign-on, invitations,
  multi-factor authentication, sessions, network restrictions, API keys and service accounts,
  encryption, data residency and the security overview.
- **REQ-AUD-*** are audit requirements: the tamper-evident audit log (D-034, WP-018), the sign-in
  log, the system log, the personal data access log, the telephony log and compliance evidence.
- **Built on the engine, not restated.** File 01 holds the permission model by action and scope
  (REQ-WI-015), field-level visibility (REQ-WI-016), entitlements (REQ-WI-017), audit of
  privileged actions on records (REQ-WI-021), labels and languages (REQ-WI-013), the date and
  time formatter (REQ-WI-014), accessibility (REQ-WI-023) and features outside the edition
  (REQ-WI-025). This file adds the admin screens and rules around them.
- **Not in this file** (each has its own module file, see the README):
  - operating hours, holidays, absence types, auto-assignment, business rules, custom
    functions, connections, global variables, custom menus, life cycles and the notification
    engine and templates (file 03); this file only links sites and groups to them and gives
    mail its server settings;
  - approval settings and the approval engine (file 02); the requester portal settings page
    (REQ-PRT-031), portal branding and domains (REQ-PRT-016) and portal navigation
    (REQ-PRT-019);
  - fine-grained access for assets and CIs (REQ-CMDB-029), cost centres and GL codes
    (REQ-PUR-017), project roles (REQ-PRJ-011, REQ-PRJ-012) and release roles (REQ-REL-023);
  - survey reports (REQ-RPT-018) and all other reports and dashboards (file 09);
  - AI administration, model access, masking rules and AI logs (file 10); this file holds the
    AI permissions in the role editor (REQ-AI-028, REQ-AI-033), masking events in the personal
    data access log (REQ-AI-019) and erasure of AI logs (REQ-AI-032);
  - in file 12: mailbox connections, outgoing mail and sending domains (REQ-INT-050 to
    REQ-INT-055); directory sync from Entra ID, Active Directory and SCIM, including leavers
    (REQ-INT-063 to REQ-INT-066); API keys, OAuth clients and scopes (REQ-INT-019 to
    REQ-INT-021); connector service identities (REQ-INT-012); telephony (REQ-INT-078);
    webhooks and extensions; and department desks with their desk admins and desk-private
    records (REQ-ESM-009, REQ-ESM-011, REQ-ESM-012). This file holds the admin screens and
    policies around them, and what the product does with the people a connector brings in.
- **Monitoring is out of scope** (ADR-017, D-001). Nothing in this file polls devices or
  correlates alerts. The platform status page (REQ-ADM-112) shows SupportX's own services
  only.
- **Editions** (product-plan §9): administration, sign-in, multi-factor authentication, single
  sign-on and the audit log are Essentials; attribute conditions, field-level rules and
  field-level encryption are Professional; sandbox, configuration as code, customer-managed
  keys and compliance evidence packs are Enterprise. **Timing** (architecture §17): identity,
  roles, sites, branding and announcements are Stage 1 (MVP); the audit log, import and export
  tooling, surveys and privacy tooling are V1; sandbox, configuration as code and compliance
  packs are Stage 3 (LATER).

## Words used in this file

| Word | Meaning |
|---|---|
| Person | Anyone known to the tenant: a technician, a requester, or both. One record per person. |
| Technician | A person with staff access who works on records. Technicians count against the licence. |
| Requester | A person who uses the portal or emails the service desk. Requesters are unlimited. |
| Role | A named set of grants. A grant is a permission at a scope, with an optional condition (ADR-022). |
| Permission | One action on one module, for example `incident.merge`, declared by the module that owns it. |
| Scope | How far a grant reaches: all, site, group or own (REQ-WI-015). |
| Support group | A team of technicians that work is assigned to. |
| User group | A set of people defined by rules, by named members, or both. Used for audiences. |
| Organisation role | A position relative to the structure, for example department head or site manager. |
| Tenant | One customer's isolated space. On-prem installs have one tenant. |
| BFF | The backend-for-frontend login layer that holds tokens server-side (D-009). |
| MFA | Multi-factor authentication: a second proof besides the password. |
| Step-up | Asking a signed-in person to prove their identity again before a sensitive action. |
| Audit log | The append-only, hash-chained log of security-relevant actions (architecture §7.4). |
| Field history | The per-record history of field changes (REQ-WI-003). It is not the audit log. |

## Requirement summary

<!-- summary:start -->
**Counts by decision and priority**

| Decision | MVP | V1 | LATER | Total |
|---|---|---|---|---|
| SAME | 23 | 36 | 8 | 67 |
| BETTER | 29 | 25 | 2 | 56 |
| NEW | 10 | 40 | 5 | 55 |
| SKIP | 0 | 0 | 1 | 1 |
| **Total** | **62** | **101** | **16** | **179** |

Edition (lowest edition that includes it): Essentials 161, Professional 10, Enterprise 8. By prefix: REQ-ADM 113, REQ-SEC 47, REQ-AUD 19.

| ID | Title | Decision | Priority | Edition |
|---|---|---|---|---|
| [REQ-ADM-001](#req-adm-001--one-list-of-people) | One list of people | BETTER | MVP | Essentials |
| [REQ-ADM-002](#req-adm-002--the-person-record) | The person record | SAME | MVP | Essentials |
| [REQ-ADM-003](#req-adm-003--one-person-technician-requester-or-both) | One person, technician, requester or both | BETTER | MVP | Essentials |
| [REQ-ADM-004](#req-adm-004--sign-in-access-without-hidden-prerequisites) | Sign-in access without hidden prerequisites | BETTER | MVP | Essentials |
| [REQ-ADM-005](#req-adm-005--custom-fields-on-people) | Custom fields on people | SAME | V1 | Essentials |
| [REQ-ADM-006](#req-adm-006--cost-per-hour-behind-a-permission) | Cost per hour behind a permission | SAME | V1 | Essentials |
| [REQ-ADM-007](#req-adm-007--where-a-person-is-used) | Where a person is used | SAME | V1 | Essentials |
| [REQ-ADM-008](#req-adm-008--bulk-actions-on-people) | Bulk actions on people | SAME | V1 | Essentials |
| [REQ-ADM-009](#req-adm-009--technician-seats-against-the-licence-requesters-unlimited) | Technician seats against the licence; requesters unlimited | NEW | MVP | Essentials |
| [REQ-ADM-010](#req-adm-010--deactivate-instead-of-delete) | Deactivate instead of delete | BETTER | MVP | Essentials |
| [REQ-ADM-011](#req-adm-011--hand-over-ownership-when-someone-leaves) | Hand over ownership when someone leaves | BETTER | V1 | Essentials |
| [REQ-ADM-012](#req-adm-012--merge-duplicate-people) | Merge duplicate people | NEW | V1 | Essentials |
| [REQ-ADM-013](#req-adm-013--import-people) | Import people | SAME | MVP | Essentials |
| [REQ-ADM-014](#req-adm-014--people-from-a-directory) | People from a directory | BETTER | V1 | Essentials |
| [REQ-ADM-015](#req-adm-015--roles-built-from-module-action-and-scope) | Roles built from module, action and scope | SAME | MVP | Essentials |
| [REQ-ADM-016](#req-adm-016--one-permission-catalogue-from-every-module) | One permission catalogue from every module | BETTER | MVP | Essentials |
| [REQ-ADM-017](#req-adm-017--built-in-roles-can-be-read-compared-and-copied) | Built-in roles can be read, compared and copied | BETTER | MVP | Essentials |
| [REQ-ADM-018](#req-adm-018--roles-a-new-tenant-starts-with) | Roles a new tenant starts with | SAME | MVP | Essentials |
| [REQ-ADM-019](#req-adm-019--configuration-rights-per-area) | Configuration rights per area | SAME | MVP | Essentials |
| [REQ-ADM-020](#req-adm-020--site-administrators) | Site administrators | SAME | V1 | Essentials |
| [REQ-ADM-021](#req-adm-021--no-privilege-escalation-no-lock-out) | No privilege escalation, no lock-out | NEW | MVP | Essentials |
| [REQ-ADM-022](#req-adm-022--segregation-of-duties-warnings-when-designing-roles) | Segregation-of-duties warnings when designing roles | NEW | V1 | Professional |
| [REQ-ADM-023](#req-adm-023--who-may-approve) | Who may approve | SAME | V1 | Essentials |
| [REQ-ADM-024](#req-adm-024--explain-a-persons-access) | Explain a person's access | NEW | V1 | Essentials |
| [REQ-ADM-025](#req-adm-025--conditions-on-grants) | Conditions on grants | NEW | V1 | Professional |
| [REQ-ADM-026](#req-adm-026--field-access-rules-in-the-role-editor) | Field access rules in the role editor | NEW | V1 | Professional |
| [REQ-ADM-027](#req-adm-027--time-limited-role-assignments) | Time-limited role assignments | NEW | V1 | Essentials |
| [REQ-ADM-028](#req-adm-028--access-reviews) | Access reviews | NEW | LATER | Enterprise |
| [REQ-ADM-029](#req-adm-029--ai-access-in-the-role-editor) | AI access in the role editor | NEW | V1 | Essentials |
| [REQ-ADM-030](#req-adm-030--roles-per-department-desk) | Roles per department desk | BETTER | LATER | Enterprise |
| [REQ-ADM-031](#req-adm-031--support-groups) | Support groups | BETTER | MVP | Essentials |
| [REQ-ADM-032](#req-adm-032--making-a-group-inactive-safely) | Making a group inactive safely | BETTER | V1 | Essentials |
| [REQ-ADM-033](#req-adm-033--user-groups-with-rules-and-named-members) | User groups with rules and named members | BETTER | V1 | Essentials |
| [REQ-ADM-034](#req-adm-034--organisation-roles) | Organisation roles | SAME | V1 | Essentials |
| [REQ-ADM-035](#req-adm-035--reporting-lines) | Reporting lines | SAME | MVP | Essentials |
| [REQ-ADM-036](#req-adm-036--regions) | Regions | SAME | V1 | Essentials |
| [REQ-ADM-037](#req-adm-037--sites) | Sites | SAME | MVP | Essentials |
| [REQ-ADM-038](#req-adm-038--site-settings-inherit-copy-or-own) | Site settings: inherit, copy or own | SAME | V1 | Essentials |
| [REQ-ADM-039](#req-adm-039--departments) | Departments | BETTER | MVP | Essentials |
| [REQ-ADM-040](#req-adm-040--calendars-and-absence-types-linked-to-sites-and-groups) | Calendars and absence types linked to sites and groups | SAME | MVP | Essentials |
| [REQ-ADM-041](#req-adm-041--custom-fields-for-every-module-from-one-place) | Custom fields for every module from one place | BETTER | MVP | Essentials |
| [REQ-ADM-042](#req-adm-042--safe-changes-to-fields-in-use) | Safe changes to fields in use | NEW | V1 | Essentials |
| [REQ-ADM-043](#req-adm-043--pick-lists-with-translations-order-and-colour) | Pick lists with translations, order and colour | SAME | MVP | Essentials |
| [REQ-ADM-044](#req-adm-044--one-customisation-home-per-module) | One customisation home per module | BETTER | V1 | Essentials |
| [REQ-ADM-045](#req-adm-045--numbering-for-every-record-type-on-one-page) | Numbering for every record type on one page | BETTER | MVP | Essentials |
| [REQ-ADM-046](#req-adm-046--reusable-sub-forms) | Reusable sub-forms | SAME | V1 | Essentials |
| [REQ-ADM-047](#req-adm-047--custom-modules) | Custom modules | SAME | LATER | Professional |
| [REQ-ADM-048](#req-adm-048--customisation-versions-preview-and-history) | Customisation versions, preview and history | BETTER | V1 | Essentials |
| [REQ-ADM-049](#req-adm-049--instance-settings) | Instance settings | BETTER | MVP | Essentials |
| [REQ-ADM-050](#req-adm-050--base-currency) | Base currency | SAME | MVP | Essentials |
| [REQ-ADM-051](#req-adm-051--more-currencies-and-exchange-rates) | More currencies and exchange rates | SAME | LATER | Professional |
| [REQ-ADM-052](#req-adm-052--languages-offered-in-the-tenant) | Languages offered in the tenant | BETTER | MVP | Essentials |
| [REQ-ADM-053](#req-adm-053--translations-of-admin-created-values) | Translations of admin-created values | BETTER | V1 | Essentials |
| [REQ-ADM-054](#req-adm-054--terminology-per-tenant) | Terminology per tenant | NEW | V1 | Essentials |
| [REQ-ADM-055](#req-adm-055--branding-for-the-console-sign-in-and-email) | Branding for the console, sign-in and email | SAME | MVP | Essentials |
| [REQ-ADM-056](#req-adm-056--how-far-people-may-personalise) | How far people may personalise | SAME | V1 | Essentials |
| [REQ-ADM-057](#req-adm-057--default-navigation-for-technicians) | Default navigation for technicians | SAME | V1 | Essentials |
| [REQ-ADM-058](#req-adm-058--one-preferences-page-that-follows-the-person) | One preferences page that follows the person | BETTER | MVP | Essentials |
| [REQ-ADM-059](#req-adm-059--language-time-zone-and-formats-per-person) | Language, time zone and formats per person | SAME | MVP | Essentials |
| [REQ-ADM-060](#req-adm-060--navigation-layout) | Navigation layout | SAME | MVP | Essentials |
| [REQ-ADM-061](#req-adm-061--personal-module-order) | Personal module order | SAME | V1 | Essentials |
| [REQ-ADM-062](#req-adm-062--theme-and-text-size) | Theme and text size | BETTER | MVP | Essentials |
| [REQ-ADM-063](#req-adm-063--accessibility-preferences) | Accessibility preferences | SAME | V1 | Essentials |
| [REQ-ADM-064](#req-adm-064--accessibility-switches-left-to-the-operating-system) | Accessibility switches left to the operating system | SKIP | LATER | Essentials |
| [REQ-ADM-065](#req-adm-065--email-signature-and-editor-defaults) | Email signature and editor defaults | SAME | V1 | Essentials |
| [REQ-ADM-066](#req-adm-066--one-mail-page-in-setup) | One mail page in setup | SAME | MVP | Essentials |
| [REQ-ADM-067](#req-adm-067--fetched-mail-is-kept-not-deleted) | Fetched mail is kept, not deleted | BETTER | MVP | Essentials |
| [REQ-ADM-068](#req-adm-068--mail-and-notification-templates-in-setup) | Mail and notification templates in setup | SAME | V1 | Essentials |
| [REQ-ADM-069](#req-adm-069--surveys-per-work-item-type) | Surveys per work item type | BETTER | V1 | Essentials |
| [REQ-ADM-070](#req-adm-070--survey-questions-and-rating-scale) | Survey questions and rating scale | BETTER | V1 | Essentials |
| [REQ-ADM-071](#req-adm-071--survey-translations) | Survey translations | SAME | V1 | Essentials |
| [REQ-ADM-072](#req-adm-072--survey-messages-and-email) | Survey messages and email | SAME | V1 | Essentials |
| [REQ-ADM-073](#req-adm-073--when-surveys-are-sent) | When surveys are sent | BETTER | V1 | Essentials |
| [REQ-ADM-074](#req-adm-074--preview-and-test-a-survey) | Preview and test a survey | SAME | V1 | Essentials |
| [REQ-ADM-075](#req-adm-075--survey-results) | Survey results | SAME | V1 | Essentials |
| [REQ-ADM-076](#req-adm-076--surveys-without-email) | Surveys without email | BETTER | V1 | Essentials |
| [REQ-ADM-077](#req-adm-077--announcements) | Announcements | SAME | MVP | Essentials |
| [REQ-ADM-078](#req-adm-078--publish-window-and-status-flow-live-everywhere) | Publish window and status flow, live everywhere | BETTER | MVP | Essentials |
| [REQ-ADM-079](#req-adm-079--second-person-publishing) | Second-person publishing | NEW | MVP | Essentials |
| [REQ-ADM-080](#req-adm-080--announcement-types-and-templates) | Announcement types and templates | SAME | V1 | Essentials |
| [REQ-ADM-081](#req-adm-081--tell-the-audience) | Tell the audience | SAME | V1 | Essentials |
| [REQ-ADM-082](#req-adm-082--views-and-acknowledgements) | Views and acknowledgements | BETTER | V1 | Essentials |
| [REQ-ADM-083](#req-adm-083--announcements-in-several-languages) | Announcements in several languages | NEW | V1 | Essentials |
| [REQ-ADM-084](#req-adm-084--announcement-permissions) | Announcement permissions | SAME | MVP | Essentials |
| [REQ-ADM-085](#req-adm-085--import-data-into-every-module) | Import data into every module | SAME | V1 | Essentials |
| [REQ-ADM-086](#req-adm-086--map-check-and-try-before-importing) | Map, check and try before importing | BETTER | V1 | Essentials |
| [REQ-ADM-087](#req-adm-087--duplicate-handling) | Duplicate handling | BETTER | V1 | Essentials |
| [REQ-ADM-088](#req-adm-088--large-imports-in-the-background-no-record-cap) | Large imports in the background, no record cap | BETTER | V1 | Essentials |
| [REQ-ADM-089](#req-adm-089--import-history-and-undo) | Import history and undo | BETTER | V1 | Essentials |
| [REQ-ADM-090](#req-adm-090--microsoft-project-plans) | Microsoft Project plans | SAME | LATER | Professional |
| [REQ-ADM-091](#req-adm-091--import-templates-per-module) | Import templates per module | SAME | V1 | Essentials |
| [REQ-ADM-092](#req-adm-092--imported-records-keep-their-past) | Imported records keep their past | BETTER | V1 | Essentials |
| [REQ-ADM-093](#req-adm-093--export-everything) | Export everything | BETTER | V1 | Essentials |
| [REQ-ADM-094](#req-adm-094--export-a-module) | Export a module | BETTER | V1 | Essentials |
| [REQ-ADM-095](#req-adm-095--archive-policies-for-every-module) | Archive policies for every module | SAME | LATER | Essentials |
| [REQ-ADM-096](#req-adm-096--retention-for-every-log-and-bin) | Retention for every log and bin | NEW | V1 | Essentials |
| [REQ-ADM-097](#req-adm-097--sandbox) | Sandbox | SAME | LATER | Enterprise |
| [REQ-ADM-098](#req-adm-098--configuration-as-code) | Configuration as code | BETTER | LATER | Enterprise |
| [REQ-ADM-099](#req-adm-099--privacy-settings) | Privacy settings | SAME | V1 | Essentials |
| [REQ-ADM-100](#req-adm-100--a-persons-data-on-request) | A person's data on request | SAME | V1 | Essentials |
| [REQ-ADM-101](#req-adm-101--erasure-and-anonymisation) | Erasure and anonymisation | SAME | V1 | Essentials |
| [REQ-ADM-102](#req-adm-102--privacy-notice-and-consent) | Privacy notice and consent | NEW | V1 | Essentials |
| [REQ-ADM-103](#req-adm-103--masking-personal-data) | Masking personal data | NEW | V1 | Professional |
| [REQ-ADM-104](#req-adm-104--retention-of-personal-data-per-record-type) | Retention of personal data per record type | SAME | LATER | Essentials |
| [REQ-ADM-105](#req-adm-105--legal-hold) | Legal hold | NEW | LATER | Enterprise |
| [REQ-ADM-106](#req-adm-106--setup-home-organised-by-task) | Setup home organised by task | BETTER | MVP | Essentials |
| [REQ-ADM-107](#req-adm-107--setup-search-by-keyword-and-meaning) | Setup search by keyword and meaning | BETTER | MVP | Essentials |
| [REQ-ADM-108](#req-adm-108--stable-setup-navigation) | Stable setup navigation | BETTER | MVP | Essentials |
| [REQ-ADM-109](#req-adm-109--licence-and-plan-page) | Licence and plan page | SAME | MVP | Essentials |
| [REQ-ADM-110](#req-adm-110--warnings-before-limits-and-expiry) | Warnings before limits and expiry | NEW | V1 | Essentials |
| [REQ-ADM-111](#req-adm-111--activate-and-renew-on-prem) | Activate and renew on-prem | NEW | V1 | Essentials |
| [REQ-ADM-112](#req-adm-112--platform-status-for-admins) | Platform status for admins | NEW | V1 | Essentials |
| [REQ-ADM-113](#req-adm-113--getting-started-checklist) | Getting started checklist | SAME | V1 | Essentials |
| [REQ-SEC-001](#req-sec-001--sign-in-through-keycloak-and-the-backend-for-frontend) | Sign-in through Keycloak and the backend-for-frontend | NEW | MVP | Essentials |
| [REQ-SEC-002](#req-sec-002--no-outside-vendor-account) | No outside vendor account | BETTER | MVP | Essentials |
| [REQ-SEC-003](#req-sec-003--tenant-branded-sign-in-page) | Tenant-branded sign-in page | BETTER | MVP | Essentials |
| [REQ-SEC-004](#req-sec-004--finding-the-tenant-at-sign-in) | Finding the tenant at sign-in | NEW | MVP | Essentials |
| [REQ-SEC-005](#req-sec-005--local-accounts-and-password-policy) | Local accounts and password policy | BETTER | MVP | Essentials |
| [REQ-SEC-006](#req-sec-006--password-reset) | Password reset | SAME | MVP | Essentials |
| [REQ-SEC-007](#req-sec-007--saml-single-sign-on-per-tenant) | SAML single sign-on per tenant | SAME | MVP | Essentials |
| [REQ-SEC-008](#req-sec-008--openid-connect-single-sign-on-per-tenant) | OpenID Connect single sign-on per tenant | SAME | MVP | Essentials |
| [REQ-SEC-009](#req-sec-009--enforce-single-sign-on-keep-a-break-glass-account) | Enforce single sign-on, keep a break-glass account | BETTER | V1 | Essentials |
| [REQ-SEC-010](#req-sec-010--verified-email-domains) | Verified email domains | SAME | V1 | Essentials |
| [REQ-SEC-011](#req-sec-011--expiring-certificates-and-secrets) | Expiring certificates and secrets | NEW | V1 | Essentials |
| [REQ-SEC-012](#req-sec-012--directory-sign-in-on-prem) | Directory sign-in on-prem | SAME | V1 | Essentials |
| [REQ-SEC-013](#req-sec-013--first-sign-in-creates-the-person) | First sign-in creates the person | NEW | MVP | Essentials |
| [REQ-SEC-014](#req-sec-014--roles-from-identity-provider-groups) | Roles from identity provider groups | NEW | V1 | Essentials |
| [REQ-SEC-015](#req-sec-015--dedicated-identity-realm) | Dedicated identity realm | NEW | V1 | Enterprise |
| [REQ-SEC-016](#req-sec-016--people-in-more-than-one-tenant) | People in more than one tenant | NEW | V1 | Essentials |
| [REQ-SEC-017](#req-sec-017--all-identity-settings-inside-the-product) | All identity settings inside the product | BETTER | MVP | Essentials |
| [REQ-SEC-018](#req-sec-018--invitations-in-the-tenants-name) | Invitations in the tenant's name | BETTER | MVP | Essentials |
| [REQ-SEC-019](#req-sec-019--no-personal-address-of-the-inviter) | No personal address of the inviter | BETTER | MVP | Essentials |
| [REQ-SEC-020](#req-sec-020--invitation-life-cycle) | Invitation life cycle | SAME | MVP | Essentials |
| [REQ-SEC-021](#req-sec-021--invite-without-mail) | Invite without mail | NEW | V1 | Essentials |
| [REQ-SEC-022](#req-sec-022--mfa-with-standard-authenticator-apps) | MFA with standard authenticator apps | BETTER | MVP | Essentials |
| [REQ-SEC-023](#req-sec-023--passkeys-and-security-keys) | Passkeys and security keys | NEW | V1 | Essentials |
| [REQ-SEC-024](#req-sec-024--mfa-policy) | MFA policy | BETTER | MVP | Essentials |
| [REQ-SEC-025](#req-sec-025--recovery-codes-and-mfa-reset) | Recovery codes and MFA reset | SAME | MVP | Essentials |
| [REQ-SEC-026](#req-sec-026--mfa-with-single-sign-on) | MFA with single sign-on | NEW | V1 | Essentials |
| [REQ-SEC-027](#req-sec-027--confirm-identity-again-for-sensitive-actions) | Confirm identity again for sensitive actions | BETTER | V1 | Essentials |
| [REQ-SEC-028](#req-sec-028--my-account-inside-the-product) | My account inside the product | BETTER | MVP | Essentials |
| [REQ-SEC-029](#req-sec-029--session-timeouts) | Session timeouts | BETTER | MVP | Essentials |
| [REQ-SEC-030](#req-sec-030--active-sessions-and-sign-out-everywhere) | Active sessions and sign out everywhere | SAME | V1 | Essentials |
| [REQ-SEC-031](#req-sec-031--sessions-end-when-access-ends) | Sessions end when access ends | NEW | MVP | Essentials |
| [REQ-SEC-032](#req-sec-032--concurrent-session-limit) | Concurrent session limit | SAME | LATER | Essentials |
| [REQ-SEC-033](#req-sec-033--sign-in-alerts-to-the-person) | Sign-in alerts to the person | NEW | V1 | Essentials |
| [REQ-SEC-034](#req-sec-034--ip-allow-lists) | IP allow-lists | NEW | V1 | Essentials |
| [REQ-SEC-035](#req-sec-035--brute-force-and-rate-limits) | Brute-force and rate limits | SAME | MVP | Essentials |
| [REQ-SEC-036](#req-sec-036--service-accounts) | Service accounts | NEW | V1 | Essentials |
| [REQ-SEC-037](#req-sec-037--tenant-policy-for-api-keys-and-tokens) | Tenant policy for API keys and tokens | BETTER | V1 | Essentials |
| [REQ-SEC-038](#req-sec-038--sign-in-for-the-mobile-app-and-other-apps) | Sign-in for the mobile app and other apps | NEW | V1 | Essentials |
| [REQ-SEC-039](#req-sec-039--encryption-in-transit-and-at-rest) | Encryption in transit and at rest | NEW | MVP | Essentials |
| [REQ-SEC-040](#req-sec-040--field-level-encryption) | Field-level encryption | NEW | V1 | Professional |
| [REQ-SEC-041](#req-sec-041--customer-managed-keys) | Customer-managed keys | NEW | LATER | Enterprise |
| [REQ-SEC-042](#req-sec-042--secrets-in-settings-are-write-only) | Secrets in settings are write-only | NEW | MVP | Essentials |
| [REQ-SEC-043](#req-sec-043--data-residency) | Data residency | NEW | LATER | Essentials |
| [REQ-SEC-044](#req-sec-044--security-overview-page) | Security overview page | NEW | V1 | Essentials |
| [REQ-SEC-045](#req-sec-045--vendor-support-access-with-consent) | Vendor support access with consent | NEW | V1 | Essentials |
| [REQ-SEC-046](#req-sec-046--application-security-baseline) | Application security baseline | NEW | MVP | Essentials |
| [REQ-SEC-047](#req-sec-047--mobile-app-access-policy) | Mobile app access policy | NEW | V1 | Essentials |
| [REQ-AUD-001](#req-aud-001--tamper-evident-audit-log) | Tamper-evident audit log | BETTER | V1 | Essentials |
| [REQ-AUD-002](#req-aud-002--what-is-audited) | What is audited | SAME | V1 | Essentials |
| [REQ-AUD-003](#req-aud-003--what-an-entry-shows) | What an entry shows | BETTER | V1 | Essentials |
| [REQ-AUD-004](#req-aud-004--reads-of-sensitive-settings-and-data) | Reads of sensitive settings and data | SAME | V1 | Essentials |
| [REQ-AUD-005](#req-aud-005--refused-and-failed-attempts) | Refused and failed attempts | NEW | V1 | Essentials |
| [REQ-AUD-006](#req-aud-006--audit-and-field-history-linked) | Audit and field history linked | NEW | V1 | Essentials |
| [REQ-AUD-007](#req-aud-007--search-and-filters) | Search and filters | SAME | V1 | Essentials |
| [REQ-AUD-008](#req-aud-008--who-may-read-the-audit-log) | Who may read the audit log | NEW | V1 | Essentials |
| [REQ-AUD-009](#req-aud-009--export-for-auditors) | Export for auditors | SAME | V1 | Essentials |
| [REQ-AUD-010](#req-aud-010--verify-the-chain) | Verify the chain | NEW | V1 | Essentials |
| [REQ-AUD-011](#req-aud-011--stream-to-a-security-monitoring-system) | Stream to a security monitoring system | NEW | V1 | Professional |
| [REQ-AUD-012](#req-aud-012--audit-retention-and-archive) | Audit retention and archive | NEW | V1 | Essentials |
| [REQ-AUD-013](#req-aud-013--erasure-keeps-the-chain-verifiable) | Erasure keeps the chain verifiable | NEW | V1 | Essentials |
| [REQ-AUD-014](#req-aud-014--ai-agent-actions-in-the-audit-log) | AI agent actions in the audit log | NEW | V1 | Essentials |
| [REQ-AUD-015](#req-aud-015--sign-in-log) | Sign-in log | NEW | V1 | Essentials |
| [REQ-AUD-016](#req-aud-016--system-log) | System log | BETTER | V1 | Essentials |
| [REQ-AUD-017](#req-aud-017--personal-data-access-log) | Personal data access log | SAME | V1 | Professional |
| [REQ-AUD-018](#req-aud-018--telephony-and-channel-log) | Telephony and channel log | SAME | LATER | Essentials |
| [REQ-AUD-019](#req-aud-019--compliance-evidence-packs) | Compliance evidence packs | NEW | LATER | Enterprise |
<!-- summary:end -->

---

## 1. People: technicians and requesters

#### REQ-ADM-001 — One list of people

Admins manage every person in one list with views for all people, technicians, requesters and
deactivated people, and a filter for sign-in state: can sign in, no sign-in, invited and not
yet accepted. The list has a column chooser, sorting, search by name, email, employee ID and
phone, a total count, and the standard page sizes and paging of every list (REQ-INC-110).

- **Decision:** BETTER. Same list, plus a deactivated view and a visible total.
- **Source:** sdp-area-11 §Screens (users list, view menu, user category filter, page size),
  §Weak spots
- **SDP weak spot fixed:** the users grid starts at 10 rows with a hidden total, and some setup
  links showed the users grid under another page's heading until a reload.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The technicians view lists only people with technician access, and the count above the
     list matches the rows across all pages.
  2. Searching an employee ID returns the matching person in under 1 second on 50,000 people.
  3. A person added in another browser appears in the open list without a reload.
  4. Every setup page shows its own heading and content on first open, with no reload.

#### REQ-ADM-002 — The person record

A person has:

- display name (optional override), first name (required) and last name;
- employee ID, job title and a short description;
- email addresses (one primary, used for sign-in and notifications), phone and mobile;
- site, department and reporting manager;
- language, time zone and VIP flag (REQ-INC-004);
- a photo, and custom fields (REQ-ADM-005).

Technicians also have sites and support groups they work in, roles, and a cost per hour
(REQ-ADM-006).

- **Decision:** SAME.
- **Source:** sdp-area-11 §Fields (new technician form, new requester form)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Saving a person without a first name is refused with a message on the field.
  2. Two active people cannot share a primary email address; the second save is refused and
     names the existing person (if the admin may see them).
  3. A person's language and time zone are used for their screens and notifications
     (REQ-ADM-059).

#### REQ-ADM-003 — One person, technician, requester or both

A person is one record. Technician access is added or removed on that record, so a requester
can become a technician and back without a second account. Their requests, history and
approvals stay with them. A technician can also raise requests as a requester.

- **Decision:** BETTER. ServiceDesk Plus offers "change as technician" one way only; the
  reverse is not visible.
- **Source:** sdp-area-11 §Fields (change as technician), §Actions (row menu, requester)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Giving technician access to a requester keeps their person ID, and their old requests
     still show them as requester.
  2. Removing technician access frees a licence seat at once (REQ-ADM-009) and keeps their
     requester access.
  3. Both changes are written to the audit log with the role changes they caused.

#### REQ-ADM-004 — Sign-in access without hidden prerequisites

An admin chooses for each person whether they may sign in. A person without sign-in remains a
contact: they can be a requester on email requests and receive notifications. Turning sign-in
on needs a primary email address; if it is missing, the control explains why it is disabled.
Turning it on sends an invitation (REQ-SEC-018).

- **Decision:** BETTER. Same rule, explained.
- **Source:** sdp-area-11 §Behaviour (login cannot be ticked until an email is typed), §Weak
  spots
- **SDP weak spot fixed:** the sign-in checkbox did nothing when the email was empty, with no
  message.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. With no email, the sign-in switch is disabled and its reason reads "add an email address
     first", translated.
  2. The API refuses sign-in for a person without email with a problem code that the UI maps to
     the same message.
  3. A person without sign-in who emails the service desk becomes the requester of the new
     record.

#### REQ-ADM-005 — Custom fields on people

Admins add custom fields to people (for example cost centre, building, contract type), with
the types and rules of REQ-ADM-041. They can be shown on the technician and requester forms,
used in user group rules (REQ-ADM-033), filters, reports and catalog audiences.

- **Decision:** SAME.
- **Source:** sdp-area-11 §Fields (user group filter: user additional fields)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A custom "building" field added to people appears on the person form and in the people
     list column chooser.
  2. A user group with the rule "building is B2" contains exactly the people with that value.
  3. A field marked "requester may not see" is not returned to the portal API.

#### REQ-ADM-006 — Cost per hour behind a permission

A technician's cost per hour, in the tenant's base currency, feeds worklog costs
(REQ-INC-068). Only roles with the "view technician cost" permission can see or change it.

- **Decision:** SAME.
- **Source:** sdp-area-11 §Fields (cost per hour; can view technician's cost per hour); D-047
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A role without the permission does not receive the cost in the API, exports or reports.
  2. Changing the cost does not change the cost of worklogs already recorded.

#### REQ-ADM-007 — Where a person is used

A person's page shows everything they are linked to: sites, support groups, roles and the
grants that came with them, organisation roles, user groups, fine-grained access rules
(REQ-CMDB-029), approval stages and delegations, owned knowledge, reports, dashboards and
automations, and assets assigned to them. Each entry links to its place.

- **Decision:** SAME. ServiceDesk Plus has "view associations" and "view FGA associations".
- **Source:** sdp-area-11 §Actions (row menu: view associations, view FGA associations,
  associated org-roles)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A technician named as approver in a catalog item's approval stage shows that item under
     approvals on their page.
  2. Entries the admin may not see are counted but not named.
  3. The page updates live when the person is added to a group elsewhere.

#### REQ-ADM-008 — Bulk actions on people

Admins select many people and, in one action: mark or unmark VIP; set the site or department;
add or remove support groups, roles or user groups; set the reporting manager; send or resend
invitations; deactivate. Bulk actions run as background jobs with live progress and a result
per person (REQ-INC-120 pattern).

- **Decision:** SAME. ServiceDesk Plus has assign approval permissions, mark as VIP, assign
  project role and assign department.
- **Source:** sdp-area-11 §Actions (users list actions menu)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Setting the department on 500 selected people shows progress and ends with a count of
     successes and failures, with a reason for each failure.
  2. A bulk role change that would exceed the admin's own rights is refused for the whole
     batch before anything changes (REQ-ADM-021).
  3. Each change is in each person's history and in the audit log.

#### REQ-ADM-009 — Technician seats against the licence; requesters unlimited

Each person with technician access uses one licence seat, checked through the entitlement
interface (`check_limit`). Requesters, including requesters who sign in, never count. When no
seat is left, adding technician access is refused with a clear message and a link to the
licence page; existing technicians keep working (architecture §13.6).

- **Decision:** NEW. Licensing per technician with unlimited requesters is our packaging rule.
- **Source:** architecture §13.1, §13.5, §13.6; product-plan §9.1; sdp-area-14 §Screens (plan
  details: technicians used)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. In a tenant licensed for 10 technicians with 10 in use, giving technician access to an
     11th person is refused with the licence problem code and a translated message.
  2. Deactivating a technician frees the seat at once, and the licence page shows 9 of 10.
  3. Adding 1,000 requesters with sign-in changes no licence count.
  4. The seat check uses the entitlement interface only; a code search finds no direct licence
     reads outside the licensing module.

#### REQ-ADM-010 — Deactivate instead of delete

Admins deactivate a person who leaves. A deactivated person:

- cannot sign in, and their sessions and API keys end at once (REQ-SEC-031);
- is not offered in pickers for assignment, approval, requester or follower;
- keeps their name on past records, history and reports, marked as deactivated;
- can be reactivated, with their previous access listed for the admin to restore.

People are never hard-deleted from the admin screens. Permanent removal of personal data is
done only by the erasure job (REQ-ADM-101).

- **Decision:** BETTER. ServiceDesk Plus showed no way to deactivate or delete a user.
- **Source:** sdp-area-11 §Actions (deactivate vs delete users), §Weak spots; architecture §7.1
  (soft delete, erasure jobs)
- **SDP weak spot fixed:** there is no visible way to deactivate or delete a user.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A deactivated technician's open session is ended within 5 seconds and the next API call
     returns 401.
  2. A deactivated person does not appear in the assignee picker, but old records still show
     their name with a "deactivated" marker.
  3. Reactivating shows the roles and groups they had, and restores only those the admin
     confirms.
  4. No API removes a person's row; only the erasure job anonymises it.

#### REQ-ADM-011 — Hand over ownership when someone leaves

Deactivating a person opens a hand-over step that lists what they own or hold, with a count
per kind and a proposed new owner for each:

- open work items assigned to them (to their group's queue or a named technician);
- pending approvals and delegations (to the stage backup, REQ-SR-023);
- knowledge articles and topics (REQ-KB-033);
- reports, dashboards and schedules (REQ-RPT-049);
- automations and workflows they own (REQ-RUL-027);
- assets assigned to them (file 07);
- group lead and organisation role positions.

The admin can accept the proposals, change them, or skip the step; anything left is listed in
an admin task. Every move is recorded on the moved items.

- **Decision:** BETTER. ServiceDesk Plus has no deactivation and so no hand-over.
- **Source:** sdp-area-11 §Weak spots (no deactivate); REQ-SR-023; REQ-KB-033; REQ-RPT-049;
  REQ-ASG-010
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Deactivating a technician with 12 open incidents, 3 pending approvals and 2 scheduled
     reports shows those counts and the proposed owners before confirming.
  2. After confirming, the 12 incidents are assigned as proposed, each with a history entry
     naming the hand-over.
  3. Skipping the step creates one admin task that lists every item still owned by the
     deactivated person.

#### REQ-ADM-012 — Merge duplicate people

Admins merge two person records that are the same person, for example a requester created
twice from two email addresses. The kept record gains the other's email addresses, records,
history and memberships. The merge can be undone within 30 days.

- **Decision:** NEW. Not observed in ServiceDesk Plus.
- **Source:** architecture §6.8 (email ingestion creates requesters); REQ-INC-027
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Merging requester B into A moves B's 7 requests to A, and A can be found by B's email.
  2. A merge that would combine two technicians with different roles shows both role sets and
     asks which to keep.
  3. Undoing the merge restores B with its original records.

#### REQ-ADM-013 — Import people

Admins import people from CSV or Excel files: technicians and requesters, with site,
department, manager, groups, roles, VIP flag and custom fields. Matching on email or employee
ID updates existing people. The import uses the shared import tool (REQ-ADM-085).

- **Decision:** SAME.
- **Source:** sdp-area-11 §Screens (import wizard: users), §Automation (importing users in
  bulk is manual)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Importing 5,000 requesters creates them in the background with live progress.
  2. A row whose manager is in a later row of the same file still gets its manager.
  3. A row giving technician access beyond the licence limit is refused with a row error; the
     other rows are imported.

#### REQ-ADM-014 — People from a directory

When people come from a directory or identity provider through a sync connector (REQ-INT-063
to REQ-INT-066):

- fields that come from the directory are read-only in SupportX, with a note naming the
  source;
- a person the connector disables (REQ-INT-064) goes through the same deactivation and
  hand-over as a manual one (REQ-ADM-010, REQ-ADM-011);
- access (roles, groups, scopes) stays managed in SupportX (D-029), unless group-to-role
  mapping is set up (REQ-SEC-014).

- **Decision:** BETTER. The vendor's directory sync deletes the user by default; the sync
  disables them (REQ-INT-064) and access stays managed in the product.
- **Source:** sdp-area-13 §Advanced Portal Settings (directory sync: delete user, selected);
  sdp-area-11 §Automation (no LDAP or AD user sync found); D-029; REQ-INT-064
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A synced person's job title cannot be edited in SupportX; the field says it comes from the
     directory.
  2. A person disabled by the sync gets the hand-over task of REQ-ADM-011, the same as a manual
     deactivation.
  3. A role given in SupportX survives the next sync.

---

## 2. Roles and permissions

#### REQ-ADM-015 — Roles built from module, action and scope

Admins create roles in a role editor. A role is a list of grants. Each grant is one permission
(module and action, REQ-WI-015) at a scope (all, site, group or own), with an optional
condition (REQ-ADM-025). The editor shows permissions grouped by module, in the user's
language, with a one-line explanation each. A role can be given to people and to support
groups (every member gets it).

- **Decision:** SAME. Matches the role matrix, advanced permissions and the scope grid of
  ServiceDesk Plus on our policy layer.
- **Source:** sdp-area-11 §Fields (role permission matrix, advanced permissions, scope
  setting); architecture §11.2; ADR-022; D-025
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A role with "incident: view, scope group" lets its holders see incidents of their groups
     only, through the API, search and live updates.
  2. Giving a role to a support group gives it to every current and future member, and
     removing someone from the group removes it from them.
  3. A grant change takes effect on open screens without a new sign-in (REQ-WI-015).

#### REQ-ADM-016 — One permission catalogue from every module

Each module declares its permissions, and the role editor lists them all from one catalogue.
Each permission has a label, a description, the licence feature it needs and the scopes it
allows. The catalogue includes the permissions the module files ask for:

- work items: REQ-WI-015, field rules REQ-WI-016, problems REQ-PRB-070, changes REQ-CHG-038,
  releases REQ-REL-019 and REQ-REL-023, projects REQ-PRJ-014;
- assets and configuration: REQ-AST-058, REQ-CMDB-031, purchase REQ-PUR-020, contracts
  REQ-CON-015;
- knowledge REQ-KB-043, reports REQ-RPT-048, dashboards REQ-DSH-029, automation REQ-RUL-031;
- AI features per role and AI logs (REQ-AI-028, REQ-AI-033, REQ-ADM-029), integrations
  (REQ-INT-013), desks (REQ-ESM-011, REQ-ADM-030);
- announcements (REQ-ADM-084), and the admin permissions of this file (people, roles, groups,
  structure, customisation, settings, mail, surveys, data, privacy, security, audit).

Permissions for modules outside the tenant's edition show disabled with an upgrade hint, or
are hidden (REQ-WI-025).

- **Decision:** BETTER. One catalogue, each permission explained, instead of a matrix plus a
  collapsed list of extra checkboxes.
- **Source:** sdp-area-11 §Fields (role matrix, advanced permissions); ADR-022 (permissions
  declared by modules, validated at startup); REQ-KB-043; REQ-RPT-048; REQ-DSH-029
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A startup check fails if any permission lacks an English or Arabic label or a
     description.
  2. A permission that a module registers appears in the role editor with no change to the
     identity module.
  3. In an Essentials tenant, change permissions show disabled with an upgrade hint.

#### REQ-ADM-017 — Built-in roles can be read, compared and copied

Every built-in role opens read-only and shows exactly what it grants. Admins can copy a
built-in role to make a custom one, and compare two roles side by side. Built-in roles cannot
be changed or deleted; custom roles can.

- **Decision:** BETTER. ServiceDesk Plus built-in roles cannot be opened at all.
- **Source:** sdp-area-11 §Screens (roles list: edit and delete greyed out, names not
  clickable), §Weak spots, §Limits; REQ-WI-015; ADR-022 (immutable system roles)
- **SDP weak spot fixed:** an admin cannot see what the built-in admin or change manager roles
  grant without trial and error.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Opening the built-in technician role lists every grant with its scope.
  2. "Copy" creates an editable custom role with the same grants and a new name.
  3. Comparing two roles highlights grants that only one of them has.
  4. The API refuses edits to a built-in role with 409 and a reason code.

#### REQ-ADM-018 — Roles a new tenant starts with

A new tenant gets a set of ready roles (Appendix A), including tenant administrator, site
administrator, technician, requester, service desk manager, knowledge manager, change manager,
release manager, asset manager, CMDB manager, report viewer, auditor and approval
administrators. Role names follow one style and show in the user's language. Roles for
modules outside the tenant's edition are present but marked as needing an upgrade.

- **Decision:** SAME. ServiceDesk Plus ships 20 roles; we ship fewer, clearer ones.
- **Source:** sdp-area-11 §Fields (role names in effect); REQ-KB-043 (knowledge manager role);
  REQ-SR-023 (approval administrators); ADR-022; D-025
- **SDP weak spot fixed:** role names mix styles (technical prefixes and plain names).
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new tenant has every role in Appendix A, and each opens with its grants.
  2. Every role name shows translated in Arabic, with no internal codes.
  3. The first admin of a new tenant holds the tenant administrator role.

#### REQ-ADM-019 — Configuration rights per area

Setting up an area is a permission of its own, so an admin can be limited to one area:
service desk settings (fields, templates, statuses, SLAs, rules, closure rules), catalog,
knowledge, assets and discovery, CMDB, purchase and contracts, projects, announcements,
notifications and mail, people and access, security, data administration, and audit. Setup
shows only the areas the person may configure.

- **Decision:** SAME. ServiceDesk Plus has configuration roles per area (helpdesk, asset,
  contract, project, purchase, announcement).
- **Source:** sdp-area-11 §Fields (role names: configuration roles)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A person with "configure knowledge" only sees the knowledge pages in setup and gets 403
     on the SLA settings API.
  2. Security and audit configuration are separate permissions from people and access.

#### REQ-ADM-020 — Site administrators

A site administrator manages people, groups, departments and site settings for their sites
only, and cannot change tenant-wide settings. Their grants carry the site scope.

- **Decision:** SAME. ServiceDesk Plus has a site administrator role.
- **Source:** sdp-area-11 §Fields (enable administrator privileges for the selected sites;
  site administrator role as configured)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A site administrator for Riyadh can edit a Riyadh department and gets 404 for a Jeddah
     department.
  2. A site administrator cannot give a role with tenant-wide scope.
  3. Tenant-wide settings pages are not listed in their setup.

#### REQ-ADM-021 — No privilege escalation, no lock-out

The role screens enforce these rules on the server:

- a person can only give grants they hold themselves, unless they are a tenant administrator;
- the last active tenant administrator cannot be removed, deactivated or have the role taken
  away;
- a role in use cannot be deleted until its holders are moved to another role.

- **Decision:** NEW. Not visible in ServiceDesk Plus.
- **Source:** ADR-022 (admin protections in the service layer)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A site administrator giving a grant they do not hold gets 403 with a reason naming the
     grant.
  2. Deactivating the only tenant administrator is refused with a translated reason.
  3. Two admins removing each other's admin role at the same moment cannot leave the tenant
     with none.

#### REQ-ADM-022 — Segregation-of-duties warnings when designing roles

Admins define pairs of permissions that should not be held together, for example "submit a
change" and "approve the same change" outside the record rule, or "manage roles" and "read the
audit log". The role editor warns when a role or a person's combined roles break a rule, and a
report lists everyone who does. Record-level checks (the requester of a change cannot approve
it) stay in the policy layer (REQ-SR-027).

- **Decision:** NEW.
- **Source:** architecture §11.2 (segregation of duties: conflicts flagged at role design
  time); ADR-022 (follow-ups)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Saving a role that combines two conflicting permissions shows a warning naming the rule;
     saving needs confirmation and a reason.
  2. The conflicts report lists every person whose roles together break a rule.

#### REQ-ADM-023 — Who may approve

Being eligible as an approver is a permission per approval kind: service requests, changes,
purchase orders, knowledge articles and contracts. Approval stages that name a role or group
only reach people with the matching permission (approval engine in file 02).

- **Decision:** SAME. ServiceDesk Plus has request approver and purchase order approver flags
  on the technician.
- **Source:** sdp-area-11 §Fields (request approver, purchase order approver; allow technician
  to approve solutions), §Actions (assign approval permissions)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A person without "approve purchase orders" is not offered as a purchase order approver.
  2. Bulk "assign approval permission" on 20 people grants it to all 20 (REQ-ADM-008).

#### REQ-ADM-024 — Explain a person's access

An admin can ask two questions and get a plain answer:

- "What can this person do?": every permission with its scope, and the role or group it came
  from;
- "Why can (or can't) this person see or change this record?": the grants and rules that
  decided, including scopes, conditions, field rules and fine-grained access.

- **Decision:** NEW. ServiceDesk Plus offers no such view.
- **Source:** architecture §11.2; ADR-022; sdp-area-11 §Weak spots (roles not viewable)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. For a technician who sees an incident through a group grant, the answer names the role,
     the grant and the group.
  2. For a technician refused an incident, the answer names the missing grant or the scope
     that excludes it.
  3. The answer comes from the same policy service the API uses, and a test checks they agree.

#### REQ-ADM-025 — Conditions on grants

A grant can carry a condition in the shared filter grammar, for example "HR cases only where
the case group is HR" or "assets only in state in use and at my site". Conditions apply in
lists, records, search, live updates, reports and AI, like scopes do. Fine-grained access for
assets and CIs (REQ-CMDB-029) is built on these conditions.

- **Decision:** NEW. ServiceDesk Plus has fine-grained rules for assets and CIs only.
- **Source:** architecture §11.2 (attribute level); ADR-022 (grants with optional filter
  condition); sdp-area-11 §Screens (fine-grained access: asset and CMDB only)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A grant "service request: view, all, where group is HR" lets the holder see HR requests
     and no others, in the list, search and reports.
  2. A condition that names a field the module does not have is refused when saved.
  3. A live update about a record outside the condition is not delivered to the holder.

#### REQ-ADM-026 — Field access rules in the role editor

The role editor has a field access tab: for each module, the fields a role may not see, sees
masked, or may only read (REQ-WI-016). Admins mark custom fields as personal data or sensitive
when they create them, and choose which roles see them.

- **Decision:** NEW. ServiceDesk Plus has no field-level permission on requests.
- **Source:** architecture §11.2 (field level); REQ-WI-016
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Marking "salary band" hidden for the technician role removes it from their API responses,
     exports and search.
  2. The tab lists every field marked personal data, and which roles see it in clear.

#### REQ-ADM-027 — Time-limited role assignments

A role can be given to a person until a date, for example for a project or as cover during an
absence. It is removed automatically at the end, and the person and the admin are told a day
before.

- **Decision:** NEW.
- **Source:** architecture §11.2; product-plan §5 (security and access)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A role given until Friday is gone on Saturday at 00:00 in the tenant time zone, and the
     removal is in the audit log.
  2. A notice is sent 24 hours before the end to the person and the admin who gave it.

#### REQ-ADM-028 — Access reviews

Admins start an access review: managers or role owners confirm or remove each person's roles
and group memberships by a due date. Removals take effect on confirmation. The finished review
is kept as evidence (REQ-AUD-019).

- **Decision:** NEW. Not in ServiceDesk Plus.
- **Source:** product-plan §4.3 (pillar 5: regional compliance); architecture §11.2
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A review of the change manager role lists every holder to their managers, who can keep or
     remove each.
  2. Removing a holder in the review removes the role at once and records the reviewer.
  3. The finished review exports as a report with every decision, reviewer and time.

#### REQ-ADM-029 — AI access in the role editor

The role editor has an AI group of permissions: use the assistant, use writing help and
summaries, run each agent or agent family, use code help, manage AI settings, and read AI
logs. The AI features themselves and their defaults per role are in file 10 (REQ-AI-028,
REQ-AI-033). AI permissions follow the same scopes as the records the AI works on.

- **Decision:** NEW. ServiceDesk Plus switches AI features on for everyone.
- **Source:** REQ-AI-028; REQ-AI-033; architecture §11.2 (one policy layer for AI agents)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A role without "use writing help" sees the writing help action disabled with a reason,
     and the API refuses it with 403.
  2. Only roles with "read AI logs" can open the AI log pages; others get 404.
  3. AI permissions are listed and translated like every other permission (REQ-ADM-016).

#### REQ-ADM-030 — Roles per department desk

When the tenant has department desks (file 12), a role can be given for one desk, so a person
can be a technician in IT and a requester-only user in HR, or a desk admin (REQ-ESM-011) in
one desk only. The role editor and the person's page show roles per desk. Records stay private
to their desk unless a grant reaches them (REQ-ESM-009).

- **Decision:** BETTER. The vendor adds people to each desk instance separately, with roles
  managed per instance.
- **Source:** sdp-area-14 §Screens (ESM directory: add or remove user to an instance);
  REQ-ESM-009; REQ-ESM-011; REQ-ESM-012; architecture §7.2 (desks as partitions)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A person with the technician role in the IT desk only gets 404 on an HR case.
  2. A person's page lists their roles grouped by desk.
  3. A desk admin can give roles in their desk and gets 403 when giving roles in another.

---

## 3. Groups, user groups and organisation roles

#### REQ-ADM-031 — Support groups

A support group has a name, description, members, the sites it serves (one or many), a lead,
an optional group email and sender identity (REQ-NTF-015), and its group notifications
(REQ-NTF-026). Groups can be active or inactive. The group list shows every site a group
serves, and can be filtered by site.

- **Decision:** BETTER. ServiceDesk Plus groups belong to one site, with a small banner saying
  they also serve other sites.
- **Source:** sdp-area-11 §Screens (technician groups: active and inactive, by site), §Fields
  (technician group form), §Weak spots
- **SDP weak spot fixed:** groups are per site, which is easy to miss.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A group serving Riyadh and Jeddah appears when the list is filtered by either site.
  2. A group without members can be saved, and the assignment screen warns that it has none.
  3. Adding a member shows in their open queue views without a reload.

#### REQ-ADM-032 — Making a group inactive safely

Before a group is made inactive, the admin sees what still uses it: open work items, routing
and assignment rules, SLA escalations, catalog items, approval stages and notification rules.
The admin chooses a replacement group or confirms. An inactive group is not offered for new
assignments; its past records keep its name.

- **Decision:** BETTER. ServiceDesk Plus has active and inactive tabs with no impact check.
- **Source:** sdp-area-11 §Screens (technician groups active and inactive), §Actions
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Making a group inactive that is used by 2 routing rules lists both rules before
     confirming.
  2. With a replacement chosen, the 2 rules and the open records move to it, each with a
     history entry.

#### REQ-ADM-033 — User groups with rules and named members

A user group is defined by rules over person fields (site, department, job title, email
domain, organisation role, VIP, custom fields), by named members, or both, with exclusions.
Admins preview the members before saving, and can always see the current member list. User
groups are used for catalog audiences (REQ-CAT-015), knowledge audiences (REQ-KB-045),
announcements (REQ-ADM-077), approvals (REQ-SR-031) and reports.

- **Decision:** BETTER. ServiceDesk Plus user groups are filters only, with no member list.
- **Source:** sdp-area-11 §Screens (user groups: a saved filter), §Fields (user group form),
  §Weak spots
- **SDP weak spot fixed:** there is no user-group member list, only a dynamic filter.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A group "department is Finance, plus Sara, minus Omar" lists Finance people with Sara
     added and Omar left out.
  2. A person moving into Finance joins the group at once, and gains access to Finance-only
     catalog items without signing in again.
  3. The preview count matches the saved member count.

#### REQ-ADM-034 — Organisation roles

Admins keep a tree of organisation roles by level: organisation (for example chief executive
or chief information officer), region, site, department, support group, and the person's
manager. Each role names who holds it for each place, for example "department head of
Finance: Aisha". Some roles allow only one holder. Approvals (REQ-SR-031) and escalations
(REQ-SLA-023) use these roles relative to a record.

- **Decision:** SAME.
- **Source:** sdp-area-11 §Screens (organisation roles), §Fields (organisation roles tree),
  §Automation (organisation roles feed approvals and escalations)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Setting a second holder on a single-holder role is refused with a message.
  2. A department head change is used by the next approval that asks for "department head of
     the requester".
  3. A role with no holder is flagged on the tree, and approvals that need it follow
     REQ-SR-023.

#### REQ-ADM-035 — Reporting lines

Each person can have a reporting manager. The product refuses loops (A manages B manages A).
Managers can see their direct reports' requests if the tenant allows (REQ-PRT-031), and an
admin can override that per person.

- **Decision:** SAME.
- **Source:** sdp-area-11 §Fields (reporting manager; view requests of direct reportees; view
  permissions own, own site, all)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Setting a manager that would create a loop is refused and names the loop.
  2. With direct-report visibility on, a manager sees the requests of their 4 reports in the
     portal and no others.
  3. A per-person override "all requests of my site" applies only to that person.

---

## 4. Organisation structure

#### REQ-ADM-036 — Regions

Admins group sites into regions with a name, description and organisation roles (regional
manager). Regions can be used in scopes, audiences, rules and reports.

- **Decision:** SAME.
- **Source:** sdp-area-11 §Screens (regions), §Fields (region form)
- **SDP weak spot fixed:** none of the sample sites were linked to the one region, and nothing
  warned about it.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A report grouped by region totals the records of its sites.
  2. The region list shows how many sites each region has, and flags sites with no region when
     regions are in use.

#### REQ-ADM-037 — Sites

A site has a name, description, region, time zone, default language, address, contact
details, and its operating-hours and holiday calendars (REQ-SLA-010, REQ-SLA-012). Records
and people take their time zone and calendar from their site (REQ-SLA-013). A new tenant has
one default site.

- **Decision:** SAME.
- **Source:** sdp-area-11 §Screens (sites), §Fields (site form)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A requester at a site with Arabic as default language who has no language set gets
     Arabic.
  2. Changing a site's calendar changes due-date calculation for new records at that site
     (REQ-INC-016).
  3. A site cannot be deleted while people or records use it; it can be made inactive.

#### REQ-ADM-038 — Site settings: inherit, copy or own

For departments, support groups, business rules and SLAs, each site either uses the default
site's settings, takes a one-time copy, or has its own. The site page shows which choice
applies for each and where an inherited setting comes from.

- **Decision:** SAME.
- **Source:** sdp-area-11 §Fields (site form: related settings; copy, refer or custom);
  REQ-SLA-007
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A site that refers to the default SLAs picks up a change to them at once.
  2. A site with a copy keeps its own SLAs when the default ones change.
  3. The site page shows "inherited from default site" next to each inherited setting.

#### REQ-ADM-039 — Departments

A department has a name, site, head, description, optional parent department and
organisation roles. Departments can be listed by site. A department head is used in approvals
and escalations (REQ-ADM-034).

- **Decision:** BETTER. Adds parent departments for larger organisations.
- **Source:** sdp-area-11 §Screens (departments by site), §Fields (department form)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A department list filtered by site shows only that site's departments.
  2. A report grouped by top-level department includes its child departments.
  3. A department cannot be its own ancestor; the save is refused with a message.

#### REQ-ADM-040 — Calendars and absence types linked to sites and groups

Operating hours, exception hours, holidays and absence types are defined in the SLA and
assignment set-up (REQ-SLA-010 to REQ-SLA-013, REQ-ASG-008). In administration they are
linked: each site and support group names its calendar, and setup shows which sites and
groups use each calendar.

- **Decision:** SAME.
- **Source:** sdp-area-11 §Navigation path (operational hours, holiday groups, unavailability
  types)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A calendar's page lists the sites and groups that use it.
  2. Deleting a calendar in use is refused, naming its users.

---

## 5. Customisation

#### REQ-ADM-041 — Custom fields for every module from one place

Admins add custom fields to any module (work item types, knowledge, assets, CIs, purchase,
contracts, vendors, projects, people) from one screen with a module filter and a type filter.
Types: text, long text, number, decimal, currency amount, date, date and time, yes or no,
single choice, multiple choice, person, link to a record, web address and email. Each field
has labels per language, help text, a default, validation (required, range, length,
pattern), and a stable key that admins see only in the API view. Values are stored in typed
JSON with indexes (architecture §6.6). Work item fields follow REQ-INC-014.

- **Decision:** BETTER. Same breadth, more types, and labels per language.
- **Source:** sdp-area-13 §Additional Fields; architecture §6.6
- **SDP weak spot fixed:** field keys such as `txt_<name>` are shown in the list as a column.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A "contract type" choice field added to assets appears on the asset form and in asset
     list filters without a deploy.
  2. A field without an Arabic label falls back to English and is listed in the translation
     coverage report (REQ-ADM-053).
  3. Filtering 1 million records on a custom choice field stays within the list target
     (REQ-WI-024).

#### REQ-ADM-042 — Safe changes to fields in use

A field's page shows where it is used: forms, templates, rules, SLAs, workflows, reports,
views and integrations. Deleting a field in use is blocked until the uses are removed; the
admin can retire it instead (hidden from forms, data kept). Changing a field's type after it
holds data is limited to safe conversions.

- **Decision:** NEW. Not observed in ServiceDesk Plus.
- **Source:** architecture §6.6 (versioned metadata); REQ-WI-009 (reject configuration that can
  never work when saved)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Deleting a field used by a business rule is refused and names the rule.
  2. A retired field no longer shows on forms, and old records still show its value in
     history.
  3. Changing a text field with data to a number is refused; changing a number to text is
     allowed.

#### REQ-ADM-043 — Pick lists with translations, order and colour

Every pick list is managed the same way: values with a label per language, order, optional
colour and icon, default value, and retire instead of delete. This covers the work item lists
(category tree, level, channel, impact, urgency, priority, type, task type, worklog type,
closure code, downtime type) and every module's own lists. Category trees have a tree view
with move and merge. A value in use cannot be deleted, only retired.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Helpdesk customization; REQ-INC-006; REQ-INC-008 (clean impact and
  urgency scales)
- **SDP weak spot fixed:** the impact list mixed scope values and severity values; we ship
  clean scales (REQ-INC-008).
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Reordering priorities changes the order in every picker and filter at once.
  2. Retiring a category hides it from new records; records that use it keep it.
  3. Merging two subcategories moves their records to the kept one, each with a history entry.

#### REQ-ADM-044 — One customisation home per module

Each module has one customisation page that links everything that shapes it: fields, pick
lists, templates, form layouts (REQ-INC-036), form rules (REQ-INC-037), statuses
(REQ-INC-044), life cycles (REQ-INC-049, REQ-WF-001), closure rules (REQ-INC-094), numbering
(REQ-ADM-045) and notifications. Each setting lives in one place only.

- **Decision:** BETTER. ServiceDesk Plus spreads one module's settings across several setup
  groups and repeats some.
- **Source:** sdp-area-13 §Navigation path, §Weak spots (same settings area in two places;
  advanced portal settings holds unrelated items)
- **SDP weak spot fixed:** reopen rules, closing rules and archive rules sit on three different
  pages, and one settings page mixes unrelated items.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. The incident customisation page links every incident setting listed above.
  2. A test of the setup map finds no setting reachable from two different pages with two
     different editors.

#### REQ-ADM-045 — Numbering for every record type on one page

One page shows the display-ID prefix and next number for every record type (REQ-WI-002):
incidents, service requests, problems, changes, releases, projects, tasks, scheduled
maintenance and others. Admins change prefixes there. Numbers start at 1 in a new tenant.

- **Decision:** BETTER. ServiceDesk Plus keeps ID settings in four places, with blank request
  prefixes and maintenance numbers starting at 3.
- **Source:** sdp-area-13 §Advanced Portal Settings (request ID, change, project and release
  settings), §Announcement and Maintenance (maintenance prefixes), §Weak spots; D-045
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The page lists every record type with its prefix and next number.
  2. Changing the change prefix to "RFC" makes the next change RFC-n; old IDs still open.
  3. Setting a next number lower than one already used is refused.

#### REQ-ADM-046 — Reusable sub-forms

Admins define reusable sub-form types (a named set of fields shown as repeating rows), for
example "equipment line" with item, quantity and cost. They can be added to templates and
catalog forms (REQ-CAT-010).

- **Decision:** SAME.
- **Source:** sdp-area-13 §Announcement and Maintenance (subform types)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A sub-form type used in two catalog items shows the same fields in both.
  2. Adding a field to the sub-form type adds it to both forms, after a preview of affected
     forms.

#### REQ-ADM-047 — Custom modules

Admins create their own record types (for example "visitor pass" or "key loan") with fields,
forms, list views, statuses, permissions, numbering, history, notifications, API and reports,
using the same metadata engine.

- **Decision:** SAME.
- **Source:** sdp-area-14 §Screens (developer space: custom modules); sdp-area-11 §Screens
  (import wizard: custom modules); architecture §2.15 (custom modules)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A new "visitor pass" module gets a list, a form, permissions in the role editor and an API
     with no code change.
  2. Its records have field history and live updates like any other record.
  3. A custom module can be exported and imported with the configuration (REQ-ADM-098).

#### REQ-ADM-048 — Customisation versions, preview and history

Changes to fields, pick lists, forms and templates are kept as versions: who changed what,
when, and a readable difference. Admins preview a form change before publishing it, and can
restore an earlier version. Every change is in the audit log (same model as REQ-RUL-026).

- **Decision:** BETTER. ServiceDesk Plus logs that something changed, not what.
- **Source:** sdp-area-14 §Screens (audit log entries); architecture §6.6 (versioned metadata),
  §7.4
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Renaming a field label shows the old and new label in the change history.
  2. Restoring a form layout's previous version brings it back and records the restore.
  3. A preview of an unpublished form shows the change to the admin only.

---

## 6. Instance settings, languages and branding

#### REQ-ADM-049 — Instance settings

One page holds the tenant's basic settings: name, address (subdomain), default time zone,
first day of the week, default language, default date and time formats, country, fiscal year
start and the main contact. People and sites inherit these unless they set their own.

- **Decision:** BETTER. Default language and date formats are tenant settings too, not only
  personal ones.
- **Source:** sdp-area-11 §Fields (instance settings); sdp-area-14 §Screens (instance
  settings), §Weak spots
- **SDP weak spot fixed:** language and date format can only be set per user, so a tenant
  cannot set a default.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Changing the default time zone changes it for people who have not set their own, live.
  2. A new person with no language gets the tenant default language.
  3. Changing the first day of the week changes calendars and week-based reports.

#### REQ-ADM-050 — Base currency

The tenant has one base currency, chosen at set-up, used for costs, prices and reports.
Changing it later shows the effect and needs confirmation; stored amounts keep their
currency.

- **Decision:** SAME.
- **Source:** sdp-area-11 §Fields (instance settings: currency); sdp-area-14 §Screens
  (currency page: one base currency)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new tenant created with Saudi riyal shows costs in SAR everywhere.
  2. Changing the base currency asks for confirmation and is in the audit log.

#### REQ-ADM-051 — More currencies and exchange rates

Admins add currencies and exchange rates against the base currency, with the date each rate
applies from. Amounts in other currencies are converted at the rate of their date
(REQ-PUR-019). Rate history is kept.

- **Decision:** SAME.
- **Source:** sdp-area-14 §Screens (new currency, configure exchange rate); architecture §2.15
  (multi-currency)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A rate entered for 1 March applies to amounts dated on or after 1 March.
  2. A past amount keeps its converted value after a new rate is entered.

#### REQ-ADM-052 — Languages offered in the tenant

Admins choose which languages people can pick and which is the default. English and Arabic
are available from MVP and Urdu from V1 (D-006, D-048), with right-to-left layout. More
languages come as translations are added (architecture §2.15 asks for 40 or more). No
language costs extra.

- **Decision:** BETTER. ServiceDesk Plus charges more for several languages on-prem.
- **Source:** architecture §2.15 (multi-language), §9.5; product-plan §9.1 (no language
  surcharge); D-006; sdp-area-14 §Screens (preferences: 37 languages)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. With Arabic switched off for the tenant, people cannot pick it, and those who had it fall
     back to the default.
  2. The language list offers only languages with complete product labels.

#### REQ-ADM-053 — Translations of admin-created values

One screen lists every admin-created text (field labels, pick list values, statuses,
templates, catalog items, survey questions, announcement types) with its translation per
enabled language. It shows coverage per language, filters to missing ones, and exports and
imports translation files for translators. Missing translations fall back to the default
language and are counted.

- **Decision:** BETTER. ServiceDesk Plus translates survey questions only on their own tab.
- **Source:** architecture §9.5 (admin-created values carry their own translations);
  sdp-area-13 §Surveys (survey translation tab)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. The coverage view shows Arabic at 92 % when 8 of 100 values lack Arabic, and lists them.
  2. Exporting translations and importing the file back with the 8 filled in brings coverage
     to 100 %.
  3. An import with an unknown key reports it and changes nothing else.

#### REQ-ADM-054 — Terminology per tenant

Admins can rename a small set of product words for their tenant, per language, for example
"incident" to "ticket" or "technician" to "agent". The new words show everywhere the label is
used, including emails and the portal.

- **Decision:** NEW. Not in ServiceDesk Plus.
- **Source:** architecture §9.5 (labels package)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Renaming "incident" to "ticket" in English changes the menu, list title, forms and
     notification subjects.
  2. Codes, API names and reports' stored definitions do not change.
  3. Reset restores the product word.

#### REQ-ADM-055 — Branding for the console, sign-in and email

A branding screen sets the tenant's logo, favicon, brand colours and product name for light,
dark and high-contrast themes. They apply to the console, the portal (REQ-PRT-016), the
sign-in page (REQ-SEC-003) and emails (REQ-NTF-015). The admin previews before saving, and
colours that fail WCAG AA contrast are refused. Assets are stored through the S3 API.

- **Decision:** SAME. ServiceDesk Plus has theme settings with fixed colour swatches.
- **Source:** D-027; sdp-area-13 §Theme Settings; architecture §9.4 (brand colours via tokens)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Uploading a logo changes the console header for signed-in people without a reload.
  2. A brand colour with contrast below AA is refused with a translated message.
  3. Two tenants on two addresses each see their own brand on every surface.

#### REQ-ADM-056 — How far people may personalise

Admins decide whether people may change their theme (light, dark, system), accent colour and
text size, or must use the tenant's brand. Accessibility preferences (REQ-ADM-063) are always
allowed.

- **Decision:** SAME. ServiceDesk Plus has "allow other users to personalise their theme and
  font".
- **Source:** sdp-area-13 §Theme Settings
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With personalisation off, the theme choices in preferences are disabled with a reason.
  2. With personalisation off, a person can still switch on high contrast and reduced motion.

#### REQ-ADM-057 — Default navigation for technicians

Admins set the default order of modules in the technician navigation, hide modules the
tenant does not use, and reset to the product default. Home stays first. People can change
their own order (REQ-ADM-061). Only modules the person may use and the tenant is licensed for
are shown, the same in every layout (D-031). The requester portal menu is set in
REQ-PRT-019.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Navigation & Footer Settings; sdp-area-01 §Weak spots
  (discoverability of modules); D-031
- **SDP weak spot fixed:** on a laptop-sized window half the modules hid behind a "more" item
  that did not open reliably, and setup and the catalog were not in the main navigation.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Moving "changes" before "incidents" in the default order changes it for people who have
     not set their own order.
  2. A hidden module is absent from navigation and the command palette for everyone.
  3. At 1280 pixels wide, every visible module is reachable in at most two clicks, and the
     overflow menu opens on the first click.

---

## 7. Personal preferences

#### REQ-ADM-058 — One preferences page that follows the person

Each person has one preferences page with sections for language and region, appearance and
navigation, accessibility, notifications (REQ-NTF-016), editor and signature, and their home
dashboard (REQ-DSH-002). Preferences are stored on the server, so they follow the person to
every device and the mobile app, and apply at once on every open tab.

- **Decision:** BETTER. ServiceDesk Plus repeats preferences, accessibility and navigation in
  two places with overlapping links.
- **Source:** sdp-area-01 §Screens (profile drawer, preferences dialog), §Weak spots (two sets
  of preferences); D-031
- **SDP weak spot fixed:** "personalise" and "preferences" overlap, and accessibility appears in
  two places.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Every personal setting is reachable from one page; a test finds no second editor for any
     of them.
  2. Changing the theme in one browser changes it in another open browser of the same person
     within 2 seconds.
  3. Signing in on a new device shows the person's saved language and layout at once.

#### REQ-ADM-059 — Language, time zone and formats per person

A person sets their language, time zone, date format, time format (12 or 24 hours), number
format and first day of the week. Each defaults from their site, then the tenant. Every date
and time on screen uses these through the one formatter (REQ-WI-014).

- **Decision:** SAME.
- **Source:** sdp-area-01 §Screens (preferences: language, country, date format, time format,
  time zone); sdp-area-14 §Screens (preferences: 37 languages, 11 date formats, 9 time
  formats)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Choosing Arabic switches every screen to Arabic, right to left, without signing out.
  2. Choosing a 24-hour format changes times in lists, records and history.
  3. A person with no time zone set sees their site's time zone.

#### REQ-ADM-060 — Navigation layout

A person chooses the navigation layout: top bar (default), side bar, or compact side bar with
icons only. The choice is stored on the server and follows them. Menus are the same in all
three.

- **Decision:** SAME.
- **Source:** D-031; sdp-area-01 §Fields (navigation menu); sdp-area-13 §Theme Settings
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Switching to the compact side bar shows icons with labels on hover and focus, in both text
     directions.
  2. The same modules, in the same order, appear in all three layouts.

#### REQ-ADM-061 — Personal module order

A person can reorder and hide modules in their own navigation, and reset to the tenant
default. Home stays first.

- **Decision:** SAME.
- **Source:** sdp-area-01 §Screens (organise navigation tabs)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Reordering by drag or by keyboard saves the order and shows it on every device.
  2. Reset returns to the tenant default order (REQ-ADM-057).

#### REQ-ADM-062 — Theme and text size

A person chooses light, dark, follow the system, or high contrast, and a text size from 90 %
to 150 %. Layouts stay usable at every size.

- **Decision:** BETTER. Adds a high-contrast theme (architecture §9.4).
- **Source:** sdp-area-01 §Fields (display mode, font size); architecture §9.4 (light, dark and
  high-contrast themes)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The high-contrast theme passes the automated contrast check on the incident list and
     record.
  2. At 150 % text size the record page has no overlapping or cut-off text.

#### REQ-ADM-063 — Accessibility preferences

Besides the built-in standard (REQ-WI-023), a person can switch on: reduced motion, underlined
links, a stronger focus outline, longer or paused toast messages, highlighted key information
(IDs and contacts), and keyboard shortcuts on or off (REQ-WI-022).

- **Decision:** SAME.
- **Source:** sdp-area-01 §Screens (accessibility controls: vision, mobility, learning);
  sdp-area-14 §Screens (accessibility controls)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With longer messages on, a toast stays until it is dismissed.
  2. With shortcuts off, typing letters in the record page triggers no action.
  3. With reduced motion on, no animation plays.

#### REQ-ADM-064 — Accessibility switches left to the operating system

We do not build a reading mask, custom cursor, custom scrollbar, screen reader switch, page
navigator, hover highlight or click-to-drag mode inside the product. Operating systems and
browsers provide these and assistive technology expects standard controls. Instead, every
screen works with screen readers and the keyboard (REQ-WI-023), and every drag action has a
keyboard alternative.

- **Decision:** SKIP. These duplicate the operating system and can conflict with assistive
  technology. Replaced by built-in WCAG 2.2 AA (REQ-WI-023).
- **Source:** sdp-area-01 §Screens (accessibility controls: hearing, mobility); architecture
  §9.4
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. Every drag-and-drop action (columns, navigation order, dashboard widgets) has a keyboard
     alternative, tested in e2e.
  2. The screen reader test suite passes on the incident list, record and create form.

#### REQ-ADM-065 — Email signature and editor defaults

A person sets a rich-text email signature, added to their replies (REQ-INC-058), and default
editor font size. The tenant can set a signature template with fields (name, job title,
group) that people complete.

- **Decision:** SAME.
- **Source:** sdp-area-01 §Screens (personalise: rich-text editor style, email signature)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A reply from a technician ends with their signature in the sent email.
  2. A signature with a script tag is stored without it (REQ-INC-064).

---

## 8. Mail

#### REQ-ADM-066 — One mail page in setup

All mail settings are reached from one page in setup, which shows each item's state and links
to where it is set:

- mailbox connections, routing, fetch interval and outgoing mail per mailbox (REQ-INT-050 to
  REQ-INT-053), and the sending domain on SaaS (REQ-INT-054);
- mail from unknown senders (REQ-INC-027), blocked senders and filters (REQ-INC-026), and
  field commands in the email (REQ-INC-025);
- notification, survey, invitation and password-reset templates (REQ-ADM-068).

Until outgoing mail is set, work goes on and messages wait visibly (REQ-INC-060); the page
shows the number of waiting messages.

- **Decision:** SAME. ServiceDesk Plus has mail server settings, mail filter and email command
  pages under one setup group.
- **Source:** sdp-area-13 §Mail (mail server settings, mail filter, email command), §Navigation
  path; sdp-area-11 §Config (mail server settings not configured)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The page lists each mailbox with its state (working, failing, not set up) and a link to it.
  2. With no outgoing mail set, the page shows a banner and the count of waiting messages,
     updated live.
  3. Searching setup for "SMTP", "mailbox" or "email" leads to this page (REQ-ADM-107).

#### REQ-ADM-067 — Fetched mail is kept, not deleted

After fetching over IMAP, Microsoft Graph or the Gmail API (REQ-INT-050), the product marks
messages as read or moves them to a chosen folder. It never deletes them unless the admin
chooses that. A message is fetched once only, even after a restart.

- **Decision:** BETTER. ServiceDesk Plus deletes every message on the polled mailbox after
  fetching, so a dedicated mailbox is required.
- **Source:** sdp-area-13 §Mail (the polled mailbox is emptied after fetching); REQ-INT-055
- **SDP weak spot fixed:** all messages on the polled mailbox are deleted after fetching.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. After fetching, the message is in the chosen folder on the mail server.
  2. Restarting the poller during a fetch creates no duplicate record.

#### REQ-ADM-068 — Mail and notification templates in setup

Notification rules and templates for every module are edited in one place in setup, through
the template editor of the notification engine (REQ-NTF-011 to REQ-NTF-014). Setup also lists
the survey, invitation and password-reset emails there.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Surveys (customise template), §Mail; REQ-NTF-011
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. The invitation email template is listed with the notification templates and can be
     edited and previewed in English and Arabic.
  2. A template change is versioned and can be reset (REQ-NTF-013).

---

## 9. Surveys

#### REQ-ADM-069 — Surveys per work item type

Admins switch satisfaction surveys on or off, and choose which work item types send one:
incidents, service requests and, if wanted, other types. Each type can use its own survey.
Surveys are off in a new tenant.

- **Decision:** BETTER. ServiceDesk Plus has one survey for requests only.
- **Source:** sdp-area-13 §Surveys (enable user survey); REQ-INC-103
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With surveys on for service requests only, closing an incident sends none.
  2. Two types can use two different surveys.

#### REQ-ADM-070 — Survey questions and rating scale

A survey has an overall rating on an ordered scale with labels (for example poor, good,
excellent), and questions of these kinds: rating, single choice, multiple choice, yes or no,
and free text. Questions can be required, reordered and shown only when an earlier answer
matches. The scale runs from worst to best in the same direction everywhere.

- **Decision:** BETTER. ServiceDesk Plus questions are free text only.
- **Source:** sdp-area-13 §Surveys (define survey: questions, satisfaction levels)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A follow-up question "what went wrong?" shows only after a poor rating.
  2. Submitting without a required answer is refused in the browser and by the API.
  3. Adding a level to the scale keeps past answers mapped to their original level.

#### REQ-ADM-071 — Survey translations

Every survey text (questions, choices, levels, messages) has a translation per enabled
language (REQ-ADM-053). The requester answers in their own language.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Surveys (survey translation tab)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An Arabic requester gets the survey in Arabic, right to left.
  2. A missing translation falls back to the tenant default language.

#### REQ-ADM-072 — Survey messages and email

Admins edit the survey's welcome, thank-you, already-answered and expired messages, and the
survey email template (REQ-ADM-068), which carries the one-click rating (REQ-INC-103).

- **Decision:** SAME.
- **Source:** sdp-area-13 §Surveys (messages: welcome, success, failure, thanks; customise
  template)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Answering an expired survey shows the expired message.
  2. Opening an answered survey again shows the already-answered message.

#### REQ-ADM-073 — When surveys are sent

Admins choose when a survey is sent:

- every time a record closes, or every Nth closed record, or every Nth closed record of the
  same requester;
- only for records matching conditions (type, template, category, group, site);
- no more than one survey per requester in a chosen number of days;
- the survey expires after a chosen number of days.

- **Decision:** BETTER. Adds conditions, a per-requester limit and expiry.
- **Source:** sdp-area-13 §Surveys (survey scheduling: three options)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With "every 3rd closed record", the 3rd, 6th and 9th closures send a survey.
  2. With a 30-day per-requester limit, a requester whose record closed twice this week gets
     one survey.
  3. A survey older than its expiry cannot be answered.

#### REQ-ADM-074 — Preview and test a survey

Admins preview a survey as a requester in each language and send a test to themselves.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Surveys (survey preview)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. The preview shows all questions, including conditional ones, in the chosen language.
  2. Answers to a test survey are marked as tests and do not count in results.

#### REQ-ADM-075 — Survey results

Results are listed per answered survey: record, requester, technician, group, overall
rating, score and answers, with filters and export. Each record shows its survey answer.
Results feed reports (REQ-RPT-018) and the low-rating follow-up (REQ-INC-103).

- **Decision:** SAME.
- **Source:** sdp-area-13 §Surveys (survey results)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new answer appears in the results list without a reload.
  2. The incident record shows the survey rating and answers on its page.
  3. The results export matches the list filters.

#### REQ-ADM-076 — Surveys without email

Surveys are also offered in the portal (REQ-PRT-012) and in the mobile app, so they work when
outgoing mail is not set or the requester does not read email.

- **Decision:** BETTER. ServiceDesk Plus surveys go only by email.
- **Source:** sdp-area-13 §Surveys (blocked without mail)
- **SDP weak spot fixed:** with mail not configured, no survey can be sent or answered.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With no outgoing mail, closing a record still lists its survey in the requester's portal.
  2. A survey answered in the portal cannot be answered again from the email.

---

## 10. Announcements

#### REQ-ADM-077 — Announcements

People with permission write announcements in the `announcements` module (ADR-024): a title,
a plain-text body (D-033), a type, an audience and an optional banner. Audiences are
everyone, requesters, technicians, chosen sites, support groups or user groups. Announcements
show in the console, the portal (REQ-PRT-009) and, if public, without sign-in (REQ-PRT-026).
Incidents can create them (REQ-INC-129).

- **Decision:** SAME.
- **Source:** ADR-024; D-032; sdp-area-01 §Screens (announcements tab); sdp-area-11 §Fields
  (announcement row in the role matrix)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An announcement for the Riyadh site shows to Riyadh people and to no one else.
  2. A banner announcement shows at the top of the console and the portal for its audience.
  3. A requester asking for a draft announcement by ID gets 404.

#### REQ-ADM-078 — Publish window and status flow, live everywhere

An announcement moves through draft, published and archived; unpublish and archive take an
optional reason, kept in history. A published announcement can have a start and end time. It
is scheduled, live or ended according to the clock at the moment it is read, and every screen
changes at the window's start and end with no reload.

- **Decision:** BETTER. Visibility is computed, so nothing is late or missed.
- **Source:** ADR-024 (status machine, computed visibility, live screens on the clock); D-032;
  sdp-area-01 §Screens (announcements: start and end dates)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An announcement with a window starting at 10:00 appears on open screens at 10:00 within 2
     seconds, without a reload.
  2. Archiving with a reason records the reason in history.
  3. The actions offered keep a fixed order and show a reason when disabled (REQ-WI-010).

#### REQ-ADM-079 — Second-person publishing

A tenant setting, off by default, requires a second person to publish: the author cannot
publish their own announcement.

- **Decision:** NEW.
- **Source:** D-032; ADR-024 (four-eyes as a segregation-of-duties rule)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. With the setting on, the author sees publish disabled with the reason "another person must
     publish", and the API refuses it.
  2. Another person with the publish permission can publish it.
  3. Changing the setting is in the setting's history and the audit log.

#### REQ-ADM-080 — Announcement types and templates

Admins keep a list of announcement types (for example service down, service restored, new
service, policy, maintenance) with labels per language, colour and icon, and announcement
templates with prefilled text and audience.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Announcement and Maintenance (announcement types),
  §Navigation path (announcement template)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Choosing the "service down" template fills the type, body and banner choice.
  2. A retired type is not offered for new announcements and still shows on old ones.

#### REQ-ADM-081 — Tell the audience

When publishing, the author can also send the announcement by email or in-app notification
to its audience, at publish time or at the window start.

- **Decision:** SAME.
- **Source:** sdp-area-01 §Screens (announcements: followers); architecture §2.1
  (announcements)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Publishing with "email the audience" sends one email per person in the audience, in their
     language.
  2. Notifications go through the notification engine and appear in its delivery log
     (REQ-NTF-028).

#### REQ-ADM-082 — Views and acknowledgements

Each announcement shows how many people saw it. An announcement can require acknowledgement
("I have read this"); then it stays shown until the person confirms, and the author sees who
has and has not.

- **Decision:** BETTER. ServiceDesk Plus counts views and followers; acknowledgement is new.
- **Source:** sdp-area-01 §Screens (announcements: views, followers)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. The view count rises when a new person opens the announcement, live for the author.
  2. A policy announcement that requires acknowledgement keeps its banner until the person
     confirms.
  3. The author can export the list of people who have not confirmed.

#### REQ-ADM-083 — Announcements in several languages

An announcement can have its title and body in each enabled language. People see their
language, else the default.

- **Decision:** NEW.
- **Source:** architecture §9.5; D-006
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An announcement with English and Arabic text shows Arabic to Arabic users, right to left.
  2. Without an Arabic version, Arabic users see the English text.

#### REQ-ADM-084 — Announcement permissions

Announcements have three permissions: view, manage (scopes all, site, group, own) and publish
(all). Technicians view all and manage their own by default; publishing and the
second-person setting stay with administrators and custom roles.

- **Decision:** SAME. ServiceDesk Plus has an announcement row in the role matrix.
- **Source:** ADR-024 (permissions and built-in role defaults); sdp-area-11 §Fields
  (announcement: view ticked and locked)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A technician can edit their own draft and gets 404 for another group's draft.
  2. A technician without publish sees publish disabled with a reason.

---

## 11. Data administration

#### REQ-ADM-085 — Import data into every module

One import tool loads data into every module from CSV or Excel (XLSX, and XLS for older
files):

- people, regions, sites, departments, support groups, categories and pick lists;
- incidents and service requests with tasks, notes, conversations, worklogs and attachments;
- problems (REQ-PRB-081), changes (REQ-CHG-118), releases (REQ-REL-010), projects with
  members, milestones, tasks and comments (REQ-PRJ-008);
- CIs and relationships (REQ-CMDB-018), assets and consumables (REQ-AST-053), software
  licences, contracts, vendors, products and purchase orders;
- knowledge articles (REQ-KB-088), catalog items (REQ-CAT-031), cost centres and GL codes
  (REQ-PUR-017), and custom modules.

- **Decision:** SAME. ServiceDesk Plus imports 46 modules through one wizard.
- **Source:** sdp-area-11 §Fields (import wizard: modules); sdp-area-14 §Screens (import
  data); architecture §6.8 (imports and exports)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Each listed module can be chosen in the tool, and a sample file for it imports without
     errors.
  2. Modules outside the tenant's edition show disabled with an upgrade hint.
  3. Imports go through the same service layer as the API: permissions, validation and rules
     apply.

#### REQ-ADM-086 — Map, check and try before importing

The tool maps file columns to fields, remembering the last mapping per module. It maps file
values to pick list values (for example "Hi" to high priority) and people by email or
employee ID. A dry run checks every row and lists errors and warnings before anything is
written.

- **Decision:** BETTER. Adds value mapping and a dry run.
- **Source:** sdp-area-11 §Fields (import wizard: next leads to field mapping); sdp-area-14
  §Screens (import data)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A dry run on a file with 3 bad dates lists those 3 rows with the column and reason, and
     writes nothing.
  2. A value with no matching pick list entry can be mapped by hand before the run.
  3. The next import of the same module offers the saved mapping.

#### REQ-ADM-087 — Duplicate handling

The admin chooses how rows that match an existing record are handled: add new only (skip
matches), add new and update matches, or update matches only. The match key is chosen per
import (display ID, email, employee ID, serial number or a custom field). Deleting existing
records before importing is not offered; an import can be undone instead (REQ-ADM-089).

- **Decision:** BETTER. Same modes without "delete existing and add", which can destroy data.
- **Source:** sdp-area-11 §Fields (import wizard: modes); sdp-area-14 §Screens (four duplicate
  modes)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. "Update matches only" with 10 matching rows and 5 new rows updates 10 and reports 5 as
     skipped.
  2. Two rows in one file matching the same record are reported, and only the first is used.
  3. No import mode removes records that are not in the file.

#### REQ-ADM-088 — Large imports in the background, no record cap

Imports run as background jobs with no record limit, streamed progress, and a downloadable
row-by-row report of results and errors. The admin can leave the page and is notified at the
end. Files may use UTF-8, UTF-16, the ISO-8859 family or Windows-1256 (Arabic).

- **Decision:** BETTER. ServiceDesk Plus caps each import at 3,000 records.
- **Source:** sdp-area-11 §Fields (import wizard: limit, encodings); sdp-area-14 §Screens
  (3,000-record limit); architecture §6.8
- **SDP weak spot fixed:** imports are capped at 3,000 records.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Importing 200,000 incidents completes with live progress and a report.
  2. A Windows-1256 file with Arabic names imports with correct Arabic text.
  3. A failed row does not stop the job; the report lists it with its reason.

#### REQ-ADM-089 — Import history and undo

Each import is kept in a history with who ran it, the file, the mode, counts and the report.
An import can be undone within 30 days: records it created are removed (to trash) and fields
it updated go back to their earlier values, unless changed since.

- **Decision:** BETTER. ServiceDesk Plus has an import history but no undo.
- **Source:** sdp-area-11 §Fields (import wizard: import history tab); sdp-area-14 §Screens
  (history tab)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Undoing an import of 1,000 new people moves them to trash and the history shows it.
  2. A field changed by a person after the import is not reverted, and the undo report lists
     it.
  3. Running and undoing imports are in the audit log.

#### REQ-ADM-090 — Microsoft Project plans

The import tool reads project plans saved from Microsoft Project in its XML format: tasks,
hierarchy, dates, effort, resources by email, and dependencies (REQ-PRJ-008).

- **Decision:** SAME.
- **Source:** architecture §2.15 (MS Project import); sdp-area-06 §Actions (import projects)
- **Priority:** LATER · **Edition:** Professional
- **Acceptance criteria:**
  1. A plan with 200 tasks and 150 dependencies imports with the same hierarchy and links.
  2. A resource whose email is unknown is reported, and the task is left unassigned.

#### REQ-ADM-091 — Import templates per module

For each module the tool offers a template file with the current fields (including custom
fields), column headings in the admin's language, and example rows.

- **Decision:** SAME.
- **Source:** sdp-area-11 §Fields (sample CSV per module); sdp-area-14 §Screens (sample csv)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A template downloaded after adding a custom field contains that field's column.
  2. A template downloaded in Arabic imports without remapping.

#### REQ-ADM-092 — Imported records keep their past

Imported work items keep their original created, resolved and closed dates, their original
ID from the old system as a reference field, and their notes and history in order. Their
history source is "import". Notifications and rules for imported records are off by default
and can be switched on per import.

- **Decision:** BETTER.
- **Source:** ADR-024 (history source `import`); architecture §18.2 (what migrates)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An incident imported with a 2024 creation date shows that date and counts in 2024
     reports.
  2. Importing 5,000 closed incidents sends no notifications.
  3. Searching the old system's ID finds the imported record.

#### REQ-ADM-093 — Export everything

An admin can export the whole tenant: every module's records, history, attachments and
configuration, as one background job with no record limit. The result is an encrypted
archive in an open format (JSON and CSV, with attachments as files), available through a
link that expires and needs sign-in. Starting it needs step-up confirmation (REQ-SEC-027) and
is audited.

- **Decision:** BETTER. ServiceDesk Plus exports at most 3,000 records per module and asks
  customers to contact support for a full export.
- **Source:** sdp-area-14 §Screens (export data: 3,000 records, contact support), §Weak spots;
  architecture §11.3 (secure export); architecture §13.6 (read-only mode keeps export)
- **SDP weak spot fixed:** export is capped at 3,000 records and only for supported modules.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A full export of a tenant with 1 million records completes in the background and the
     admin is notified.
  2. The download link expires after the period in Appendix A and refuses use without
     sign-in.
  3. A tenant in licence read-only mode can still run the full export.

#### REQ-ADM-094 — Export a module

Admins export one module's records with chosen fields and filters to CSV, Excel or JSON, in
the background with progress. Exported values use labels in the admin's language; fields the
admin may not see are left out (REQ-INC-116). Exports are listed in an export history.

- **Decision:** BETTER. No record cap; JSON added.
- **Source:** sdp-area-14 §Screens (export data: CSV or XLSX, history table)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Exporting all 300,000 assets produces one file per the per-file limit and lists the files.
  2. The export history shows who exported what, when, and how many rows.

#### REQ-ADM-095 — Archive policies for every module

Admins set archive policies per module: which status categories, which date field, how old,
and exclusions (REQ-INC-118). A dry run shows how many records a policy would archive. Runs
are logged.

- **Decision:** SAME.
- **Source:** sdp-area-13 §Data Archive; REQ-INC-118
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. The dry run for "closed more than 2 years ago" shows the count before saving.
  2. Each run's log shows the number archived and any failures.

#### REQ-ADM-096 — Retention for every log and bin

One page sets how long each kind of log and bin is kept, with a platform minimum and maximum
for each:

- audit log (REQ-AUD-012), sign-in log, system log, personal data access log, telephony log;
- notification delivery log (REQ-NTF-028), automation run log (REQ-RUL-027), workflow history;
- import and export history and export files, trash (REQ-WI-020);
- AI usage logs (file 10).

Expired entries are removed or archived by a scheduled job, and each run is logged.

- **Decision:** NEW. ServiceDesk Plus shows no retention setting for any log.
- **Source:** sdp-area-14 §Screens (retention periods: none shown), §Weak spots; architecture
  §7.3 (partitioning), §11.3 (retention policies per record type)
- **SDP weak spot fixed:** no retention setting for the audit, system or personal data logs.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Setting the system log to 90 days removes entries older than 90 days on the next run.
  2. Setting the audit log below its platform minimum is refused with the minimum shown.
  3. Every retention change is in the audit log.

#### REQ-ADM-097 — Sandbox

An admin creates a sandbox: an isolated copy of the tenant's configuration, with optional
sample data that has personal data masked. Changes are tried there and then promoted to
production (REQ-ADM-098). A sandbox can be refreshed from production and deleted. Sandboxes
do not use licence seats.

- **Decision:** SAME. ServiceDesk Plus has one sandbox on its cloud edition.
- **Source:** sdp-area-14 §Screens (sandbox); architecture §17 (Stage 3: sandbox and
  config-as-code); product-plan §4.3 (pillar 1: sandbox missing on-prem)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. A sandbox created from production has the same fields, templates, rules and roles.
  2. No email leaves a sandbox to real addresses; it is caught and shown in the sandbox.
  3. Sandboxes work the same on SaaS and on-prem.

#### REQ-ADM-098 — Configuration as code

All configuration (fields, forms, pick lists, templates, roles, groups, SLAs, rules,
workflows, catalog, notification templates, settings) can be exported to files, kept in a git
repository, compared, and promoted between environments with a preview of every difference.
References between objects are matched by stable name; secrets are never exported. Automation
follows REQ-RUL-030.

- **Decision:** BETTER. ServiceDesk Plus has a cloud-only sandbox and no export of
  configuration.
- **Source:** product-plan §6 (config-as-code), §8; architecture §17 (Stage 3); REQ-RUL-030
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. Exporting a tenant's configuration and importing it into an empty tenant gives the same
     configuration.
  2. A promotion preview lists each object that will be added, changed or removed.
  3. An exported file contains no passwords, keys or tokens.

---

## 12. Privacy

#### REQ-ADM-099 — Privacy settings

One page sets the tenant's privacy controls: the privacy contact, the privacy notice
(REQ-ADM-102), data subject requests (REQ-ADM-100, REQ-ADM-101), masking (REQ-ADM-103) and
retention of personal data (REQ-ADM-104). Each control shows whether it is on.

- **Decision:** SAME. ServiceDesk Plus has a single switch for personal data handling.
- **Source:** sdp-area-11 §Screens (privacy settings), §Config; sdp-area-14 §Screens (privacy
  settings); architecture §2.15 (compliance tooling)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. The page lists each privacy control with its state and a link to set it.
  2. Every change on the page is in the audit log.

#### REQ-ADM-100 — A person's data on request

An admin with the privacy permission can produce a person's data on request: their profile,
the records they raised or are named in, their messages, approvals and survey answers, as a
machine-readable archive. The request and its delivery are logged.

- **Decision:** SAME.
- **Source:** architecture §11.3 (data export per person), §2.15 (compliance tooling)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A data export for a requester includes all 14 of their records and their messages.
  2. Internal notes are included only if the tenant's policy says so; the setting is shown on
     the request.

#### REQ-ADM-101 — Erasure and anonymisation

An admin can request erasure of a person. A second admin approves it. The job replaces the
person's personal data in records, history, attachments' metadata, search, analytics, AI logs
and assistant conversations (REQ-AI-032) with
an anonymous placeholder, keeps records and counts for reporting, and produces a completion
report. Erasure is blocked while a legal hold applies (REQ-ADM-105, and per desk
REQ-ESM-028). The audit chain stays
verifiable (REQ-AUD-013).

- **Decision:** SAME.
- **Source:** architecture §7.1 (hard delete only through erasure jobs), §11.3; WP-018 (erasure
  keeps the chain verifiable)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. After erasure, searching the person's name or email finds nothing, and their records show
     "erased person".
  2. Report totals for the period are unchanged.
  3. The requesting admin cannot approve their own erasure request.
  4. Assistant conversations and AI log text about the person are erased with the rest.

#### REQ-ADM-102 — Privacy notice and consent

The tenant can show a privacy notice that people must accept at first sign-in to the portal
or console, and again when it changes. Acceptance is recorded with the notice version and
time. Optional consents (for example surveys) can be withdrawn by the person.

- **Decision:** NEW. Not observed in ServiceDesk Plus.
- **Source:** architecture §2.15 (GDPR controls), §11.3
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new notice version is shown to every person at their next sign-in, and they continue
     only after accepting.
  2. A person who withdraws survey consent gets no further surveys.
  3. The admin can list who accepted which version.

#### REQ-ADM-103 — Masking personal data

Admins mark which fields hold personal data, and choose per role whether they are shown,
masked or hidden (REQ-WI-016, REQ-ADM-026). Masking applies in screens, exports, search and
notifications. Personal data is masked before any text is sent to an external AI model
(file 10).

- **Decision:** NEW. ServiceDesk Plus has no data masking setting.
- **Source:** architecture §11.2 (field level), §11.3 (PII masking before external AI);
  sdp-area-14 §Weak spots (no data masking page)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A role with "phone masked" sees "•••• 4521" and cannot filter by phone.
  2. An export by that role contains the masked value.

#### REQ-ADM-104 — Retention of personal data per record type

Admins set, per record type, how long personal data is kept after a record closes, for
example requesters' contact details on closed HR cases after 3 years. After that, the record
is anonymised automatically. Records under legal hold are skipped.

- **Decision:** SAME.
- **Source:** architecture §11.3 (retention policies per record type)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. A dry run shows how many records the policy would anonymise.
  2. A record under legal hold is skipped and listed in the run log.

#### REQ-ADM-105 — Legal hold

An admin with the privacy permission can place people or records on legal hold. Held data
cannot be erased, archived or removed by retention until the hold is lifted. Holds have a
reason and are audited.

- **Decision:** NEW.
- **Source:** architecture §11.3; product-plan §4.3 (pillar 5)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. An erasure request for a held person is refused, naming the hold.
  2. Lifting the hold is recorded with a reason.

---

## 13. Setup and the licence page

#### REQ-ADM-106 — Setup home organised by task

Setup opens on a home page that groups settings by task (people and access, organisation,
service desk, catalog and portal, automation, notifications and mail, data, security, audit,
licence), each with a one-line explanation. Only areas the person may configure are shown
(REQ-ADM-019). Setup is reachable from the main navigation and the command palette.

- **Decision:** BETTER.
- **Source:** sdp-area-01 §Weak spots (setup not in the main navigation); sdp-area-13
  §Navigation path, §Weak spots
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A person with only knowledge configuration rights sees only the knowledge group.
  2. Every setup page is reachable from the home page in at most two clicks.

#### REQ-ADM-107 — Setup search by keyword and meaning

The setup search finds settings by page name, by the names of settings inside pages, and by
common words and synonyms, in the person's language. For example "SSO", "login", "API",
"key", "security", "mobile", "2FA" and "password" lead to the right pages. Results open the
page scrolled to the setting.

- **Decision:** BETTER. ServiceDesk Plus setup search matches page names only.
- **Source:** sdp-area-14 §Behaviour (setup search matches page names only); sdp-area-11
  §Weak spots (setup search found nothing for SSO or login)
- **SDP weak spot fixed:** searching setup for "SSO", "login", "API", "security", "mobile" or
  "key" returned nothing.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Searching "SSO" returns the single sign-on page first.
  2. Searching "2FA" returns the MFA policy page; searching "API key" returns the API keys
     page.
  3. Searching in Arabic finds the same pages.
  4. A search test covers every setting in the setup map with at least one keyword.

#### REQ-ADM-108 — Stable setup navigation

Setup navigation keeps its scroll position and the open group between pages, every page has
its own address that can be bookmarked and shared, and the page title always matches the
content.

- **Decision:** BETTER.
- **Source:** sdp-area-14 §Weak spots (sidebar scroll resets after every page load);
  sdp-area-11 §Navigation path, §Weak spots (stale content under the wrong heading)
- **SDP weak spot fixed:** the setup sidebar scrolls back to the top after every page load,
  and some links showed the previous page's content under a new title.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Opening a page near the end of the setup menu and then the next page keeps the menu
     scrolled to where it was.
  2. Opening a copied setup address in a new tab opens that page.

#### REQ-ADM-109 — Licence and plan page

Admins see the licence and plan in plain words: edition, term and expiry, maintenance
(upgrade) end date, enabled features and add-ons, and each counted limit with use against it
(technicians, managed assets, department desks, customers, AI runs). The page reads only
through the entitlement interface (`has_feature`, `check_limit`, `remaining`); it never
reads the licence file. Usage updates live.

- **Decision:** SAME. ServiceDesk Plus shows plan, expiry and used counts.
- **Source:** sdp-area-14 §Screens (licence and plan); sdp-area-01 §Screens (edition details);
  architecture §13.1, §13.8; CLAUDE.md §5f
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Adding a technician changes the "technicians used" figure on an open licence page within
     2 seconds.
  2. A code search finds no read of the licence file outside the licensing module.
  3. The page shows the same information on SaaS and on-prem.

#### REQ-ADM-110 — Warnings before limits and expiry

Admins are warned before problems: a limit at 90 % use, expiry 30 days ahead, the grace
period after a failed check, and read-only mode, each with what happens next and what to do.
In read-only mode people can still view and export their data (architecture §13.6).

- **Decision:** NEW.
- **Source:** architecture §13.6 (behaviour when a check fails)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. At 9 of 10 technicians, admins see a banner and get one notice.
  2. In read-only mode, creating an incident is refused with a translated reason, and export
     still works.
  3. Non-admins see a short notice in read-only mode, never licence details.

#### REQ-ADM-111 — Activate and renew on-prem

On on-prem installs, the licence page creates the activation request (online, or as a file for
air-gapped sites), imports the signed licence file and shows the result. Renewals and
rehosting use the same steps. The page calls the licensing module only.

- **Decision:** NEW. ServiceDesk Plus on-prem licensing is not part of this research.
- **Source:** architecture §13.2 (on-prem activation flow), §13.4 (rehosting)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An offline activation request downloads as a file, and importing the signed reply
     activates the install without network access.
  2. Importing a licence with a broken signature is refused with a plain reason.
  3. New features in a renewed licence appear without a restart.

#### REQ-ADM-112 — Platform status for admins

Admins see the health of what their tenant depends on: mail in and out, directory sync,
background jobs, imports and exports in progress, search indexing lag and live update
service, with the time of the last problem. On-prem, it also shows each service's health
(ADR-018).

- **Decision:** NEW.
- **Source:** architecture §15 (dependency health on an admin status page); ADR-018
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. When search indexing is 5 minutes behind, the page shows the lag and since when.
  2. The page never shows other tenants' data or internal host names on SaaS.

#### REQ-ADM-113 — Getting started checklist

A new tenant's admins get a checklist: branding, mail, invite the team, sites and groups,
sign-in and MFA policy, portal, and a first catalog item. Items tick themselves when done, and
the checklist can be hidden.

- **Decision:** SAME. ServiceDesk Plus has a getting started page.
- **Source:** sdp-area-01 §Edition notes (getting started page)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Connecting a mailbox ticks the mail item without a reload.
  2. Hiding the checklist hides it for that admin only.

---

## 14. Sign-in and identity

#### REQ-SEC-001 — Sign-in through Keycloak and the backend-for-frontend

All authentication runs through the bundled Keycloak. The browser uses the OpenID Connect
authorisation code flow with PKCE through the backend-for-frontend inside the core API
(D-009). Tokens stay on the server; the browser holds only an HttpOnly, Secure, SameSite
session cookie, and unsafe requests carry a CSRF token. The console, portal and mobile app
use the same identity set-up.

- **Decision:** NEW. ServiceDesk Plus hands sign-in to an outside accounts service.
- **Source:** architecture §11.1; ADR-006; D-009; D-010; CLAUDE.md §8
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. No API response readable by browser scripts contains an access, refresh or ID token.
  2. A state-changing request without the CSRF token is refused with 403.
  3. Signing out ends the SupportX session and the Keycloak session (back-channel logout).
  4. The same sign-in works on SaaS, on-prem and air-gapped installs with no outside service.

#### REQ-SEC-002 — No outside vendor account

People sign in with the tenant's own identity: a local account in the tenant's Keycloak
organisation, or the tenant's single sign-on. Nobody needs an account with Extravis or any
third party to use SupportX.

- **Decision:** BETTER. The vendor requires a third-party vendor account before a technician or
  requester can sign in; invitations must be accepted in that account first.
- **Source:** product owner observation (login, invitation and MFA), finding (a); sdp-area-11
  §Fields (login requires the user to exist in the vendor's organisation and accept an
  invitation), §Edition notes; sdp-area-14 §Weak spots
- **SDP weak spot fixed:** a third-party vendor account is required to sign in.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A new technician completes first sign-in using only the tenant's invitation and the
     tenant's sign-in page.
  2. An e2e test of sign-in, on SaaS and on-prem, makes no request to any host outside the
     install and the tenant's identity provider.
  3. No sign-in or account page names a third-party account provider.

#### REQ-SEC-003 — Tenant-branded sign-in page

The sign-in page shows the tenant's logo, colours, name and language choice (REQ-ADM-055),
in English and Arabic right to left from MVP and Urdu from V1. It offers only the sign-in
methods the tenant has enabled. An unknown address shows the default product brand.

- **Decision:** BETTER. The vendor's sign-in and invitation pages carry the vendor's brand,
  not the customer's.
- **Source:** product owner observation (login, invitation and MFA), finding (b); D-027;
  WP-017
- **SDP weak spot fixed:** sign-in and invitations are vendor-branded rather than
  tenant-branded.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Two tenants on two addresses each see their own logo and colours on the sign-in page.
  2. A tenant with only single sign-on enabled shows only the single sign-on button.
  3. The sign-in page passes the accessibility check in English and Arabic.

#### REQ-SEC-004 — Finding the tenant at sign-in

The tenant is found from the address used (subdomain or custom domain) or, on a shared
address, from the email domain the person types. This only chooses where to sign in; it never
grants access.

- **Decision:** NEW.
- **Source:** D-027 (tenant resolution from the request host as a login hint); D-010
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Opening the tenant's subdomain goes straight to that tenant's sign-in page.
  2. A person of tenant A who signs in through tenant B's address gets no access to tenant B.

#### REQ-SEC-005 — Local accounts and password policy

Tenants can use local accounts. Admins set the password policy: minimum length, character
mix, no reuse of recent passwords, optional expiry, and a block on common and breached
passwords. Repeated failures lock the account for a time (brute-force protection). Defaults
are in Appendix A.

- **Decision:** BETTER. ServiceDesk Plus has no password policy screen; it lives in the
  outside accounts service.
- **Source:** architecture §11.1 (password and lockout policies); sdp-area-11 §Config (no
  password policy found), §Edition notes; sdp-area-14 §Weak spots
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. With a 12-character minimum, a 10-character password is refused with a translated
     message.
  2. After the set number of failures, the account is locked for the set time, and the person
     is told when they can try again.
  3. A password on the breached list is refused.

#### REQ-SEC-006 — Password reset

People reset a forgotten password through a link sent from the tenant's sender, on the
tenant's branded page. Admins can force a reset at next sign-in. A reset ends the person's
other sessions.

- **Decision:** SAME.
- **Source:** architecture §11.1; D-027
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. The reset email comes from the tenant's sender with the tenant's branding.
  2. A reset link works once and expires after the time in Appendix A.
  3. After a reset, the person's sessions on other devices end.

#### REQ-SEC-007 — SAML single sign-on per tenant

A tenant admin sets up SAML 2.0 single sign-on in SupportX: upload the identity provider's
metadata or enter its sign-in address, sign-out address and certificate; map attributes
(email, names, department, site); download SupportX's metadata. A test button signs in with
the new set-up before it is switched on.

- **Decision:** SAME. ServiceDesk Plus configures SAML in its separate directory console.
- **Source:** architecture §11.1 (SAML 2.0); sdp-area-14 §Screens (SAML authentication:
  login URL, logout URL, certificate); D-010
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A test sign-in with a wrong certificate fails with a plain reason and leaves the set-up
     off.
  2. After switching on, a person signs in through the identity provider and lands in their
     tenant.
  3. A department attribute from the provider sets the person's department on first sign-in.

#### REQ-SEC-008 — OpenID Connect single sign-on per tenant

A tenant admin sets up OpenID Connect sign-in with Microsoft Entra ID, Okta, Google or any
standard provider: issuer, client ID and secret, scopes and claim mapping, with a test before
switching on.

- **Decision:** SAME.
- **Source:** architecture §11.1 (OIDC: Entra ID, Okta, Google); sdp-area-14 §Screens
  (integrations: Microsoft Entra ID)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Entra ID sign-in works for a tenant after entering the issuer, client ID and secret.
  2. The client secret is write-only after saving (REQ-SEC-042).

#### REQ-SEC-009 — Enforce single sign-on, keep a break-glass account

A tenant can require single sign-on for everyone, or for technicians only. At least one named
break-glass administrator keeps a local account with MFA, so the tenant is not locked out if
the identity provider fails. Every break-glass sign-in alerts the other admins.

- **Decision:** BETTER.
- **Source:** architecture §11.1; sdp-area-14 §Screens (SAML authentication)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With single sign-on required, the password form is not offered to a technician.
  2. Switching it on without a break-glass admin is refused with a reason.
  3. A break-glass sign-in sends an alert to every other tenant admin.

#### REQ-SEC-010 — Verified email domains

Admins verify the email domains their organisation owns, by a DNS record. Verified domains
route sign-in to the tenant's single sign-on, allow self-registration (REQ-PRT-025), and stop
other tenants from claiming the domain.

- **Decision:** SAME. The vendor's directory console verifies extra domains so their users can
  join without an invitation.
- **Source:** sdp-area-14 §Screens (custom domains)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A domain becomes verified only after its DNS record is found.
  2. A second tenant cannot verify a domain already verified by another tenant.
  3. Typing an address in a verified domain on the shared sign-in page goes to that tenant's
     single sign-on.

#### REQ-SEC-011 — Expiring certificates and secrets

Setup tracks the expiry of single sign-on certificates and client secrets, and warns admins
30, 7 and 1 days ahead. A new certificate can be added before the old one expires, so the
change has no downtime.

- **Decision:** NEW.
- **Source:** architecture §11.1; REQ-NTF-027
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A certificate expiring in 30 days produces one admin alert.
  2. With two certificates loaded, sign-in works with either.

#### REQ-SEC-012 — Directory sign-in on-prem

On-prem and private cloud installs can authenticate against Active Directory or LDAP through
Keycloak's user federation, with optional Kerberos for seamless desktop sign-in. Bringing
people and their details in is done by the directory sync connector (file 12).

- **Decision:** SAME. ServiceDesk Plus offers an AD provisioning app and points to SAML.
- **Source:** architecture §11.1 (LDAP/Active Directory); sdp-area-14 §Screens (Active
  Directory settings)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A person with an AD account signs in with their AD password on an on-prem install.
  2. A disabled AD account cannot sign in at its next attempt.

#### REQ-SEC-013 — First sign-in creates the person

When someone signs in for the first time through the tenant's identity provider and is
allowed in, SupportX creates their person record. Their identity provider role is mapped once
to a starting role (tenant administrator, technician or requester); after that, access is
managed only in SupportX (D-029). Tenants can turn this off and allow only invited or
imported people.

- **Decision:** NEW.
- **Source:** D-029; ADR-022; architecture §11.1
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A first sign-in through single sign-on creates a requester with the provider's name and
     email.
  2. A later role change in the identity provider does not change the person's SupportX roles.
  3. With automatic creation off, an unknown person is refused with a message to contact the
     service desk.

#### REQ-SEC-014 — Roles from identity provider groups

Admins can map identity provider groups to SupportX roles and support groups. With mapping
on, membership follows the provider at every sign-in and sync; mapped roles are marked as
coming from the provider and cannot be changed by hand.

- **Decision:** NEW.
- **Source:** ADR-022 (follow-ups: SSO group to role mapping); D-029
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Adding a person to the provider group "SX-Change-Managers" gives them the change manager
     role at their next sign-in.
  2. Removing them from the group removes the role at the next sign-in or sync.
  3. A mapped role shows its source and cannot be removed by hand.

#### REQ-SEC-015 — Dedicated identity realm

A tenant that needs identity settings the shared realm cannot hold gets its own Keycloak
realm. Its people sign in the same way, and its admins manage it from the same SupportX
screens.

- **Decision:** NEW.
- **Source:** D-010; ADR-006 (revised)
- **Priority:** V1 · **Edition:** Enterprise
- **Acceptance criteria:**
  1. Moving a tenant to a dedicated realm keeps every person's sign-in working.
  2. Setup screens for single sign-on and MFA work the same for shared and dedicated realms.

#### REQ-SEC-016 — People in more than one tenant

A person who belongs to more than one tenant (for example an Extravis engineer serving
several customers) switches between them from the header without signing in again. Each
tenant's data, roles and branding apply after the switch, and the session is renewed.

- **Decision:** NEW.
- **Source:** D-010 (Keycloak Organizations); PROGRESS WP-006 (tenant switch endpoint)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Switching from tenant A to tenant B shows only B's records and B's branding.
  2. The session ID changes on the switch.
  3. A person not in tenant C cannot switch to it.

#### REQ-SEC-017 — All identity settings inside the product

Every sign-in, MFA, session, network and account setting a tenant admin needs is in SupportX
setup. Tenant admins never need the Keycloak admin console or an outside directory product.

- **Decision:** BETTER. ServiceDesk Plus keeps security, MFA, sessions and domain policy in
  outside accounts and directory products, and its own directory screens carry an
  end-of-support notice pointing elsewhere.
- **Source:** sdp-area-14 §Weak spots (vital admin controls outside the product; directory
  screens with end-of-support notices), §Screens (ESM directory: user management banner);
  sdp-area-11 §Config (no password, session, SSO or two-factor screen in setup)
- **SDP weak spot fixed:** security, MFA, sessions and domain policy live outside the product.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An e2e test sets password policy, MFA policy, session timeouts and single sign-on using
     only SupportX screens.
  2. No tenant admin account has rights in the Keycloak admin console.

---

## 15. Invitations

#### REQ-SEC-018 — Invitations in the tenant's name

Invitation emails come from the tenant's configured sender, with the tenant's branding,
language and wording (template in REQ-ADM-068). The link leads to the tenant's sign-in page
to set a password or use single sign-on.

- **Decision:** BETTER. The vendor's invitations are vendor-branded.
- **Source:** product owner observation (login, invitation and MFA), finding (b); D-027;
  sdp-area-11 §Edition notes (login relies on vendor accounts and invitations)
- **SDP weak spot fixed:** invitations carry the vendor's brand rather than the tenant's.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An invitation's sender address is the tenant's configured sender and its logo is the
     tenant's.
  2. An invitation to an Arabic-speaking person is in Arabic.

#### REQ-SEC-019 — No personal address of the inviter

Invitations name the organisation, and may name the inviting admin's display name if the
tenant chooses. They never show the inviter's personal or work email address, in the body or
the headers.

- **Decision:** BETTER. The vendor's invitations expose the inviter's personal email address.
- **Source:** product owner observation (login, invitation and MFA), finding (c)
- **SDP weak spot fixed:** the inviter's personal email address is exposed in invitations.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A test reads the raw invitation message and finds no inviter email address in any header
     or in the body.
  2. Replies to an invitation go to the tenant's configured reply-to address.

#### REQ-SEC-020 — Invitation life cycle

Invitations are pending until accepted, expire after a set time, and can be resent or
revoked. The people list shows invited people with the date sent and the expiry
(REQ-ADM-001). An accepted invitation link cannot be used again.

- **Decision:** SAME. ServiceDesk Plus has pending users and invited users.
- **Source:** sdp-area-11 §Screens (user category: pending users); sdp-area-14 §Screens (ESM
  directory user management: invited users)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. An invitation older than its expiry shows "expired" and its link is refused with a
     message to ask for a new one.
  2. Revoking an invitation makes its link stop working at once.
  3. Using an accepted link a second time is refused.

#### REQ-SEC-021 — Invite without mail

If outgoing mail is not set up, an admin can copy a one-time invitation link to send another
way. The link has the same expiry and single use as an emailed one.

- **Decision:** NEW. ServiceDesk Plus cannot send invitations until mail is set up.
- **Source:** sdp-area-11 §Config (mail not configured, so invitations cannot be sent), §Edition
  notes
- **SDP weak spot fixed:** invitations need mail to be set up first.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With no outgoing mail, the invite action offers "copy link" instead of failing.
  2. Copying the link is in the audit log.

---

## 16. Multi-factor authentication

#### REQ-SEC-022 — MFA with standard authenticator apps

Multi-factor authentication uses standard time-based one-time codes (TOTP), so people can use
any authenticator app they choose. Enrolment shows a QR code and a typed key, and confirms
with a first code.

- **Decision:** BETTER. The vendor's MFA forces its own authenticator app.
- **Source:** product owner observation (login, invitation and MFA), finding (d); architecture
  §11.1 (MFA: TOTP, WebAuthn); sdp-area-14 §Weak spots (2FA outside the product)
- **SDP weak spot fixed:** MFA forces the vendor's own authenticator app.
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Enrolment works with at least three common authenticator apps, tested.
  2. A wrong code during enrolment is refused and the person can try again.
  3. Sign-in asks for the code after the password and refuses an old code.

#### REQ-SEC-023 — Passkeys and security keys

People can register passkeys and hardware security keys (WebAuthn) as a second factor, or as
a password-free sign-in where the tenant allows it.

- **Decision:** NEW.
- **Source:** architecture §11.1 (MFA: WebAuthn)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A person registers a security key and then signs in with password and key.
  2. With password-free sign-in allowed, a person signs in with a passkey only.

#### REQ-SEC-024 — MFA policy

Admins set MFA as off, optional or required, for the tenant and per role. Required MFA gives
a short enrolment grace period (Appendix A). By default, MFA is required for administrators
and optional for others.

- **Decision:** BETTER. The policy is set in the product, per role.
- **Source:** architecture §11.1; sdp-area-14 §Weak spots (2FA outside the product)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Giving someone the tenant administrator role makes them enrol at next sign-in.
  2. After the grace period, a person who has not enrolled can only enrol, not use the product.
  3. The policy page shows how many people in each role have enrolled.

#### REQ-SEC-025 — Recovery codes and MFA reset

At enrolment people get one-time recovery codes. An admin can reset a person's MFA after
checking their identity; the person must enrol again, and the reset is audited and notified
to the person.

- **Decision:** SAME.
- **Source:** architecture §11.1
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A recovery code signs the person in once and cannot be used again.
  2. An MFA reset by an admin sends the person a notice and writes an audit entry.
  3. An admin cannot reset their own MFA.

#### REQ-SEC-026 — MFA with single sign-on

When people sign in through the tenant's single sign-on, the identity provider's MFA is
trusted and SupportX does not ask again, unless the tenant requires SupportX's own MFA too.

- **Decision:** NEW.
- **Source:** architecture §11.1
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A single sign-on user is not asked for a SupportX code by default.
  2. With "also require SupportX MFA" on, they are.

#### REQ-SEC-027 — Confirm identity again for sensitive actions

Sensitive actions ask the signed-in person to confirm their identity again (password and
MFA, or single sign-on again) if they have not done so in the last few minutes: changing
security settings, giving administrator roles, creating API keys, a full export, erasure,
and changing their own email or MFA. No emailed code to someone else's mailbox is used.

- **Decision:** BETTER. The vendor's account page demands a one-time code emailed to the
  owner's mailbox.
- **Source:** sdp-area-14 §Weak spots (my account demands an emailed code), §Limits
- **SDP weak spot fixed:** opening the account page needs a code sent to the owner's mailbox.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Creating an API key 20 minutes after sign-in asks for confirmation; within the window it
     does not.
  2. A failed confirmation leaves the setting unchanged and is in the sign-in log.

---

## 17. Account and sessions

#### REQ-SEC-028 — My account inside the product

Each person has an account page in SupportX: profile details they may edit, change password,
MFA methods and recovery codes, active sessions (REQ-SEC-030), their own API keys
(REQ-INT-019) and recent sign-ins. It opens like any other page, with step-up only for
changes (REQ-SEC-027).

- **Decision:** BETTER. The vendor's account page lives in an outside product behind an
  emailed code.
- **Source:** sdp-area-14 §Screens (profile panel: my account, blocked by OTP), §Weak spots,
  §Limits; sdp-area-01 §Screens (profile drawer: my account)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A person opens their account page without an emailed code.
  2. Changing their password asks for the current one.
  3. Profile fields synced from a directory are read-only with their source shown
     (REQ-ADM-014).

#### REQ-SEC-029 — Session timeouts

Admins set the idle timeout and the absolute session length, separately for the console and
the portal. Before an idle timeout, the person is warned and can stay signed in; unsaved form
input is kept (REQ-INC-019).

- **Decision:** BETTER. Session settings are in the product.
- **Source:** architecture §11.1; PROGRESS WP-006 (idle and absolute timeouts); sdp-area-11
  §Config (no session timeout screen)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. With a 30-minute idle timeout, a person idle for 29 minutes sees a warning, and at 30 is
     signed out.
  2. A form left open through a timeout keeps its input after signing in again.

#### REQ-SEC-030 — Active sessions and sign out everywhere

A person sees their active sessions (device, browser, approximate place, IP address, last
activity) and can end any of them or all others. Admins can see and end any person's
sessions.

- **Decision:** SAME. The vendor's account service lists sessions outside the product.
- **Source:** sdp-area-14 §Limits (my account: sessions)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Ending a session from another device signs that device out within 5 seconds.
  2. "Sign out everywhere else" leaves the current session working.

#### REQ-SEC-031 — Sessions end when access ends

A person's sessions, live update connections and API keys (REQ-INT-019) end at once when
they are deactivated, their MFA or password is reset by an admin, or they lose access to the
tenant. Role changes take effect without ending the session (REQ-WI-015).

- **Decision:** NEW.
- **Source:** architecture §11.1, §8.2; REQ-ADM-010
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Deactivating a person closes their live update connection within 5 seconds.
  2. Their API key returns 401 on the next call.

#### REQ-SEC-032 — Concurrent session limit

A tenant can limit how many sessions one person may have at a time. Signing in beyond the
limit ends the oldest session, and the person is told.

- **Decision:** SAME.
- **Source:** architecture §11.1 (session policies)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. With a limit of 2, a third sign-in ends the oldest of the two sessions.
  2. The ended session shows a message explaining why on its next action.

#### REQ-SEC-033 — Sign-in alerts to the person

People get a notice when their account is signed in from a new device or browser, when it is
locked after failed attempts, and when their password, email or MFA changes.

- **Decision:** NEW.
- **Source:** architecture §11.1
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A sign-in from a new browser sends one notice to the person with time and approximate
     place.
  2. A lock-out sends a notice with the time the account opens again.

---

## 18. Network and API access

#### REQ-SEC-034 — IP allow-lists

Admins can restrict access by IP address ranges, separately for the console, the portal and
the API. Saving a list that would lock out the admin making the change is refused. Break-glass
admins (REQ-SEC-009) can be exempted.

- **Decision:** NEW. No IP restriction was found in ServiceDesk Plus setup.
- **Source:** sdp-area-14 §Limits (IP restrictions not found), §Weak spots (no IP restriction
  page)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With a console allow-list, a sign-in from outside it is refused with a clear message.
  2. Saving a list that does not contain the admin's current address is refused.
  3. The portal stays reachable from anywhere when only the console is restricted.

#### REQ-SEC-035 — Brute-force and rate limits

Sign-in, password reset, invitation and API endpoints are protected against guessing and
floods: failed attempts slow down and then lock, and the API returns rate-limit headers and
429 when a limit is reached.

- **Decision:** SAME.
- **Source:** architecture §10 (rate-limit headers), §11.1 (lockout policies); PROGRESS WP-006
  (brute-force protection)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. 100 password-reset requests for one address in a minute send at most the limit in
     Appendix A.
  2. An API key over its rate limit gets 429 with a retry time.

#### REQ-SEC-036 — Service accounts

Admins create and manage service accounts: non-human identities with roles and scopes like
people, an owner, a description and no interactive sign-in. Connectors and API clients act as
such an identity (REQ-INT-012). Service accounts do not use technician seats. Their actions
show the service account as actor.

- **Decision:** NEW. In the vendor, integrations act as the admin who set them up.
- **Source:** architecture §11.1 (short-lived service tokens), §6.1 (identity_access: API
  tokens); REQ-INT-012
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A service account with "incident: create" can create incidents through the API and
     cannot sign in to the console.
  2. Records it creates show the service account as creator in history.
  3. Deactivating its owner flags the service account for the hand-over (REQ-ADM-011).

#### REQ-SEC-037 — Tenant policy for API keys and tokens

API keys, OAuth clients and scopes are specified in file 12 (REQ-INT-019 to REQ-INT-021).
Admins set the tenant policy around them on the security pages:

- who may create keys for themselves (a permission, off for technicians by default);
- the maximum lifetime of a key, and whether keys must have an IP range;
- one list of every key and OAuth client in the tenant, with owner, scopes, last use and
  expiry, and revoke from that list;
- keys unused for a set time are listed to admins, and a deactivated person's keys stop at
  once (REQ-SEC-031).

- **Decision:** BETTER. ServiceDesk Plus shows no API key page in setup.
- **Source:** sdp-area-14 §Limits (no API key or OAuth console), §Weak spots; REQ-INT-019;
  REQ-INT-020; PROGRESS WP-006 (API-key stub)
- **SDP weak spot fixed:** there is no setup page for API keys.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With a 90-day maximum lifetime, creating a key with a 1-year expiry is refused with the
     limit shown.
  2. The tenant key list shows every key, including personal ones, without showing any key
     value.
  3. Keys unused for the set time appear in the admin list, and revoking one makes the next
     call return 401.

#### REQ-SEC-038 — Sign-in for the mobile app and other apps

The mobile app and other first-party apps sign in through the same Keycloak set-up with the
OpenID Connect code flow and PKCE in the system browser, so single sign-on and MFA work the
same as on the web. Their refresh tokens are bound to the device, listed as sessions
(REQ-SEC-030) and revocable.

- **Decision:** NEW.
- **Source:** architecture §11.1, §9.1 (mobile apps); sdp-area-01 §Screens (profile drawer:
  iOS and Android app icons); sdp-area-14 §Limits (no mobile app settings page)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A tenant with single sign-on required signs in to the mobile app through its identity
     provider.
  2. Ending the app's session from the web account page signs the app out at its next call.
  3. The app never stores a password.

---

## 19. Data protection

#### REQ-SEC-039 — Encryption in transit and at rest

All traffic uses TLS 1.2 or later with HSTS on public endpoints. Data at rest is encrypted:
database volumes, object storage and backups. Files are encrypted per tenant. The security
overview (REQ-SEC-044) shows this state.

- **Decision:** NEW. Encryption is not observable in ServiceDesk Plus.
- **Source:** architecture §11.3, §6.8 (per-tenant file encryption); product-plan §8 (security
  baseline); sdp-area-14 §Limits (encryption not observable)
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. A TLS 1.1 connection to any public endpoint is refused.
  2. Every public response carries an HSTS header.
  3. An install check confirms encrypted volumes and storage and reports any that are not.

#### REQ-SEC-040 — Field-level encryption

Admins mark sensitive fields (for example national ID or salary) to be encrypted inside the
application with AES-256-GCM, keys held in a key management service (SaaS) or the install's
keystore (on-prem). Encrypted fields can be matched exactly but not searched by partial text,
and are decrypted only for roles allowed to see them. Keys can be rotated.

- **Decision:** NEW.
- **Source:** architecture §11.3 (envelope encryption for designated fields); product-plan §5
  (security and access: field-level encryption), §8; D-021
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. A database read of an encrypted field returns ciphertext.
  2. A role allowed to see the field gets the clear value through the API; others get it
     hidden or masked.
  3. Rotating the key keeps every value readable.

#### REQ-SEC-041 — Customer-managed keys

Enterprise tenants can supply their own key from their key management service for the
tenant's encryption keys, and revoke it to make their data unreadable.

- **Decision:** NEW.
- **Source:** architecture §11.3 (keys in KMS); product-plan §4.2 (regulated buyers)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. With a customer key set, revoking it makes the tenant's encrypted fields and files
     unreadable, and the product says why.
  2. Restoring the key restores access with no data loss.

#### REQ-SEC-042 — Secrets in settings are write-only

Passwords, client secrets, private keys and tokens entered in setup (mail, single sign-on,
connections, webhooks) are encrypted, never shown again, never logged and never exported.
Screens show only that a secret is set, and when it was last changed.

- **Decision:** NEW.
- **Source:** architecture §11.3 (secrets never in images, code or logs); CLAUDE.md §8
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. Reading a mail server setting through the API returns "set" for the password, not its
     value.
  2. A log search after saving a secret finds no trace of it.

#### REQ-SEC-043 — Data residency

A SaaS tenant is placed in one region cell chosen at sign-up (for example Saudi Arabia, UAE,
Pakistan or the EU). Its data, backups, search, analytics and files stay in that cell. The
security overview shows the region. External AI calls follow the tenant's AI settings
(file 10, D-049). On-prem and air-gapped installs keep everything on site.

- **Decision:** NEW. The vendor has no GCC or Pakistan region.
- **Source:** architecture §14.1 (cell-based regions); product-plan §2 (no regional data
  residency at the vendor), §4.3
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. A tenant created in the Saudi cell has its database, files and backups only in that cell.
  2. The security overview shows the tenant's region.

#### REQ-SEC-044 — Security overview page

One page shows the tenant's security state: sign-in methods, MFA policy and enrolment by
role, single sign-on state and certificate expiry, password and session policy, IP
allow-lists, API keys and service accounts, encryption and region, vendor support access, and
recent security events. Each item links to its setting and flags weak choices with a
recommendation.

- **Decision:** NEW. ServiceDesk Plus has no security policy page.
- **Source:** sdp-area-14 §Weak spots (no setup page for security policy), §Limits
- **SDP weak spot fixed:** there is no setup page named for security policy.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With MFA optional for administrators, the page flags it and links to the MFA policy.
  2. The enrolment counts on the page match the MFA policy page.

#### REQ-SEC-045 — Vendor support access with consent

Extravis support staff can see a tenant's data only when a tenant admin grants access for a
set time and purpose. Every action they take is audited with their identity and the grant.
The tenant can end the grant at any time.

- **Decision:** NEW.
- **Source:** architecture §11.2, §7.4; product-plan §4.2 (government and bank buyers)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Without a grant, a support engineer cannot open any tenant record.
  2. A grant for 4 hours ends after 4 hours with no action needed.
  3. Each support action shows in the audit log as "Extravis support" with the grant ID.

#### REQ-SEC-046 — Application security baseline

The product is built and checked against OWASP ASVS level 2: strict content security policy,
output encoding, server-side sanitising of rich text, static, dependency, image and secret
scanning in CI, signed images, a software bill of materials per release, and a yearly outside
penetration test.

- **Decision:** NEW.
- **Source:** architecture §11.4; CLAUDE.md §8
- **Priority:** MVP · **Edition:** Essentials
- **Acceptance criteria:**
  1. CI fails on a high-severity finding from the scanners.
  2. Every release has a signed image and a bill of materials.
  3. Every response carries the content security policy header.

#### REQ-SEC-047 — Mobile app access policy

Admins set mobile app rules: whether the app may be used, required MFA, a device unlock
(PIN or biometrics) to open the app, session length, and clearing local data at sign-out.

- **Decision:** NEW. ServiceDesk Plus has no mobile app settings page.
- **Source:** sdp-area-14 §Limits (no mobile app settings page), §Weak spots
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. With mobile use off, the app refuses sign-in with a message from the tenant.
  2. With device unlock required, the app asks for it after being in the background longer
     than the set time.

---

## 20. The audit log

#### REQ-AUD-001 — Tamper-evident audit log

Security-relevant actions are written to an append-only audit log, separate from record
history. Each entry holds the hash of the previous entry of the same tenant (a hash chain),
and the chain is anchored at regular intervals, so changing or removing any entry is
detected. The application can only add and read entries.

- **Decision:** BETTER. ServiceDesk Plus has an audit log; ours is provably unchanged.
- **Source:** architecture §7.4; D-034; PROGRESS WP-018; sdp-area-14 §Screens (audit log)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Changing one stored entry directly in the database makes verification fail and name the
     first broken entry (REQ-AUD-010).
  2. Deleting an entry is detected the same way.
  3. The application database role has no update or delete right on the audit table.
  4. Each tenant has its own chain; tenant A's entries never appear in tenant B's log.

#### REQ-AUD-002 — What is audited

The audit log records at least:

- sign-in events of administrators, step-up confirmations, MFA and password resets;
- people: create, change of access, deactivate, reactivate, merge, erase;
- roles, grants, groups, organisation roles and field rules;
- every configuration change, with a link to its version (REQ-ADM-048, REQ-RUL-026);
- security settings, API keys, service accounts, IP lists, single sign-on, vendor support
  grants;
- imports, exports, undo of imports, archive and retention runs, erasure, legal holds;
- licence events: activation, renewal, limit reached, read-only mode;
- the record actions of REQ-WI-021 (delete, restore, purge, merge, bulk changes, edits to
  closed records, due date changes).

- **Decision:** SAME.
- **Source:** architecture §7.4, §11 ("every privileged action is audited"); CLAUDE.md §8;
  REQ-WI-021; sdp-area-14 §Screens (audit log: "modified trigger (disable)")
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A test performs each listed action once and finds exactly one audit entry for each.
  2. A new admin action without an audit entry fails an architecture test that checks every
     admin route is audited.

#### REQ-AUD-003 — What an entry shows

Each entry shows: time to the second in the reader's time zone; actor and actor type (person,
service account, API key, AI agent, automation, system, Extravis support); on whose behalf;
the action as a translated label; the object with a link; a summary of what changed; the
outcome (done, refused, failed); IP address, client (console, portal, API, mobile) and request
ID. No internal operation codes are shown.

- **Decision:** BETTER. ServiceDesk Plus shows an internal operation code in each entry.
- **Source:** sdp-area-14 §Screens (audit log entry: time, operation, object, internal operation
  code, who, client icon, log ID, related application logs); architecture §9.5
- **SDP weak spot fixed:** entries show an internal operation code next to the operation.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An entry for a role change shows the role, the grants added and removed, the actor, and
     the IP address.
  2. The same entry shows in Arabic with translated action labels.
  3. The request ID on an entry leads support to the matching trace.

#### REQ-AUD-004 — Reads of sensitive settings and data

Viewing sensitive settings and data is audited too: security settings, the audit log itself,
secrets pages, full exports, personal data views covered by REQ-AUD-017, and other categories
the admin switches on. Everyday reads of records are not logged here.

- **Decision:** SAME. ServiceDesk Plus logs reads of settings pages ("accessed instance
  settings").
- **Source:** sdp-area-14 §Screens (audit log records reads), §Behaviour (reading a page is
  logged)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Opening the single sign-on settings page writes one read entry.
  2. Opening an incident does not write an audit entry.
  3. Switching on "log reads of survey results" starts logging those reads.

#### REQ-AUD-005 — Refused and failed attempts

Attempts to perform an audited action that are refused (permission, licence, step-up failed)
or that fail are logged with the reason code, so probing is visible.

- **Decision:** NEW.
- **Source:** architecture §7.4, §11.2
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A technician trying to open the roles API gets 403 and an audit entry with outcome
     "refused".
  2. Ten refused admin attempts by one person in 10 minutes alert the security admins once.

#### REQ-AUD-006 — Audit and field history linked

An audit entry about a record links to that record's field history entries for the same
change (REQ-WI-003), and the record's history shows that an audit entry exists for
privileged changes.

- **Decision:** NEW.
- **Source:** architecture §7.4 (history and audit); ADR-024 (field history is not the audit
  log)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Changing a due date on an incident creates one history entry and one audit entry that
     link to each other.
  2. A person who can see the record but not the audit log sees the history entry without the
     link.

#### REQ-AUD-007 — Search and filters

Auditors search the log by actor, actor type, action, module, object, outcome, IP address,
client and time range (today, last 7 or 30 days, this or last month, custom), save
searches, and page through results without limits. New entries appear live at the top.

- **Decision:** SAME.
- **Source:** sdp-area-14 §Screens (audit log filters: criteria builder, date filter, sort, load
  more)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Filtering by actor and last 7 days returns only that actor's entries in that range.
  2. A search over 10 million entries returns the first page in under 2 seconds.
  3. A new entry matching the open filter appears without a reload.

#### REQ-AUD-008 — Who may read the audit log

Reading and exporting the audit log are permissions of their own, held by the auditor role
and tenant administrators. Nobody, including tenant administrators and Extravis support, can
change or delete entries. Reading the log is itself audited (REQ-AUD-004).

- **Decision:** NEW.
- **Source:** architecture §7.4, §11.2
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A service desk manager without the permission gets 404 on the audit log pages and API.
  2. No API exists to change or delete an audit entry.

#### REQ-AUD-009 — Export for auditors

Auditors export the log for a time range and filter to CSV or JSON as a background job. The
export includes the chain values and a verification result, so an outside auditor can check
it has not been changed. Exports are audited.

- **Decision:** SAME. ServiceDesk Plus offers a download.
- **Source:** architecture §7.4 (exportable for compliance evidence); PROGRESS WP-018;
  sdp-area-14 §Actions (audit log download)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. Exporting one month of entries gives a file whose chain values verify with the published
     verification tool.
  2. Removing a line from the exported file makes the outside verification fail.

#### REQ-AUD-010 — Verify the chain

Admins can verify the chain for a time range on demand, and it is verified automatically on a
schedule (Appendix A). A failed verification alerts the tenant's security admins and Extravis
operations, and names the first broken entry.

- **Decision:** NEW.
- **Source:** architecture §7.4; PROGRESS WP-018 (verification tool)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A verification of a clean range reports success with the number of entries checked.
  2. A broken chain sends one alert and shows the first broken entry's time and ID.

#### REQ-AUD-011 — Stream to a security monitoring system

Admins can stream audit and sign-in entries to their security monitoring system (SIEM) in
standard formats (syslog with CEF or JSON, or HTTPS webhook), with retry and a delivery
status.

- **Decision:** NEW.
- **Source:** architecture §7.4; product-plan §4.2 (regulated buyers)
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. An audit entry reaches a test syslog receiver within 10 seconds.
  2. When the receiver is down, entries are queued and sent in order when it returns.

#### REQ-AUD-012 — Audit retention and archive

The audit log is kept for the tenant's retention period (REQ-ADM-096), never below the
platform minimum (Appendix A). Older entries move to archive storage with their chain values
and can be restored for an investigation. Monthly partitions keep the log fast at scale.

- **Decision:** NEW. ServiceDesk Plus shows no audit retention setting.
- **Source:** sdp-area-14 §Weak spots (no retention setting for audit, system or PII logs);
  architecture §7.3 (partitioning); PROGRESS WP-018 (retention and archiving)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. The retention job moves entries older than the period to archive, tested on 10 million
     rows.
  2. Archived entries restored for a range still verify.

#### REQ-AUD-013 — Erasure keeps the chain verifiable

When a person is erased (REQ-ADM-101), personal data in audit entries is replaced by a
pseudonym in a way that keeps the chain verifiable, and the erasure itself is recorded.

- **Decision:** NEW.
- **Source:** PROGRESS WP-018 (GDPR erasure that keeps the chain verifiable); architecture
  §11.3
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. After erasing a person, their name and email appear in no audit entry, and verification
     still succeeds.
  2. Entries by the erased person still group together under the same pseudonym.

#### REQ-AUD-014 — AI agent actions in the audit log

Actions taken by AI agents are audited with the agent, the version, the person or rule on
whose behalf it acted, and the tools it used. Agent permissions and approvals are defined in
file 10.

- **Decision:** NEW.
- **Source:** product-plan §7.1 (full audit trail of every agent action); architecture §11.2
  (one policy layer for AI agents)
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. An agent that changes an incident's priority writes an entry naming the agent and the
     person who started it.
  2. Filtering by actor type "AI agent" lists only agent actions.

---

## 21. Other logs and compliance

#### REQ-AUD-015 — Sign-in log

Admins see every sign-in event: success, failure with a readable reason (wrong password,
locked, MFA failed, single sign-on error, IP not allowed), sign-out, lock-out and MFA events,
with time, person, method, IP address and device. People see their own recent sign-ins
(REQ-SEC-028).

- **Decision:** NEW. Sign-in events sit in the vendor's outside accounts service.
- **Source:** sdp-area-14 §Weak spots (security and sessions outside the product); architecture
  §11.1
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A failed single sign-on shows the reason in plain words, for example "certificate does not
     match".
  2. Filtering by "failed" for the last 24 hours lists only failures in that range.

#### REQ-AUD-016 — System log

A system log shows background events and failures: automation, scheduled jobs, mail polling
and sending, directory sync, imports and exports, retention runs, licence checks and
integration calls. Each entry has a severity, module, message, time and a link to the object
it concerns. Admins filter and export it. Entries are removed only by retention, not by hand.
Failures also surface on the affected record or setting (REQ-WI-009).

- **Decision:** BETTER. Same content, linked to objects, and entries cannot be deleted by
  hand.
- **Source:** sdp-area-14 §Screens (system log: columns, delete, delete all, export);
  REQ-WI-009; REQ-RUL-027
- **SDP weak spot fixed:** the system log can be emptied with one "delete all" button.
- **Priority:** V1 · **Edition:** Essentials
- **Acceptance criteria:**
  1. A failed mailbox check writes an error entry that links to the mailbox settings.
  2. No API or screen deletes system log entries.
  3. Exporting the filtered log gives the same rows as the screen.

#### REQ-AUD-017 — Personal data access log

When enabled, views and exports of fields marked as personal data are logged: who saw or
exported whose data, when and where. For a data subject request, an admin can list everyone
who accessed one person's data in a period. Masking events from the AI features (REQ-AI-019)
are written here as counts per type, never with the values.

- **Decision:** SAME. ServiceDesk Plus has a personal data log with a weekly filter and
  export.
- **Source:** sdp-area-14 §Screens (PII/ePHI log); architecture §6.1 (audit: data-access logs);
  REQ-AI-019
- **Priority:** V1 · **Edition:** Professional
- **Acceptance criteria:**
  1. Opening a requester's profile with a personal-data field writes one access entry.
  2. The per-person report lists each accessor with time and screen.
  3. A masked value sent to an AI model adds a masking entry with its type and no value.

#### REQ-AUD-018 — Telephony and channel log

When a telephony or chat connector is in use (REQ-INT-078, REQ-INT-094), calls and chats
are logged with caller and receiver, numbers or handles, time, duration, and the record they created or
updated. Admins filter and export the log.

- **Decision:** SAME.
- **Source:** sdp-area-14 §Screens (telephony log: caller and receiver, module, record ID, time);
  sdp-area-14 §Screens (integrations: cloud telephony)
- **Priority:** LATER · **Edition:** Essentials
- **Acceptance criteria:**
  1. A call that creates an incident appears in the log with a link to that incident.
  2. With no telephony connector, the log page explains how to set one up.

#### REQ-AUD-019 — Compliance evidence packs

Enterprise tenants can switch on regional compliance packs (NCA ECC, SAMA, UAE IA, Qatar NIA,
SBP, PTA, and ISO 27001). Each pack maps the pack's controls to SupportX settings and logs,
shows which controls are met, and produces an evidence report for a period from the audit
log, sign-in log, access reviews (REQ-ADM-028) and settings history.

- **Decision:** NEW. ServiceDesk Plus maps only global frameworks, in documents.
- **Source:** product-plan §4.3 (pillar 5: regional compliance), §6 (regional compliance
  packs), §9 (Enterprise); architecture §17 (Stage 3: compliance evidence engine)
- **Priority:** LATER · **Edition:** Enterprise
- **Acceptance criteria:**
  1. Switching on the SAMA pack lists its mapped controls with met or not met for each.
  2. A control about MFA for administrators shows "not met" when MFA is optional for admins.
  3. The evidence report for a quarter includes the audit export and its verification result.

---

## Appendix A — Proposed defaults

These are the defaults a new tenant gets. They are seed data, not fixed behaviour: a tenant
admin can change every one of them (D-041). Platform minimums and maximums, where given, cap
what a tenant can set. The requirements above refer to this appendix.

**Roles a new tenant starts with** (REQ-ADM-018). Roles for modules outside the tenant's
edition are present but marked as needing an upgrade.

| Role | What it grants |
|---|---|
| Tenant administrator | Everything, at scope all. Cannot be edited (REQ-ADM-021). |
| Security administrator | Sign-in, MFA, sessions, IP lists, API keys, service accounts, security overview; no record access. |
| Site administrator | People, groups, departments and site settings for their sites. |
| Service desk manager | All incident and service request actions at scope all; service desk configuration; share reports and dashboards. |
| Technician | Incidents and service requests at scope group plus own; knowledge view, create and edit own; run reports; announcements view all, manage own. |
| Requester | Portal: own requests, catalog and knowledge for their audiences. |
| Knowledge manager | Every knowledge permission (REQ-KB-043). |
| Problem manager | Every problem permission (REQ-PRB-070). |
| Change manager | Every change permission, including approve and CAB (REQ-CHG-038). |
| Release manager | Every release permission (REQ-REL-023). |
| Asset manager | Every asset, software and contract permission (REQ-AST-058, REQ-CON-015). |
| CMDB manager | Every CMDB permission (REQ-CMDB-031). |
| Report viewer | Run reports and view dashboards shared with them (REQ-RPT-048). |
| Auditor | Read and export the audit, sign-in, system and personal data access logs; read-only settings. |

Approval administrators (REQ-SR-023) are a support group seeded with the tenant
administrators.

**Segregation-of-duties rules** (REQ-ADM-022): auditor with tenant administrator or security
administrator; create purchase order with approve purchase order; manage roles with run
access reviews.

**People and lifecycle:**

- people created from a first single sign-on sign-in: on, as requester (REQ-SEC-013);
- a person removed from the directory: deactivated (REQ-ADM-014);
- hand-over proposals (REQ-ADM-011): open work items to their group's queue, unassigned;
  approvals to the stage backup, else approval administrators; articles to the topic owner;
  reports, dashboards and automations to the person's manager, else tenant administrators;
- undo windows: merge of people 30 days (REQ-ADM-012), import 30 days (REQ-ADM-089);
- notice before a time-limited role ends: 24 hours (REQ-ADM-027).

**Instance and preferences:**

- one default site, named after the tenant (REQ-ADM-037);
- default language: chosen at sign-up (English or Arabic); languages offered: English and
  Arabic, plus Urdu from V1 (REQ-ADM-052);
- first day of the week: Sunday when the default language is Arabic, Monday otherwise
  (REQ-ADM-049), as in file 09;
- navigation layout: top bar (D-031); theme: follow the system; text size 100 %
  (REQ-ADM-060, REQ-ADM-062);
- people may personalise theme and text size: on (REQ-ADM-056).

**Mail** (REQ-ADM-067): fetched mail marked as read and moved to a "Processed by SupportX"
folder. Mailbox defaults (check interval, creation by email) are in file 12 Appendix A; mail
from unknown senders creates a requester (REQ-INC-027).

**Surveys** (REQ-ADM-069 to REQ-ADM-076): off. When switched on: sent on every closed incident
and service request; at most one survey per requester in 14 days; surveys expire after 14
days; scale of five levels (very poor, poor, fair, good, excellent); low rating is the two
lowest levels (REQ-INC-103).

**Announcements** (REQ-ADM-077 to REQ-ADM-084): types service down, service restored,
planned maintenance, new service, policy and general; second-person publishing off (D-032);
acknowledgement off.

**Sign-in and sessions:**

| Setting | Default | Platform limit |
|---|---|---|
| Minimum password length (REQ-SEC-005) | 12 characters | at least 8 |
| Password reuse | last 5 refused | |
| Password expiry | none | |
| Breached password check | on | |
| Lock-out | 5 failures in 15 minutes locks for 15 minutes, doubling on repeat | |
| Password reset link (REQ-SEC-006) | single use, 60 minutes | at most 24 hours |
| Invitation link (REQ-SEC-020) | single use, 7 days | at most 30 days |
| MFA (REQ-SEC-024) | required for tenant, security and site administrators and auditors; optional for others | |
| MFA enrolment grace | 7 days | at most 30 days |
| Console session (REQ-SEC-029) | 60 minutes idle, 12 hours absolute | absolute at most 7 days |
| Portal session | 30 minutes idle, 12 hours absolute | absolute at most 30 days |
| Idle warning | 2 minutes before | |
| Step-up window (REQ-SEC-027) | 10 minutes | at most 60 minutes |
| Password reset requests (REQ-SEC-035) | 5 per address per hour | |
| API key maximum lifetime (REQ-SEC-037) | 1 year | at most 2 years |
| Unused API keys listed after | 90 days | |
| Keys for themselves (REQ-SEC-037) | technicians: off; admins: on | |
| Concurrent session limit (REQ-SEC-032) | none | |
| IP allow-lists (REQ-SEC-034) | none | |
| SSO certificate expiry warnings (REQ-SEC-011) | 30, 7 and 1 days ahead | |

**Retention** (REQ-ADM-096):

| Log or bin | Default | Platform minimum | Platform maximum |
|---|---|---|---|
| Audit log (REQ-AUD-012) | 3 years | 1 year | 10 years |
| Sign-in log (REQ-AUD-015) | 1 year | 90 days | 5 years |
| System log (REQ-AUD-016) | 180 days | 30 days | 2 years |
| Personal data access log (REQ-AUD-017) | 2 years | 1 year | 10 years |
| Telephony and channel log (REQ-AUD-018) | 1 year | 30 days | 5 years |
| Import and export history | 1 year | 90 days | 5 years |
| Export files (REQ-ADM-093, REQ-ADM-094) | 7 days | 1 day | 30 days |
| Notification delivery log, automation run log | as file 03 Appendix A | | |
| Trash | 30 days (file 01 Appendix A) | | |

**Audit verification** (REQ-AUD-010): daily for the previous day, and weekly for the full
chain.

**Licence warnings** (REQ-ADM-110): at 90 % of a counted limit; 30, 7 and 1 days before
expiry; grace period 14 days (architecture §13.6).

**Privacy** (REQ-ADM-099 to REQ-ADM-105): privacy notice off; personal data access log off;
erasure needs a second admin's approval; internal notes not included in a person's data
export.

---

## Open questions for the product owner

1. **Audit log at MVP?** The tamper-evident audit log (REQ-AUD-001 to REQ-AUD-010) is set to
   V1, in line with REQ-WI-021 and D-034. WP-018 is planned in Stage 1. Should the design
   partner customer get it at go-live (MVP)?
2. **Single sign-on edition.** SAML and OpenID Connect single sign-on (REQ-SEC-007,
   REQ-SEC-008) are set to Essentials and MVP, since product-plan §10 lists SSO in Phase 1
   and every tender asks for it. Many vendors charge for SSO. Keep it in Essentials?
3. **Field-level encryption and masking edition.** Field-level encryption (REQ-SEC-040),
   masking (REQ-ADM-103), field access rules (REQ-ADM-026) and the personal data access log
   (REQ-AUD-017) are Professional, matching REQ-WI-016. product-plan lists field-level
   encryption as a P0 security baseline. Should any of them be Essentials?
4. **MFA by default.** Appendix A requires MFA for administrators and auditors and leaves it
   optional for technicians. Should MFA be required for every technician in a new tenant?
5. **Vendor support access.** REQ-SEC-045 lets Extravis support see tenant data only with a
   time-limited grant from a tenant admin. Is that acceptable for Extravis's own support
   operations on SaaS, including during an outage?
6. **Audit retention minimum.** The proposed platform minimum is 1 year and the default 3
   years. Some regulators in our markets ask for 5 years or more. Should the default follow
   the compliance pack a tenant switches on?
7. **Service accounts and seats.** Service accounts do not use technician seats
   (REQ-SEC-036). Is that the commercial intent, or should there be a separate limit?
8. **Dedicated identity realm edition.** REQ-SEC-015 is Enterprise. Should a dedicated realm be
   available to any tenant that needs a custom SSO set-up (D-010 does not tie it to an
   edition)?
9. **Languages beyond English, Arabic and Urdu.** architecture §2.15 asks for 40 or more
   languages. Which come next, and at what priority?
10. **Announcements ownership.** File 02 (question 9) asked whether file 11 should own the
    announcements module. This file now does (REQ-ADM-077 to REQ-ADM-084). Please confirm.
11. **Custom modules.** Custom modules (REQ-ADM-047) are LATER and Professional. Should they
    move to Enterprise, alongside sandbox and configuration as code?
12. **Data residency timing.** Multi-region SaaS cells are Stage 3 in architecture §17, so
    REQ-SEC-043 is LATER. Must the first external SaaS customers already choose a region (for
    example the Saudi cell) at V1?
