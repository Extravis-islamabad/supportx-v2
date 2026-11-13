import { useEffect, useState } from 'react';

// Shared by the portal's no-sign-in link pages (the approval link, D-132; stopping mails to an
// address kept informed, WP-046a S6): lane B's rules for public links.

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
