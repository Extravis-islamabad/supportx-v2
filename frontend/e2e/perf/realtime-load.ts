// Realtime load test (WP-011): `pnpm --filter @supportx/e2e perf:load [connections] [changes]`.
//
// Opens N WebSocket connections to the dev stack's Centrifugo, all following the Demo Company
// users list (t:<demo>:queue:users), then commits a burst of real changes (tooling.realtime_burst:
// profile saves of the e2e scroll-fixture users, through the outbox like any save). Measures, per
// connection and change, commit → message received; samples CPU and memory of Centrifugo and the
// fan-out worker; prints and writes test-results/perf-load.json. Dev stack only: the tokens are
// signed with the dev HMAC key from deploy/compose/.env (the gateway is what is under test, not
// the token endpoint, which is rate limited per user). Runs on Node's built-in TypeScript support.
import { execFile, execFileSync, spawn } from 'node:child_process';
import { createHmac, randomUUID } from 'node:crypto';
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { promisify } from 'node:util';

const run = promisify(execFile);
const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = resolve(HERE, '../../..');
const DEMO = '01900000-0000-7000-8000-00000000de30';
const CONNECTIONS = Number(process.argv[2] ?? 2000);
const CHANGES = Number(process.argv[3] ?? 200);
const CHANGE_SPACING_MS = 10;

const env: Record<string, string> = Object.fromEntries(
  readFileSync(resolve(REPO, 'deploy/compose/.env'), 'utf8')
    .split('\n')
    .filter((line) => /^[A-Z_]+=/.test(line))
    .map((line) => [line.slice(0, line.indexOf('=')), line.slice(line.indexOf('=') + 1)]),
);
const SECRET = env.CENTRIFUGO_TOKEN_HMAC_SECRET ?? '';
const URL = `ws://127.0.0.1:${env.CENTRIFUGO_PORT ?? '28000'}/connection/websocket`;
const CHANNEL = `t:${DEMO}:queue:users`;

/** [arrival ms, record IDs, refresh] of one list message. */
type Received = [number, string[], boolean];
interface Client {
  ws: WebSocket;
  messages: Received[];
}
interface Commit {
  id: string;
  committed_ms: number;
}
interface Sample {
  centrifugo_cpu: number;
  centrifugo_mem: string;
  fanout_cpu: number;
  fanout_rss_mb: number;
}
interface Reply {
  id?: number;
  error?: unknown;
  push?: { pub?: { data: { ids?: string[]; refresh?: boolean } } };
}

const b64 = (value: string | Buffer): string => Buffer.from(value).toString('base64url');

function sign(claims: Record<string, unknown>): string {
  const head = b64(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const body = b64(JSON.stringify(claims));
  return `${head}.${body}.${b64(createHmac('sha256', SECRET).update(`${head}.${body}`).digest())}`;
}

function tokens(): { connect: string; subscribe: string } {
  const now = Math.floor(Date.now() / 1000);
  const sub = `${DEMO}:${randomUUID()}`;
  const base = { sub, aud: 'supportx-realtime', iss: 'supportx-api', iat: now, exp: now + 3600 };
  return { connect: sign(base), subscribe: sign({ ...base, channel: CHANNEL }) };
}

/** One client: connect + subscribe; records every list message. */
function client(): Promise<Client> {
  return new Promise((resolveClient, rejectClient) => {
    const ws = new WebSocket(URL);
    const messages: Received[] = [];
    const { connect, subscribe } = tokens();
    const timer = setTimeout(() => {
      rejectClient(new Error('subscribe timeout'));
    }, 30_000);
    ws.onopen = () => {
      ws.send(
        `${JSON.stringify({ id: 1, connect: { token: connect } })}\n${JSON.stringify({ id: 2, subscribe: { channel: CHANNEL, token: subscribe } })}`,
      );
    };
    ws.onmessage = (event: MessageEvent) => {
      for (const line of String(event.data).split('\n')) {
        if (line === '') continue;
        const reply = JSON.parse(line) as Reply;
        if (reply.id === 2) {
          clearTimeout(timer);
          if (reply.error !== undefined) rejectClient(new Error(JSON.stringify(reply.error)));
          else resolveClient({ ws, messages });
        } else if (reply.push?.pub !== undefined) {
          const data = reply.push.pub.data;
          messages.push([Date.now(), data.ids ?? [], data.refresh === true]);
        } else if (line === '{}') {
          ws.send('{}');
        }
      }
    };
    ws.onerror = () => {
      rejectClient(new Error('websocket error'));
    };
  });
}

function percentile(sorted: number[], q: number): number {
  return sorted[Math.min(sorted.length - 1, Math.floor(q * sorted.length))] ?? Number.NaN;
}

async function sampleUntil(samples: Sample[], stop: { done: boolean }): Promise<void> {
  const fanoutPid =
    execFileSync('pgrep', ['-f', 'workers.realtime_fanout'], { encoding: 'utf8' })
      .trim()
      .split('\n')
      .pop() ?? '';
  while (!stop.done) {
    const [docker, ps] = await Promise.all([
      run('docker', [
        'stats',
        '--no-stream',
        '--format',
        '{{.CPUPerc}} {{.MemUsage}}',
        'supportx-dev-centrifugo-1',
      ]).catch(() => ({ stdout: '' })),
      run('ps', ['-o', '%cpu=,rss=', '-p', fanoutPid]).catch(() => ({ stdout: '' })),
    ]);
    const [cpu = '0', mem = ''] = docker.stdout.trim().split(' ');
    const [fanoutCpu = '0', fanoutRss = '0'] = ps.stdout.trim().split(/\s+/);
    samples.push({
      centrifugo_cpu: Number.parseFloat(cpu),
      centrifugo_mem: mem,
      fanout_cpu: Number.parseFloat(fanoutCpu),
      fanout_rss_mb: Math.round(Number(fanoutRss) / 1024),
    });
  }
}

function fixtures(action: 'create' | 'delete'): string {
  return execFileSync('uv', ['run', 'python', '-m', 'tooling.e2e_fixtures', action], {
    cwd: resolve(REPO, 'backend'),
    encoding: 'utf8',
  }).trim();
}

function burst(commits: Commit[]): Promise<void> {
  return new Promise((resolveBurst, rejectBurst) => {
    const child = spawn(
      'uv',
      ['run', 'python', '-m', 'tooling.realtime_burst', String(CHANGES), String(CHANGE_SPACING_MS)],
      { cwd: resolve(REPO, 'backend') },
    );
    let buffered = '';
    child.stdout.on('data', (chunk: Buffer) => {
      buffered += chunk.toString();
      const lines = buffered.split('\n');
      buffered = lines.pop() ?? '';
      for (const line of lines) if (line.trim() !== '') commits.push(JSON.parse(line) as Commit);
    });
    child.on('exit', (code) => {
      if (code === 0) resolveBurst();
      else rejectBurst(new Error(`burst exited with ${String(code)}`));
    });
  });
}

async function main(): Promise<number> {
  console.log(`fixtures: ${fixtures('create')}`);
  const opened = Date.now();
  const clients: Client[] = [];
  for (let start = 0; start < CONNECTIONS; start += 200) {
    const batch = Math.min(200, CONNECTIONS - start);
    clients.push(...(await Promise.all(Array.from({ length: batch }, () => client()))));
  }
  const connectSeconds = (Date.now() - opened) / 1000;
  console.log(`${String(clients.length)} connections subscribed in ${connectSeconds.toFixed(1)} s`);

  const samples: Sample[] = [];
  const stop = { done: false };
  const sampling = sampleUntil(samples, stop);
  const commits: Commit[] = [];
  await burst(commits);
  await new Promise((settle) => setTimeout(settle, 3_000)); // the last windows arrive
  stop.done = true;
  await sampling;

  // Per client and change: the first message after the commit that names it (or says refresh).
  const latencies: number[] = [];
  let missing = 0;
  let messages = 0;
  for (const { messages: received } of clients) {
    messages += received.length;
    for (const change of commits) {
      const hit = received.find(
        ([at, ids, refresh]) =>
          at >= change.committed_ms - 5 && (refresh || ids.includes(change.id)),
      );
      if (hit === undefined) missing += 1;
      else latencies.push(hit[0] - change.committed_ms);
    }
  }
  latencies.sort((a, b) => a - b);
  for (const { ws } of clients) ws.close();
  console.log(`fixtures: ${fixtures('delete')}`);

  const stats = execFileSync('make', ['-s', 'events-stats'], { cwd: REPO, encoding: 'utf8' });
  const peak = (key: 'centrifugo_cpu' | 'fanout_cpu' | 'fanout_rss_mb'): number =>
    Math.max(...samples.map((s) => s[key]));
  const result = {
    connections: clients.length,
    connect_seconds: connectSeconds,
    changes: commits.length,
    messages_per_connection: Math.round(messages / clients.length),
    deliveries: latencies.length,
    missing,
    delivery_ms: {
      p50: Math.round(percentile(latencies, 0.5)),
      p95: Math.round(percentile(latencies, 0.95)),
      p99: Math.round(percentile(latencies, 0.99)),
      max: Math.round(latencies[latencies.length - 1] ?? Number.NaN),
    },
    centrifugo: {
      cpu_peak_percent: peak('centrifugo_cpu'),
      mem_last: samples.at(-1)?.centrifugo_mem,
    },
    fanout_worker: { cpu_peak_percent: peak('fanout_cpu'), rss_peak_mb: peak('fanout_rss_mb') },
    samples: samples.length,
  };
  console.log(JSON.stringify(result, null, 2));
  console.log(
    stats
      .split('\n')
      .filter((line) => line.startsWith('fanout.'))
      .join('\n'),
  );
  mkdirSync(resolve(HERE, '../test-results'), { recursive: true });
  writeFileSync(resolve(HERE, '../test-results/perf-load.json'), JSON.stringify(result, null, 2));
  return missing === 0 ? 0 : 1;
}

main().then(
  (code) => process.exit(code),
  (error: unknown) => {
    console.error(error);
    process.exit(1);
  },
);
