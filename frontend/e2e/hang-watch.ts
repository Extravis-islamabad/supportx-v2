/**
 * A watchdog for frozen pages in the Playwright run (CI's stack smoke).
 *
 *     node e2e/hang-watch.ts <debugging port> <output folder>
 *
 * Why: a page whose own JavaScript never yields (a render or effect loop) shows up in Playwright
 * only as a step that never returns and, much later, a test timeout that names whatever ran
 * last, often a cleanup `page.request` (2026-11-04: shell 95 and knowledge 347). Neither the trace
 * nor the API log shows where the page was stuck.
 *
 * How: Chromium also listens on a debugging port (playwright.config.ts, E2E_CDP_PORT). This keeps
 * a DevTools connection to every page: it records the console and uncaught errors, and every few
 * seconds asks the page to evaluate `1`. A page that hasn't answered for STUCK_AFTER_MS is
 * frozen. A running script can't be profiled from outside (Profiler.* waits for the page), but
 * Debugger.pause interrupts it, so the watchdog pauses the page SAMPLES times and keeps each
 * stack: a sampling profile of the freeze. It then resumes the page, so the test goes on to fail
 * or pass as it would. Each freeze becomes one JSON file in the output folder.
 *
 * Plain Node 24 (global fetch and WebSocket); no dependencies.
 */

import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

export const STUCK_AFTER_MS = 20_000;
const PROBE_EVERY_MS = 4_000;
const PROBE_TIMEOUT_MS = 3_000;
const SAMPLES = 10;
const SAMPLE_GAP_MS = 300;
const CONSOLE_KEPT = 300;
const FRAMES_KEPT = 25;

export interface CallFrame {
  functionName: string;
  url: string;
  location: { lineNumber: number; columnNumber: number };
}

/** One readable line per frame: `name (file:line:column)`, with the origin and query dropped. */
export function frameLine(frame: CallFrame): string {
  const name = frame.functionName === '' ? '(anonymous)' : frame.functionName;
  const file = frame.url.replace(/^[a-z]+:\/\/[^/]+/, '').replace(/\?.*$/, '');
  const { lineNumber, columnNumber } = frame.location;
  // DevTools counts from 0; editors and stack traces from 1.
  return `${name} (${file || '<inline>'}:${String(lineNumber + 1)}:${String(columnNumber + 1)})`;
}

/** The frames seen most often across the samples: where the freeze spends its time. */
export function hotFrames(samples: string[][], top = 10): { frame: string; samples: number }[] {
  const counts = new Map<string, number>();
  for (const stack of samples) {
    for (const frame of new Set(stack)) counts.set(frame, (counts.get(frame) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]))
    .slice(0, top)
    .map(([frame, n]) => ({ frame, samples: n }));
}

/** A fixed-size log: the newest `size` entries. */
export class Ring<T> {
  private readonly items: T[] = [];
  private readonly size: number;
  constructor(size: number) {
    this.size = size;
  }
  push(item: T): void {
    this.items.push(item);
    if (this.items.length > this.size) this.items.shift();
  }
  all(): T[] {
    return [...this.items];
  }
}

/** Frozen: no answer since `lastAnswer` for at least STUCK_AFTER_MS. */
export function isStuck(lastAnswer: number, now: number): boolean {
  return now - lastAnswer >= STUCK_AFTER_MS;
}

interface CdpMessage {
  id?: number;
  method?: string;
  params?: Record<string, unknown>;
  result?: unknown;
  error?: { message: string };
}

class Cdp {
  private next = 1;
  private readonly waiting = new Map<number, (message: CdpMessage) => void>();
  private readonly listeners: ((message: CdpMessage) => void)[] = [];
  closed = false;
  private readonly socket: WebSocket;

  private constructor(socket: WebSocket) {
    this.socket = socket;
    socket.addEventListener('message', (event) => {
      const message = JSON.parse(String(event.data)) as CdpMessage;
      if (message.id !== undefined) {
        this.waiting.get(message.id)?.(message);
        this.waiting.delete(message.id);
      } else {
        for (const listener of this.listeners) listener(message);
      }
    });
    socket.addEventListener('close', () => {
      this.closed = true;
    });
  }

  static open(url: string): Promise<Cdp> {
    return new Promise((resolve, reject) => {
      const socket = new WebSocket(url);
      socket.addEventListener('open', () => {
        resolve(new Cdp(socket));
      });
      socket.addEventListener('error', () => {
        reject(new Error(`no DevTools connection to ${url}`));
      });
    });
  }

  on(listener: (message: CdpMessage) => void): void {
    this.listeners.push(listener);
  }

  /** The command's answer, or null when there is none within `timeoutMs` (or it failed). */
  send(method: string, params: object = {}, timeoutMs = 5_000): Promise<CdpMessage | null> {
    if (this.closed) return Promise.resolve(null);
    const id = this.next++;
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.waiting.delete(id);
        resolve(null);
      }, timeoutMs);
      this.waiting.set(id, (message) => {
        clearTimeout(timer);
        resolve(message.error === undefined ? message : null);
      });
      this.socket.send(JSON.stringify({ id, method, params }));
    });
  }

  close(): void {
    this.socket.close();
  }
}

interface Target {
  id: string;
  type: string;
  url: string;
  title: string;
  webSocketDebuggerUrl?: string;
}

const sleep = (ms: number) =>
  new Promise((resolve) => {
    setTimeout(resolve, ms);
  });

function text(params: Record<string, unknown> | undefined): string {
  // consoleAPICalled: args with a value or a description; exceptionThrown: exceptionDetails.
  const args = (params?.args ?? []) as { value?: unknown; description?: string }[];
  if (args.length > 0) {
    // A primitive value prints as itself; anything else as DevTools describes it.
    return args
      .map((a) =>
        typeof a.value === 'string' || typeof a.value === 'number' || typeof a.value === 'boolean'
          ? String(a.value)
          : (a.description ?? JSON.stringify(a.value)),
      )
      .join(' ');
  }
  const details = params?.exceptionDetails as
    { text?: string; exception?: { description?: string } } | undefined;
  const entry = params?.entry as { text?: string } | undefined;
  return details?.exception?.description ?? details?.text ?? entry?.text ?? '';
}

class Watched {
  lastAnswer = Date.now();
  captured = false;
  private probing = false;
  readonly console = new Ring<{ at: string; kind: string; text: string }>(CONSOLE_KEPT);
  private paused: ((frames: CallFrame[]) => void) | null = null;
  readonly target: Target;
  readonly cdp: Cdp;

  constructor(target: Target, cdp: Cdp) {
    this.target = target;
    this.cdp = cdp;
    cdp.on((message) => {
      const kind =
        message.method === 'Runtime.consoleAPICalled'
          ? `console.${String(message.params?.type)}`
          : message.method === 'Runtime.exceptionThrown'
            ? 'uncaught'
            : message.method === 'Log.entryAdded'
              ? `log.${String((message.params?.entry as { level?: string } | undefined)?.level)}`
              : null;
      if (kind !== null) {
        this.console.push({
          at: new Date().toISOString(),
          kind,
          text: text(message.params).slice(0, 400),
        });
      }
      if (message.method === 'Debugger.paused') {
        this.paused?.((message.params?.callFrames ?? []) as CallFrame[]);
      }
    });
  }

  async start(): Promise<void> {
    // Debugger must be on before a freeze: Debugger.enable itself waits for the page, while
    // Debugger.pause interrupts running script. Breakpoints off, so `debugger;` never stops it.
    await Promise.all([
      this.cdp.send('Runtime.enable'),
      this.cdp.send('Log.enable'),
      this.cdp.send('Debugger.enable'),
    ]);
    await this.cdp.send('Debugger.setBreakpointsActive', { active: false });
  }

  async probe(): Promise<void> {
    if (this.probing) return;
    this.probing = true;
    const answer = await this.cdp.send(
      'Runtime.evaluate',
      { expression: '1', returnByValue: true },
      PROBE_TIMEOUT_MS,
    );
    this.probing = false;
    if (answer !== null) {
      this.lastAnswer = Date.now();
      this.captured = false; // answering again: a later freeze is captured too
    }
  }

  private pauseOnce(): Promise<CallFrame[] | null> {
    return new Promise((resolve) => {
      const timer = setTimeout(() => {
        this.paused = null;
        resolve(null);
      }, 5_000);
      this.paused = (frames) => {
        clearTimeout(timer);
        this.paused = null;
        resolve(frames);
      };
      void this.cdp.send('Debugger.pause');
    });
  }

  async capture(out: string): Promise<void> {
    this.captured = true;
    const samples: string[][] = [];
    for (let i = 0; i < SAMPLES; i++) {
      const frames = await this.pauseOnce();
      if (frames !== null) samples.push(frames.slice(0, FRAMES_KEPT).map(frameLine));
      await this.cdp.send('Debugger.resume');
      await sleep(SAMPLE_GAP_MS);
    }
    const at = new Date().toISOString();
    const report = {
      at,
      url: this.target.url,
      title: this.target.title,
      unresponsive_ms: Date.now() - this.lastAnswer,
      hot_frames: hotFrames(samples),
      samples,
      console: this.console.all(),
    };
    const file = join(out, `freeze-${at.replace(/[:.]/g, '-')}-${this.target.id.slice(0, 8)}.json`);
    writeFileSync(file, `${JSON.stringify(report, null, 2)}\n`);
    const top = report.hot_frames[0]?.frame ?? 'no stack (the pause did not land)';
    process.stdout.write(`[hang-watch] frozen page ${this.target.url}: ${top} -> ${file}\n`);
  }
}

async function watch(port: number, out: string): Promise<void> {
  mkdirSync(out, { recursive: true });
  const pages = new Map<string, Watched>();
  process.stdout.write(`[hang-watch] watching 127.0.0.1:${String(port)}, captures in ${out}\n`);
  for (;;) {
    let targets: Target[] = [];
    try {
      const listed = await fetch(`http://127.0.0.1:${String(port)}/json/list`);
      targets = (await listed.json()) as Target[];
    } catch {
      // No browser between tests or retries (a new worker starts a new one): look again soon.
    }
    const live = new Set(targets.map((t) => t.id));
    for (const [id, page] of pages) {
      if (!live.has(id) || page.cdp.closed) {
        page.cdp.close();
        pages.delete(id);
      }
    }
    for (const target of targets) {
      if (target.type !== 'page' || pages.has(target.id) || !target.webSocketDebuggerUrl) continue;
      try {
        const page = new Watched(target, await Cdp.open(target.webSocketDebuggerUrl));
        pages.set(target.id, page);
        void page.start();
      } catch {
        // The page closed before we connected.
      }
    }
    const now = Date.now();
    for (const [id, page] of pages) {
      const target = targets.find((t) => t.id === id);
      if (target) Object.assign(page.target, { url: target.url, title: target.title });
      if (!page.captured && isStuck(page.lastAnswer, now)) void page.capture(out);
      else void page.probe();
    }
    await sleep(PROBE_EVERY_MS);
  }
}

if (import.meta.url === `file://${process.argv[1] ?? ''}`) {
  const [port, out] = process.argv.slice(2);
  if (port === undefined || out === undefined) {
    process.stderr.write('usage: node e2e/hang-watch.ts <debugging port> <output folder>\n');
    process.exit(2);
  }
  void watch(Number(port), out);
}
