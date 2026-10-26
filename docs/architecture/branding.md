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

The realm files set `"loginTheme": "supportx"`. The realm is imported only on first start, so an
installation whose realm already exists keeps Keycloak's own theme until an administrator sets it.
In the admin console: Realm settings › Themes › Login theme = `supportx`. Or with kcadm:

```sh
kcadm.sh update realms/supportx -s loginTheme=supportx
```

Compose mounts the theme folder; `start-dev` does not cache themes, so CSS edits show at once.
The chart ships the theme as a ConfigMap. Its keys are the file paths with `/` written as `__`,
and the volume's `items` put each file back at its path under `/opt/keycloak/themes/supportx`.
WP-017 adds per-tenant login branding (Keycloak organizations) on top of this theme.

## Accessibility checks

`frontend/e2e/tests/branding.spec.ts` runs axe on these pages:

- the login page in light, dark, high contrast and Arabic RTL;
- the console with its logo and the About dialog in light, dark and high contrast;
- the portal home and its About dialog in light, dark and high contrast, for an Arabic
  (right-to-left) requester.

It also checks that favicons and the manifest are served and that each theme loads the right
logo file. `layouts.spec.ts` keeps covering the three console layouts in every theme and in
Arabic.
