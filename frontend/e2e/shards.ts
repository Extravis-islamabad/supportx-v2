/**
 * Balanced Playwright shards for the stack smoke (CI). Playwright's own --shard splits by test
 * count, so the slow journeys landed together and one shard ran 35 minutes while another ran 10.
 *
 *   node shards.ts 2/3               the spec files of shard 2 of 3, one per line
 *   node shards.ts --weights a.log   new weights from CI logs of the list reporter
 *
 * Files are assigned whole, heaviest first, each to the shard with the least time so far, using
 * the seconds in shard-weights.json (measured on CI's runners, retries included). A spec not
 * listed there weighs DEFAULT_SECONDS. The split depends only on the file names and the weights,
 * so every shard computes the same one without talking to the others.
 */
import { readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const WEIGHTS = join(HERE, 'shard-weights.json');
const DEFAULT_SECONDS = 30;

export function assign(
  files: string[],
  weights: Record<string, number>,
  count: number,
): string[][] {
  const shards = Array.from({ length: count }, () => ({ seconds: 0, files: [] as string[] }));
  const heaviest = [...files].sort(
    (a, b) =>
      (weights[b] ?? DEFAULT_SECONDS) - (weights[a] ?? DEFAULT_SECONDS) || a.localeCompare(b),
  );
  for (const file of heaviest) {
    const lightest = shards.reduce((best, shard) => (shard.seconds < best.seconds ? shard : best));
    lightest.files.push(file);
    lightest.seconds += weights[file] ?? DEFAULT_SECONDS;
  }
  return shards.map((shard) => shard.files.sort());
}

/** Seconds per spec file from list-reporter lines such as `✓  3 [chromium] › tests/a.spec.ts:9:1 › … (12.3s)`. */
export function weightsFrom(log: string): Record<string, number> {
  const found: Record<string, number> = {};
  const line = /[✓✘-]\s+\d+ \[chromium\] › (tests\/[^:]+):.*\((\d+(?:\.\d+)?)(m|s)\)\s*$/u;
  for (const text of log.split('\n')) {
    const match = line.exec(text);
    if (match === null) continue;
    const [, file = '', amount = '0', unit = 's'] = match;
    found[file] = (found[file] ?? 0) + Number(amount) * (unit === 'm' ? 60 : 1);
  }
  return Object.fromEntries(
    Object.entries(found)
      .sort(([a], [b]) => a.localeCompare(b))
      .map(([file, seconds]) => [file, Math.ceil(seconds)]),
  );
}

function main(args: string[]): void {
  if (args[0] === '--weights') {
    const log = args
      .slice(1)
      .map((path) => readFileSync(path, 'utf8'))
      .join('\n');
    writeFileSync(WEIGHTS, `${JSON.stringify(weightsFrom(log), null, 2)}\n`);
    return;
  }
  const [index, count] = (args[0] ?? '').split('/').map(Number);
  if (index === undefined || count === undefined || !(index >= 1 && index <= count)) {
    throw new Error('usage: node shards.ts <shard>/<count>');
  }
  const files = readdirSync(join(HERE, 'tests'))
    .filter((name) => name.endsWith('.spec.ts'))
    .map((name) => `tests/${name}`);
  const weights = JSON.parse(readFileSync(WEIGHTS, 'utf8')) as Record<string, number>;
  process.stdout.write(`${(assign(files, weights, count)[index - 1] ?? []).join('\n')}\n`);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main(process.argv.slice(2));
