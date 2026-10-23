import { api, call } from './client';
import type { components } from './schema';

export type RealtimeToken = components['schemas']['RealtimeToken'];

/**
 * Realtime tokens (WP-011, architecture.md §8.2). The realtime client asks for these itself, again
 * before they expire; a refusal (401/403) means the session or the permission is gone.
 */
export async function fetchConnectionToken(): Promise<string> {
  return (await call(api.POST('/api/v1/realtime/connection-token'))).token;
}

/** Signed only if the policy layer lets the user see what `channel` carries. */
export async function fetchSubscriptionToken(channel: string): Promise<string> {
  return (await call(api.POST('/api/v1/realtime/subscription-token', { body: { channel } }))).token;
}

/** The channels to join to follow list `name` live (one per audience the user belongs to). */
export async function fetchListChannels(name: string): Promise<string[]> {
  const found = await call(
    api.GET('/api/v1/realtime/lists/{name}', { params: { path: { name } } }),
  );
  return found.channels;
}
