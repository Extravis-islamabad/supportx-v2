import { confirmUrl, type ReauthOutcome } from '@supportx/api-client';

/**
 * Confirm who you are in a pop-up (REQ-SEC-027; WP-057 S2a).
 *
 * The API answers with `Cross-Origin-Opener-Policy: same-origin`, and the pop-up also passes
 * through Keycloak on another origin. Either step moves the pop-up to its own browsing-context
 * group: `window.opener` is null there and `popup.closed` reads true here, so neither can carry
 * the answer. The pop-up's /confirmed page announces it on a BroadcastChannel instead. The browser
 * keeps that channel to this exact origin, and the message must carry this attempt's random id
 * (lane B's condition A6, as agreed 2026-11-13). The answer is never proof of anything: it only
 * makes the client retry once, and the server checks the session's fresh sign-in again.
 */

export const CONFIRMED_PATH = '/confirmed';
export const REAUTH_CHANNEL = 'supportx-reauth';
export const REAUTH_MESSAGE = 'supportx.reauth';
/** The server's pending confirmation lives as long (confirm.py CONFIRM_TTL). */
export const CONFIRM_TTL_MS = 5 * 60_000;

export type ConfirmedStatus = 'ok' | 'failed' | 'unavailable';
const STATUSES: readonly ConfirmedStatus[] = ['ok', 'failed', 'unavailable'];
const OUTCOME: Record<ConfirmedStatus, ReauthOutcome> = {
  ok: 'confirmed',
  failed: 'failed',
  unavailable: 'unavailable',
};
const ATTEMPT = /^[A-Za-z0-9_-]{16,64}$/;

export interface ConfirmedMessage {
  type: typeof REAUTH_MESSAGE;
  attempt: string;
  status: ConfirmedStatus;
}

/** The /confirmed page, wherever the UI is served (`/confirmed`, `/portal/confirmed`). */
export function isConfirmedPage(pathname: string): boolean {
  return pathname.replace(/\/$/, '').endsWith(CONFIRMED_PATH);
}

export function isAttempt(value: unknown): value is string {
  return typeof value === 'string' && ATTEMPT.test(value);
}

export function confirmedStatus(value: string | null): ConfirmedStatus {
  return STATUSES.find((status) => status === value) ?? 'failed';
}

/**
 * A same-origin path to go back to, else `/` (the server's safe_return_to, mirrored): the
 * /confirmed page's link must never lead off this site (lane B's condition 2).
 */
export function safeReturnTo(value: string | null, origin = window.location.origin): string {
  if (!value?.startsWith('/')) return '/';
  let decoded: string;
  try {
    decoded = decodeURIComponent(value);
  } catch {
    return '/';
  }
  for (const text of [value, decoded]) {
    if (text.startsWith('//') || text.includes('\\')) return '/';
    // eslint-disable-next-line no-control-regex -- intentional: refuse ASCII control characters
    if (/[\u0000-\u001f\u007f]/.test(text)) return '/';
  }
  let url: URL;
  try {
    url = new URL(value, origin);
  } catch {
    return '/';
  }
  if (url.origin !== origin) return '/';
  return `${url.pathname}${url.search}${url.hash}`;
}

/** The outcome in a message from /confirmed, or null for anything else (lane B's condition 4). */
export function readConfirmedMessage(data: unknown, attempt: string): ReauthOutcome | null {
  if (typeof data !== 'object' || data === null || Array.isArray(data)) return null;
  const keys = Object.keys(data).sort();
  if (keys.join(',') !== 'attempt,status,type') return null;
  const message = data as Record<string, unknown>;
  if (message.type !== REAUTH_MESSAGE || message.attempt !== attempt) return null;
  const status = STATUSES.find((known) => known === message.status);
  return status === undefined ? null : OUTCOME[status];
}

type Channel = Pick<BroadcastChannel, 'postMessage' | 'close'> & {
  onmessage: ((event: MessageEvent) => void) | null;
};
export type ChannelFactory = (name: string) => Channel;
const browserChannel: ChannelFactory = (name) => new BroadcastChannel(name);

/** On the /confirmed page: tell the opener (the status and its attempt id, nothing else). */
export function announceConfirmed(
  status: ConfirmedStatus,
  attempt: string,
  channel: ChannelFactory = browserChannel,
): void {
  const open = channel(REAUTH_CHANNEL);
  const message: ConfirmedMessage = { type: REAUTH_MESSAGE, attempt, status };
  open.postMessage(message);
  open.close();
}

export interface ConfirmationDeps {
  open: (url: string) => unknown;
  redirect: (url: string) => void;
  channel: ChannelFactory;
  attemptId: () => string;
  here: () => string;
  ttlMs: number;
}

const browserDeps: ConfirmationDeps = {
  open: (url) => window.open(url, 'supportx-confirm', 'popup,width=520,height=720'),
  redirect: (url) => {
    window.location.assign(url);
  },
  channel: browserChannel,
  attemptId: () => crypto.randomUUID(),
  here: () => `${window.location.pathname}${window.location.search}${window.location.hash}`,
  ttlMs: CONFIRM_TTL_MS,
};

export interface Confirmation {
  /** Settles once: the pop-up's answer, Cancel, or the time limit ('failed'). */
  outcome: Promise<ReauthOutcome>;
  cancel: () => void;
}

/**
 * Open the pop-up and wait for its answer. Call from a click (a pop-up blocker allows that).
 * A blocked pop-up becomes a full-page confirmation that comes back here; that page never answers,
 * so null is returned and the person repeats the action once back.
 */
export function startConfirmation(overrides: Partial<ConfirmationDeps> = {}): Confirmation | null {
  const deps = { ...browserDeps, ...overrides };
  const attempt = deps.attemptId();
  const here = deps.here();
  if (deps.open(confirmUrl(here, attempt)) === null) {
    deps.redirect(confirmUrl(here));
    return null;
  }
  const channel = deps.channel(REAUTH_CHANNEL);
  let settle: (outcome: ReauthOutcome) => void = () => undefined;
  const outcome = new Promise<ReauthOutcome>((resolve) => {
    let done = false;
    const timer = setTimeout(() => {
      finish('failed');
    }, deps.ttlMs);
    function finish(result: ReauthOutcome) {
      if (done) return;
      done = true;
      clearTimeout(timer);
      channel.onmessage = null;
      channel.close(); // after the first match, Cancel or the time limit (lane B's condition 4)
      resolve(result);
    }
    settle = finish;
    channel.onmessage = (event: MessageEvent) => {
      const answer = readConfirmedMessage(event.data, attempt);
      if (answer !== null) finish(answer);
    };
  });
  return {
    outcome,
    cancel: () => {
      settle('failed');
    },
  };
}
