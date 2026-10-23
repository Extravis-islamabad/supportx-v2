import { writeFileSync } from 'node:fs';

import { expect, test } from '@playwright/test';

import { signInAs } from '../tests/helpers';

/**
 * Commit → other screen, 200 times (WP-011 target: p95 < 1 s). One browser saves the user's
 * profile through the API (the save returns after the commit); another browser of the same
 * user follows the profile's record channel, like the profile page does. A change counts as
 * visible when a message for that version (or a later one: bursts merge) arrives there.
 */

const CHANGES = 200;
const SPACING_MS = 100;

interface Arrival {
  version: number;
  at: number;
}

function percentile(sorted: number[], q: number): number {
  return sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))] ?? Number.NaN;
}

test('latency: 200 profile saves reach another browser', async ({ browser }) => {
  const writerContext = await browser.newContext();
  const readerContext = await browser.newContext();
  const writer = await writerContext.newPage();
  const reader = await readerContext.newPage();
  await signInAs(writer, 'tech', '/');
  await signInAs(reader, 'tech', '/');

  const me = (await (await reader.request.get('/api/v1/auth/me')).json()) as {
    csrf_token: string;
    user: { id: string };
    tenant: { id: string };
  };
  const channel = `t:${me.tenant.id}:users:${me.user.id}`;
  const readerHeaders = { 'X-CSRF-Token': me.csrf_token };
  const connection = (await (
    await reader.request.post('/api/v1/realtime/connection-token', { headers: readerHeaders })
  ).json()) as { token: string };
  const subscription = (await (
    await reader.request.post('/api/v1/realtime/subscription-token', {
      headers: readerHeaders,
      data: { channel },
    })
  ).json()) as { token: string };

  // The reader's own browser socket records when each version arrives.
  await reader.evaluate(
    ({ connect, subscribe, name }) =>
      new Promise<void>((resolve, reject) => {
        const w = window as unknown as { arrivals: { version: number; at: number }[] };
        w.arrivals = [];
        const ws = new WebSocket(`${location.origin.replace(/^http/, 'ws')}/connection/websocket`);
        ws.onopen = () => {
          ws.send(
            `${JSON.stringify({ id: 1, connect: { token: connect } })}\n${JSON.stringify({ id: 2, subscribe: { channel: name, token: subscribe } })}`,
          );
        };
        ws.onmessage = (event) => {
          for (const line of String(event.data).split('\n').filter(Boolean)) {
            const reply = JSON.parse(line) as {
              id?: number;
              error?: unknown;
              push?: { pub?: { data?: { version?: number } } };
            };
            if (reply.id === 2) {
              if (reply.error) reject(new Error(JSON.stringify(reply.error)));
              else resolve();
            } else if (reply.push?.pub?.data?.version !== undefined) {
              w.arrivals.push({ version: reply.push.pub.data.version, at: Date.now() });
            } else if (Object.keys(reply).length === 0) {
              ws.send('{}');
            }
          }
        };
        ws.onerror = () => {
          reject(new Error('websocket error'));
        };
      }),
    { connect: connection.token, subscribe: subscription.token, name: channel },
  );

  const writerMe = (await (await writer.request.get('/api/v1/auth/me')).json()) as {
    csrf_token: string;
  };
  const path = `/api/v1/users/${me.user.id}`;
  let version = ((await (await writer.request.get(path)).json()) as { version: number }).version;
  const original = ((await (await writer.request.get(path)).json()) as { signature: string | null })
    .signature;
  const commits: { version: number; at: number }[] = [];
  try {
    for (let n = 0; n < CHANGES; n += 1) {
      const response = await writer.request.patch(path, {
        headers: { 'X-CSRF-Token': writerMe.csrf_token, 'If-Match': `"${String(version)}"` },
        data: { signature: `Latency ${String(n)}` },
      });
      expect(response.status()).toBe(200);
      version = ((await response.json()) as { version: number }).version;
      commits.push({ version, at: Date.now() });
      await writer.waitForTimeout(SPACING_MS);
    }
    await reader.waitForTimeout(2_000);
  } finally {
    await writer.request.patch(path, {
      headers: { 'X-CSRF-Token': writerMe.csrf_token, 'If-Match': `"${String(version)}"` },
      data: { signature: original },
    });
  }

  const arrivals = await reader.evaluate(
    () => (window as unknown as { arrivals: Arrival[] }).arrivals,
  );
  const latencies = commits
    .map((commit) => {
      const seen = arrivals.find((a) => a.version >= commit.version && a.at >= commit.at - 5);
      return seen === undefined ? Number.POSITIVE_INFINITY : seen.at - commit.at;
    })
    .sort((x, y) => x - y);
  const missing = latencies.filter((l) => !Number.isFinite(l)).length;
  const result = {
    changes: CHANGES,
    messages: arrivals.length,
    missing,
    p50_ms: percentile(latencies, 0.5),
    p95_ms: percentile(latencies, 0.95),
    p99_ms: percentile(latencies, 0.99),
    max_ms: latencies[latencies.length - 1 - missing],
  };
  console.log(`latency ${JSON.stringify(result)}`);
  writeFileSync('test-results/perf-latency.json', JSON.stringify(result, null, 2));
  expect(missing).toBe(0);
  expect(result.p95_ms).toBeLessThan(1_000);
  await writerContext.close();
  await readerContext.close();
});
