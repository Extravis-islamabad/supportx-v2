import { createHmac } from 'node:crypto';

import { expect, test, type Page } from '@playwright/test';

import { OTHER_TENANT_ID } from '../realtime';
import { centrifugoTokenSecret, CONSOLE_URL } from '../stack';
import { deleteE2eRoles, signInAs } from './helpers';

/**
 * Realtime attacks against the real gateway (WP-011, architecture.md §8.2), from Node with raw
 * WebSocket clients through the same origin the browser uses. Every attempt must be refused.
 */

// Same origin as the console: the Vite proxy in dev, the gateway in the k3d cluster.
const WS_URL = `${CONSOLE_URL.replace(/^http/, 'ws')}/connection/websocket`;

interface Reply {
  id?: number;
  error?: { code: number; message: string };
  connect?: unknown;
  subscribe?: unknown;
  push?: { channel?: string; disconnect?: { code: number }; pub?: { data: unknown } };
}

/** A raw Centrifugo client speaking the JSON protocol. */
class RawClient {
  private socket: WebSocket;
  private next = 1;
  private waiting = new Map<number, (reply: Reply) => void>();
  readonly pushes: { at: number; push: NonNullable<Reply['push']> }[] = [];
  closedAt: number | null = null;
  closeCode: number | null = null;
  private opened: Promise<void>;

  constructor() {
    this.socket = new WebSocket(WS_URL);
    this.opened = new Promise((resolve, reject) => {
      this.socket.onopen = () => {
        resolve();
      };
      this.socket.onerror = () => {
        reject(new Error('websocket error'));
      };
    });
    this.socket.onmessage = (event) => {
      for (const line of String(event.data).split('\n').filter(Boolean)) {
        const reply = JSON.parse(line) as Reply;
        if (reply.id !== undefined) this.waiting.get(reply.id)?.(reply);
        else if (reply.push !== undefined) this.pushes.push({ at: Date.now(), push: reply.push });
        else this.socket.send('{}'); // ping → pong
      }
    };
    this.socket.onclose = (event) => {
      this.closedAt = Date.now();
      this.closeCode = event.code;
    };
  }

  async send(command: Record<string, unknown>): Promise<Reply> {
    await this.opened;
    const id = this.next++;
    const answer = new Promise<Reply>((resolve) => {
      this.waiting.set(id, resolve);
      setTimeout(() => {
        resolve({ id, error: { code: -1, message: 'no reply (closed)' } });
      }, 3_000);
    });
    this.socket.send(JSON.stringify({ id, ...command }));
    return answer;
  }

  connect(token: string): Promise<Reply> {
    return this.send({ connect: { token } });
  }

  subscribe(channel: string, token: string): Promise<Reply> {
    return this.send({ subscribe: { channel, token } });
  }

  close(): void {
    this.socket.close();
  }
}

function b64(value: string | Buffer): string {
  return Buffer.from(value).toString('base64url');
}

function sign(claims: Record<string, unknown>, secret: string): string {
  const head = b64(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const body = b64(JSON.stringify(claims));
  const signature = createHmac('sha256', secret).update(`${head}.${body}`).digest();
  return `${head}.${body}.${b64(signature)}`;
}

async function api(page: Page) {
  const me = (await (await page.request.get('/api/v1/auth/me')).json()) as {
    csrf_token: string;
    user: { id: string };
    tenant: { id: string };
  };
  const headers = { 'X-CSRF-Token': me.csrf_token };
  return {
    me,
    post: (path: string, data?: unknown) =>
      page.request.post(`/api/v1${path}`, { headers, ...(data === undefined ? {} : { data }) }),
    put: (path: string) => page.request.put(`/api/v1${path}`, { headers }),
    del: (path: string) => page.request.delete(`/api/v1${path}`, { headers }),
    token: async (channel?: string): Promise<{ status: number; token?: string; code?: string }> => {
      const response =
        channel === undefined
          ? await page.request.post('/api/v1/realtime/connection-token', { headers })
          : await page.request.post('/api/v1/realtime/subscription-token', {
              headers,
              data: { channel },
            });
      const body = (await response.json()) as { token?: string; code?: string };
      return { status: response.status(), ...body };
    },
  };
}

test('forged and expired connection tokens are refused by the gateway', async ({ page }) => {
  await signInAs(page, 'limited');
  const { me } = await api(page);
  const claims = {
    sub: `${me.tenant.id}:${me.user.id}`,
    aud: 'supportx-realtime',
    iss: 'supportx-api',
    iat: Math.floor(Date.now() / 1000),
    exp: Math.floor(Date.now() / 1000) + 600,
  };
  const forged = new RawClient();
  const reply = await forged.connect(sign(claims, 'not-the-secret-not-the-secret-123'));
  expect(reply.connect).toBeUndefined(); // refused (invalid token: the gateway closes)
  forged.close();

  const secret = centrifugoTokenSecret();
  const expired = new RawClient();
  const old = { ...claims, iat: claims.iat - 3600, exp: claims.iat - 60 };
  const expiredReply = await expired.connect(sign(old, secret));
  expect(expiredReply.connect).toBeUndefined();
  expect(expiredReply.error?.code).toBe(109); // token expired
  expired.close();
});

test('a valid connection cannot join channels it has no token for', async ({ page }) => {
  await signInAs(page, 'limited');
  const client = await api(page);
  const t = client.me.tenant.id;
  const own = `t:${t}:user:${client.me.user.id}`;
  const raw = new RawClient();
  const connection = await client.token();
  expect((await raw.connect(connection.token ?? '')).connect).toBeDefined();

  // A token for its own channel does not open another tenant's or another user's channel.
  const ownToken = (await client.token(own)).token ?? '';
  for (const channel of [`t:${OTHER_TENANT_ID}:broadcast`, `t:${t}:user:${crypto.randomUUID()}`]) {
    const reply = await raw.subscribe(channel, ownToken);
    expect(reply.subscribe, channel).toBeUndefined();
  }
  // No token at all: refused too.
  expect((await raw.subscribe(`t:${t}:broadcast`, '')).subscribe).toBeUndefined();

  // And the API will not sign tokens for them.
  for (const channel of [
    `t:${OTHER_TENANT_ID}:broadcast`,
    `t:${OTHER_TENANT_ID}:queue:users`,
    `t:${t}:queue:users`, // requesters do not hold users.view
    `t:${t}:users:${crypto.randomUUID()}`,
  ]) {
    const refused = await client.token(channel);
    expect([refused.status, refused.code], channel).toEqual([403, 'realtime_channel_denied']);
  }
  raw.close();
});

test('a role change cuts the live connection within a second and stops rejoining', async ({
  browser,
}) => {
  const adminContext = await browser.newContext();
  const userContext = await browser.newContext();
  const adminPage = await adminContext.newPage();
  const userPage = await userContext.newPage();
  await signInAs(adminPage, 'admin', '/');
  await signInAs(userPage, 'limited', '/');
  const admin = await api(adminPage);
  const user = await api(userPage);
  const t = user.me.tenant.id;
  const users = `t:${t}:queue:users`;
  await deleteE2eRoles(adminPage);
  const role = await admin.post('/roles', {
    name: `E2E realtime ${String(Date.now())}`,
    permissions: [{ permission: 'users.view', scope: 'all' }],
  });
  expect(role.status()).toBe(201);
  const roleId = ((await role.json()) as { id: string }).id;
  const raw = new RawClient();
  try {
    expect((await raw.connect((await user.token()).token ?? '')).connect).toBeDefined();

    // Granting the role: the user's connection is cut (code 4000) so it rejoins with new rights.
    const granted = await admin.put(`/users/${user.me.user.id}/roles/${roleId}`);
    expect(granted.status()).toBe(204);
    const grantedAt = Date.now();
    await expect
      .poll(() => raw.closedAt ?? raw.pushes.find((p) => p.push.disconnect)?.at ?? null, {
        timeout: 3_000,
      })
      .not.toBeNull();
    const cut = (raw.pushes.find((p) => p.push.disconnect)?.at ?? raw.closedAt ?? 0) - grantedAt;
    console.log(`revocation after grant: ${String(cut)} ms`);
    expect(cut).toBeLessThan(1_000);

    // Rejoin with the new rights: the users list is allowed now.
    const again = new RawClient();
    expect((await again.connect((await user.token()).token ?? '')).connect).toBeDefined();
    const listToken = await user.token(users);
    expect(listToken.status).toBe(200);
    expect((await again.subscribe(users, listToken.token ?? '')).subscribe).toBeDefined();

    // Removing it: cut again within a second, and the list token is refused from then on.
    const removed = await admin.del(`/users/${user.me.user.id}/roles/${roleId}`);
    expect(removed.status()).toBe(204);
    const removedAt = Date.now();
    await expect
      .poll(() => again.closedAt ?? again.pushes.find((p) => p.push.disconnect)?.at ?? null, {
        timeout: 3_000,
      })
      .not.toBeNull();
    const cutAgain =
      (again.pushes.find((p) => p.push.disconnect)?.at ?? again.closedAt ?? 0) - removedAt;
    console.log(`revocation after removal: ${String(cutAgain)} ms`);
    expect(cutAgain).toBeLessThan(1_000);
    expect(await user.token(users)).toMatchObject({ status: 403, code: 'realtime_channel_denied' });
    again.close();
  } finally {
    raw.close();
    await deleteE2eRoles(adminPage);
    await adminContext.close();
    await userContext.close();
  }
});
