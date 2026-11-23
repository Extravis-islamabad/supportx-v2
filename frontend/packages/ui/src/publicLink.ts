import { useEffect, useState } from 'react';

// Shared by the no-sign-in link pages (the approval link, D-132; stopping mails to an address
// kept informed, WP-046a S6; a copied invite link, REQ-SEC-021, in console and portal): lane B's
// rules for public links. Moved from the portal unchanged (lane C, WP-057 S2b-2).

/** The token from the URL fragment: read without side effects, then off the address bar. */
export function useFragmentToken(): string | undefined {
  const [token] = useState(() => {
    const found = window.location.hash.replace(/^#/, '');
    return found === '' ? undefined : found;
  });
  useEffect(() => {
    // No referrer leaves this page (lane B's review), before its first request; the token is in
    // the fragment, which a referrer never carries anyway.
    let meta = document.querySelector<HTMLMetaElement>('meta[name="referrer"]');
    if (meta === null) {
      meta = document.createElement('meta');
      meta.name = 'referrer';
      document.head.appendChild(meta);
    }
    meta.content = 'no-referrer';
    if (window.location.hash !== '') {
      window.history.replaceState(null, '', window.location.pathname + window.location.search);
    }
  }, []);
  return token;
}

/** The link's `?t=`: the tenant's slug where the address names none (never a secret). */
export function linkTenant(): string | null {
  const slug = new URLSearchParams(window.location.search).get('t');
  return slug === '' ? null : slug; // an empty ?t= is none
}

export const INVITE_PATH = '/invite';

/** The invite page wherever the app is served (`/invite`, `/portal/invite`; REQ-SEC-021). */
export function isInvitePage(pathname: string): boolean {
  return pathname.replace(/\/$/, '').endsWith(INVITE_PATH);
}
