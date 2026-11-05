import * as Crypto from 'expo-crypto';
import * as WebBrowser from 'expo-web-browser';

import { api } from '@supportx/api-client';

// The mobile sign-in (ADR-042): the system browser runs the server's usual sign-in and comes
// back to the app with a one-time code, which is exchanged for the session ID. Keycloak's tokens
// never reach the phone.
export const APP_RETURN = 'supportx://auth';

export type SignInResult =
  | { ok: true; sessionId: string }
  | { ok: false; reason: 'cancelled' | 'unreachable' | 'error'; code?: string };

/** base64url without padding (RFC 4648 §5), what the server's challenge check expects. */
export function base64Url(base64: string): string {
  return base64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function bytesToBase64(bytes: Uint8Array): string {
  let binary = '';
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

/** A random verifier (32 bytes, 43 characters) and its S256 challenge. */
export async function newChallenge(): Promise<{ verifier: string; challenge: string }> {
  const verifier = base64Url(bytesToBase64(Crypto.getRandomBytes(32)));
  const digest = await Crypto.digestStringAsync(Crypto.CryptoDigestAlgorithm.SHA256, verifier, {
    encoding: Crypto.CryptoEncoding.BASE64,
  });
  return { verifier, challenge: base64Url(digest) };
}

/** Where the browser starts: the console client; requesters are moved to the portal by the server. */
export function loginUrl(origin: string, challenge: string): string {
  const query = new URLSearchParams({ app: 'console', returnTo: '/', mobile_challenge: challenge });
  return `${origin}/api/v1/auth/login?${query.toString()}`;
}

/** The `handoff` or `auth_error` the browser came back with. */
export function readReturn(url: string): { handoff?: string; error?: string } {
  const query = url.includes('?') ? url.slice(url.indexOf('?') + 1) : '';
  const params = new URLSearchParams(query);
  return {
    handoff: params.get('handoff') ?? undefined,
    error: params.get('auth_error') ?? undefined,
  };
}

export async function signIn(origin: string): Promise<SignInResult> {
  const { verifier, challenge } = await newChallenge();
  let result: WebBrowser.WebBrowserAuthSessionResult;
  try {
    result = await WebBrowser.openAuthSessionAsync(loginUrl(origin, challenge), APP_RETURN);
  } catch {
    return { ok: false, reason: 'unreachable' };
  }
  if (result.type !== 'success') return { ok: false, reason: 'cancelled' };
  const { handoff, error } = readReturn(result.url);
  if (error !== undefined) return { ok: false, reason: 'error', code: error };
  if (handoff === undefined) return { ok: false, reason: 'error' };
  try {
    const { data, error: problem } = await api.POST('/api/v1/auth/mobile/exchange', {
      body: { handoff, verifier },
    });
    if (data === undefined) {
      const code = (problem as { code?: unknown } | undefined)?.code;
      return { ok: false, reason: 'error', code: typeof code === 'string' ? code : undefined };
    }
    return { ok: true, sessionId: data.session_id };
  } catch {
    return { ok: false, reason: 'unreachable' };
  }
}
