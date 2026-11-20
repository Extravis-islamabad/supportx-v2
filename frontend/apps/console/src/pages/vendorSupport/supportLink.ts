export const SUPPORT_START_PATH = '/vendor-support/start';

/**
 * The link's token, read once when this module loads and taken out of the address bar at once
 * (lane B (1), WP-057 S4c-3): before React renders, before any request, so neither the history,
 * a Referer nor a later script sees it. A token in the query string is ignored (a mail scanner
 * or a log could hold one); only the fragment counts, and only on this page.
 */
function captureToken(): string | null {
  if (typeof window === 'undefined' || window.location.pathname !== SUPPORT_START_PATH) {
    return null;
  }
  const raw = window.location.hash.replace(/^#/, '');
  if (raw !== '') {
    window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`);
  }
  // No Referer leaves this page either way (lane B (2)), whatever the server's headers say.
  const meta = document.createElement('meta');
  meta.name = 'referrer';
  meta.content = 'no-referrer';
  document.head.appendChild(meta);
  return raw === '' ? null : decodeURIComponent(raw);
}

let captured: string | null = captureToken();

/** The token the page opened with (read again by a re-render: StrictMode calls it twice). */
export function capturedToken(): string | null {
  return captured;
}

/** The page holds the token now: the module keeps no copy. */
export function forgetCapturedToken(): void {
  captured = null;
}

/** For tests: read the address again (a fresh page load). */
export function recaptureForTests(): void {
  captured = captureToken();
}

/** The tenant's slug, where the link names it (`?t=`): not a secret, it only routes the POST. */
export function tenantSlug(): string | null {
  return new URLSearchParams(window.location.search).get('t');
}
