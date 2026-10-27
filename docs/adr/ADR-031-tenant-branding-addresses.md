# ADR-031: Tenant branding and addresses

- **Status:** Accepted (WP-017; D-027, D-090, D-093)
- **Date:** 2026-10-27
- **Deciders:** Haider (Product Owner), lane B

## Context

Each tenant needs its own look (logo, colours, names) on the console, the portal, the Keycloak
sign-in page and e-mails, and its own address: a subdomain, or a custom domain with a
certificate (REQ-ADM-055, REQ-PRT-016, REQ-SEC-003, REQ-SEC-004). The address may only hint at
where to sign in; it never grants access. One shared Keycloak realm serves every tenant through
Organizations (D-010), and Keycloak and the API share one host in Kubernetes (D-038).

## Decision

1. **Brand data lives in the organization module**, one row per tenant (`tenant_branding`); empty
   means the SupportX default from `palette.json` (D-078). Colours are checked on the server with
   the same rules as the SupportX brand (`organization/domain/branding.py`, also used by
   `make brand-assets`); a failing colour is refused with the nearest passing one (D-090).
2. **Uploads are files** (WP-022, owner `branding`): scanned and encrypted like any file. The
   variants every surface shows (logo per theme, icon, favicons) are generated with Pillow on
   save into `branding_assets` and **served publicly** on versioned URLs cached for a year: the
   sign-in page and e-mails need them before anyone signs in, and they are not secret. Public
   routes tell an address's logo and colours and nothing else, are keyed by the tenant's ID
   (unguessable), and answer an unknown ID exactly like an unbranded tenant, so they cannot be
   used to list or probe tenants. Only they may be used cross-origin.
3. **The sign-in page is branded without a Keycloak extension.** Keycloak 26.8 gives login
   templates the organization in context (`org`). The SupportX theme's `template.ftl` (upstream
   keycloak.v2 plus one marked block) links `<branding URL>/<tenant_id>/login.css` (the
   organization's `tenant_id` attribute), a stylesheet
   the API renders from the same template as the default theme. Keycloak knows the organization
   when SupportX asks for it (scope `organization:<alias>`), or once the e-mail's domain names it.
4. **The address picks the organization, never the access.** The BFF resolves the request's host
   (`<slug>.<tenant_base_domain>`, or a verified custom domain) through two SECURITY DEFINER
   lookups (no tenant is known before sign-in) and then:
   - asks Keycloak for that organization only, so every Keycloak page shows that brand and the
     token names only that tenant;
   - keeps the callback on the same address, so the session cookie belongs to it.

   Someone who is not a member gets no organization and the existing `no_organization` refusal.
   A login cannot finish on another address than it started on.
5. **Custom domains are proved with an HTTP token** the installation answers with an HMAC (the
   ACME HTTP-01 idea; no DNS library). The check refuses loopback, link-local, multicast and
   reserved addresses, follows no redirects and reads at most 256 bytes. Only verified domains
   resolve. A single-server installation may upload its own certificate (checked, key encrypted
   with the tenant's data key).

## Consequences

- One cross-tenant read exists: the migrator-owned resolver may read verified domains of every
  tenant (`tenant_domains_resolve`, allowlisted in the RLS guard with its reason).
- On a tenant's own address a person in several tenants sees only that tenant; switching happens
  on the installation's shared address.
- A Keycloak upgrade means copying the new upstream `template.ftl` and putting the SupportX block
  back (a test checks the block).
- Each custom domain must be a valid redirect URI of the console and portal clients (realm files
  never carry UI origins). The e2e setup registers the dev addresses for its run; production
  registration comes with certificate provisioning (open).

## Certificates and routes for custom domains (decided, D-093)

Decided by the product owner on 2026-10-27 (option (a) of the WP-017 plan question):

- A **separate domain worker** creates certificates and routes for verified custom domains. It
  acts on the outbox's domain events and runs with **its own minimal service account**, allowed
  only certificates and their secrets in its own namespace. The API never gets those rights.
- **On-prem** uses a certificate the tenant uploads (built in WP-017) or the customer's own load
  balancer in front of SupportX.
- **Automatic ACME certificates** only where the server has internet (SaaS, later), and only
  through that worker.
- **An air-gapped installation never tries to reach the internet** for certificates: no ACME
  attempt, no lookup. A verified domain there shows "certificate not managed here" until a
  certificate is uploaded.

Until the worker is built (with the SaaS cell, WP-014d), `domain_certificates_managed` stays off
everywhere and the uploaded certificate is the only way.
