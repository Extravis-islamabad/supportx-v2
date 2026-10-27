# Branding

How SupportX shows its own brand (logo, colours, favicons) and how WP-017 will replace it per
tenant. Decision: D-078.

## One source

| What | Where | Used by |
|---|---|---|
| Source logo (gradient headset icon, black "SUPPORT", gradient X; transparent) | `docs/brand/supportx-logo-dark-text.png` | `make brand-assets` |
| Colours | `frontend/packages/ui/src/brand/palette.json` | UI theme (`theme.ts`), web manifest, Keycloak login theme |
| Logos at UI size (dark text, white text, one colour; icon in colour and one colour) | `frontend/packages/ui/src/brand/assets/` | `BrandLogo`, the pre-load splash in each `index.html` |
| Favicons (`favicon.ico` 16/32/48, 180 px Apple touch icon, 192 and 512 px app icons) and `site.webmanifest` | `frontend/packages/ui/src/brand/public/` | both apps (Vite `publicDir`; served by the web image's nginx) |
| Keycloak login theme `supportx` (keycloak.v2 + logo, favicon, colours) | `deploy/helm/supportx/files/keycloak/themes/supportx/` | Compose (mounted) and Helm (ConfigMap `<release>-keycloak-theme`) |
| Full-size white-text logo, 512 px icon, `preview.png` | `docs/brand/` | people (marketing, checks) |

`frontend/packages/ui/src/brand/index.ts` is the only code that imports the files:
`SUPPORTX_LOGOS` and `SUPPORTX_COLOURS` feed `DEFAULT_BRANDING` (theme.ts), and everything else
reads the brand through `useAppearance().branding`. WP-017 passes a tenant's `Branding` to
`AppearanceProvider` and every surface follows. Nothing else changes.

```ts
interface Branding {
  colorPrimary: string;               // seed of every primary shade; white text on it >= 4.5:1
  gradient: readonly [string, string]; // decorative: header accent, portal welcome band
  logos: BrandLogos;                   // full (required), fullOnDark, fullHighContrast, icon, iconHighContrast
}
```

A tenant that uploads one logo gets it everywhere. `logoFor` falls back to `full`, and the narrow
sidebar shows the short name when there is no icon.

## Generating the assets

`make brand-assets` runs `backend/tooling/brand_assets.py`. It uses only the Python standard
library: no image library is on the approved list, and the work needs only PNG decoding,
area-average scaling (premultiplied alpha, so no dark fringes), recolouring, and PNG/ICO
encoding. Steps:

1. Trim the source, then split the icon from the wordmark at the first wide transparent gap.
2. Make the white-text logo by recolouring near-neutral pixels (the black text) to white; the
   gradient stays. Make the high-contrast logo and icon by setting every pixel to black and
   keeping its alpha.
3. Write the files listed above, then `preview.png` with every asset on white and on #141414
   (Ant Design's dark background) for a visual check.
4. Sample the gradient ends from the icon, check every colour pair the palette makes, and exit 1
   if one fails or if `palette.json`'s recorded sample no longer matches the logo.

`make lint` runs `--check`. It fails when the Keycloak CSS or the manifest is stale against
`palette.json`, or when a palette colour falls below AA. Rerun `make brand-assets` after
replacing the logo or editing the palette, and commit the outputs.

## Colours (WCAG 2.1)

Sampled from the logo: **#6666ec** (blue-violet end) to **#951ab6** (purple end).

| Token | Value | Why | Contrast |
|---|---|---|---|
| Primary (light and dark) | **#7e40d1** | gradient midpoint; #6666ec alone is 4.49:1 with white (fails AA) | white text 5.93:1; as links on white 5.93:1 |
| Hover / pressed (light and dark) | #6f38b8 / #6533a7 | Ant Design lightens on hover by default; darkening keeps white text above AA | white text 7.16:1 / 8.12:1 |
| Links and selected text, dark mode | #bea0e8 (primary lightened 50%) | a deep purple is unreadable as text on dark | 8.23:1 on #141414, 7.36:1 on #1f1f1f |
| Primary and links, high contrast | #522a88 (primary darkened 35%) | AAA target | 10.27:1 with white |
| Gradient | **#6060de → #951ab6** | the logo's ends, start darkened 6% | white text at least 4.97:1 anywhere along it |

Links use the brand colour in every mode. Ant Design's default link blue (#1677ff) is 4.1:1 on
white, below AA. The logo itself is exempt from contrast rules (WCAG 1.4.3 "logotypes"). Even so,
each theme shows the version that reads best: dark text on light, white text on dark, all black
in high contrast. In dark mode the purple end of the icon is 2.7:1 on #141414; it is decoration,
next to the white wordmark.

The same rules are tested twice: the Python checks (`Palette.checks`) and
`frontend/packages/ui/src/brand.test.tsx` (on Ant Design's computed tokens).

## Where the brand appears

| Surface | What | Notes |
|---|---|---|
| Console top bar (top layout) | full logo, 28 px | `AppShell` |
| Console sidebar, wide | full logo | |
| Console sidebar, compact or collapsed | icon, 32 px | |
| Header (console and portal) | 3 px brand-gradient accent along the top edge | solid black in high contrast |
| Portal header | full logo and the portal's name | `PortalLayout` |
| Portal home | welcome band in the gradient, white heading | black-bordered plain band in high contrast |
| Favicons, home-screen icons, `theme-color` | all sizes | `index.html` of both apps |
| Pre-load splash | logo while the first script loads | `<picture>` follows the OS dark and contrast settings |
| Session check / redirect, sign-in error, session error, crash page | logo above the message | `BrandedPage` |
| About dialog (user menu › About SupportX) | logo, app name, server version (`GET /api/v1/health`), "Made by Extravis" | en/ar/ur |
| Keycloak login | logo per mode (light, dark through keycloak.v2's dark class, `prefers-contrast: more`), primary buttons and links, gradient bar on the card, favicon | theme `supportx`, realm `loginTheme` |
| E-mail templates | none yet | WP-023/WP-024 take the logo from the same files |

## Keycloak

The realm files set `"loginTheme": "supportx"`, but Keycloak imports a realm only on its first
start. Realms that existed before the branding work get the theme from an upgrade step,
`tooling/keycloak_theme.py`:

| Realm's login theme | What the step does |
|---|---|
| none (empty) | sets `supportx` |
| anything else (Keycloak's own chosen on purpose, a tenant's custom theme, already `supportx`) | leaves it as it is: never overwritten |
| realm missing | nothing |

- **Kubernetes:** a Job per Helm revision, `<release>-keycloak-theme-<revision>`
  (`keycloak.setLoginTheme`, default on). It signs in as the installation's bootstrap admin
  (secret key `keycloak-admin-password`) and retries while Keycloak starts. Nothing waits for it,
  so it never holds up a deploy. If an operator has replaced the bootstrap admin, it logs
  `SKIPPED` and exits 0; set the theme by hand once in that case. If Keycloak never answers, it
  fails visibly.
- **Compose:** `make keycloak-theme`, with the admin from `deploy/compose/.env`.
- **By hand:** in the admin console, Realm settings › Themes › Login theme = `supportx`, or
  `kcadm.sh update realms/supportx -s loginTheme=supportx`.

Compose mounts the theme folder; `start-dev` does not cache themes, so CSS edits show at once.
The chart ships the theme as a ConfigMap. Its keys are the file paths with `/` written as `__`,
and the volume's `items` put each file back at its path under `/opt/keycloak/themes/supportx`.
The theme's `template.ftl` is upstream keycloak.v2 (26.8.1) plus one block marked `SupportX`: it
links the tenant's stylesheet when Keycloak knows the organization (next section). On a Keycloak
upgrade, copy the new upstream file and put the block back; `test_keycloak_theme.py` checks it.

## Accessibility checks

`frontend/e2e/tests/branding.spec.ts` runs axe on these pages:

- the login page in light, dark, high contrast and Arabic RTL;
- the console with its logo and the About dialog in light, dark and high contrast;
- the portal home and its About dialog in light, dark and high contrast, for an Arabic
  (right-to-left) requester.

It also checks that favicons and the manifest are served and that each theme loads the right
logo file. `layouts.spec.ts` keeps covering the three console layouts in every theme and in
Arabic.

## Per tenant (WP-017, ADR-031, D-090)

A tenant replaces the default from Admin › Branding (`branding.manage`). Nothing else changes:
the apps pass the tenant's `Branding` to the theme, as above.

| Part | Where | Notes |
|---|---|---|
| Colours, names, welcome text | `tenant_branding` (organization module) | Empty = the default. Names per language, English the fallback |
| Uploads (logo, dark logo, icon) | files service, owner `branding` | Scanned like any file; PNG, JPEG, WebP or ICO, never SVG |
| Variants every surface shows | `branding_assets`, made with Pillow on save | `logo.png`, `logo-dark.png`, `logo-high-contrast.png`, `icon.png`, `icon-high-contrast.png`, `favicon.ico`, `apple-touch-icon.png`, `icon-192.png`, `icon-512.png` |
| Public routes | `/api/v1/public/branding` (the address's brand), `/{slug}/login.css`, `/{slug}/{asset}?v=` | Versioned URLs cached a year; others five minutes |
| Rules | `organization/domain/branding.py` | The colour maths of this page, shared with `make brand-assets` |

**Colours.** The server checks every pair the brand makes (table above). A failing primary or
gradient is refused (`brand_colour_contrast`) with the failing checks and the nearest darker
shade that passes; the screen checks as you choose and offers that shade in one click. The
preview draws the console header, the portal welcome band and the sign-in card with the real
theme builder in light, dark and high contrast before anything is saved.

**Logos.** A cut-out logo (transparent background) also gives the dark version (near-black
neutral pixels turned white, as for SupportX's own) and the high-contrast one (all black). An
opaque logo is shown as it is in every mode. Without an icon, favicons are made from the logo.

**Where it shows.**
- Console and portal: `AddressBranding` (before sign-in, from the address) and `TenantBranding`
  (signed in; refetched on `organization.branding_changed`, so open screens follow live). The tab
  icon follows too. The portal shows the portal name and the welcome text in its band.
- Sign-in page: the theme links `<supportxBrandingUrl>/<org alias>/login.css` when Keycloak
  knows the organization. `supportxBrandingUrl` is the theme property
  `${env.SUPPORTX_BRANDING_URL:/api/v1/public/branding}` (one host in Kubernetes; Compose points
  it at the console dev server). Keycloak knows the organization on a tenant's own address
  (SupportX asks for `organization:<alias>`) and, on the shared address, once the e-mail's domain
  names it. The organization alias is the tenant slug.
- E-mails: `organization.email_branding()` gives the absolute logo URL, colours and the product
  name in a language; `header_html()` is the escaped header. The WP-039 mail foundation renders
  with them (D-089).

## Addresses (WP-017, REQ-SEC-004)

- **Subdomain:** `<slug>.<tenant_base_domain>` when `SUPPORTX_TENANT_BASE_DOMAIN` is set (dev:
  `localhost`, so `demo.localhost:5173` and `other.localhost:5173` are the seeded tenants).
- **Custom domain:** added on the branding screen, pointed here (CNAME), then checked: SupportX
  fetches `http://<host>/api/v1/public/domain-check/<token>` and expects this installation's
  HMAC of the token (keyed with the session secret). Only verified domains resolve; a host
  belongs to one tenant. The fetch refuses loopback, link-local, multicast and reserved
  addresses, follows no redirects and reads at most 256 bytes.
- **Certificates:** a single-server installation may upload its own (key matches, names the host,
  valid now; the key is encrypted with the tenant's data key). Automatic certificates need the
  platform (`SUPPORTX_DOMAIN_CERTIFICATES_MANAGED`; who provisions in Kubernetes is open,
  ADR-031). Each custom domain must also be a redirect URI of the console and portal clients.
- **Sign-in:** on a tenant's address the BFF asks Keycloak for that organization only and keeps
  the callback there. A person who is not a member gets `no_organization`, on that address.
