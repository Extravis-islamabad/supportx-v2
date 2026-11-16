import { api } from '@supportx/api-client';

export type AddressProblem = 'invalid' | 'https_required';

export type ParsedAddress = { ok: true; origin: string } | { ok: false; problem: AddressProblem };

/**
 * The server's origin from what the user typed: "support.example.com" means
 * https://support.example.com, and a path is dropped (the API is always at /api/v1 on the
 * origin, as for the web apps). Plain http is refused outside development builds: the session
 * travels in a cookie header and must never cross the network unencrypted (§11.1).
 */
export function parseServerAddress(input: string, allowHttp: boolean): ParsedAddress {
  const text = input.trim();
  if (text === '') return { ok: false, problem: 'invalid' };
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(text) ? text : `https://${text}`;
  let url: URL;
  try {
    url = new URL(withScheme);
  } catch {
    return { ok: false, problem: 'invalid' };
  }
  if (url.hostname === '' || url.username !== '' || url.password !== '') {
    return { ok: false, problem: 'invalid' };
  }
  if (url.protocol === 'http:' && !allowHttp) return { ok: false, problem: 'https_required' };
  if (url.protocol !== 'https:' && url.protocol !== 'http:') {
    return { ok: false, problem: 'https_required' };
  }
  return { ok: true, origin: url.origin };
}

export type ServerCheck =
  { ok: true; version: string } | { ok: false; problem: 'unreachable' | 'not_supportx' };

/** Asks a server's public health endpoint whether it is a SupportX API, and its version. */
export async function checkServer(origin: string, timeoutMs = 10_000): Promise<ServerCheck> {
  const controller = new AbortController();
  const timer = setTimeout(() => {
    controller.abort();
  }, timeoutMs);
  try {
    // Called without `call()`: it would replace a thrown error with a bare "network" one, and
    // the original is what tells a developer why a reachable server still fails here.
    const { data, response } = await api.GET('/api/v1/health', {
      baseUrl: origin,
      signal: controller.signal,
    });
    // A different service answering on this path is not a SupportX server.
    const health = data as { status?: unknown; version?: unknown } | undefined;
    if (!response.ok || health?.status !== 'ok' || typeof health.version !== 'string') {
      if (__DEV__) console.warn('[server check] not a SupportX answer', response.status, data);
      return { ok: false, problem: 'not_supportx' };
    }
    return { ok: true, version: health.version };
  } catch (error) {
    if (__DEV__) console.warn('[server check] request failed', origin, error);
    return { ok: false, problem: 'unreachable' };
  } finally {
    clearTimeout(timer);
  }
}
