#!/usr/bin/env node
// Keeps every module label file (src/resources/<module>/<lang>.ts) in key order, so two PRs
// that add labels no longer both append to the end of the same file and conflict (D-127
// follow-up). `--check` only reports: it exits 1 when a file is out of order (the fast checks).
//
// An entry is its key line plus any continuation lines (a long value on the next line). Comment
// lines inside the object move with the entry that follows them, so no text is ever lost.
// Keys compare by code point, the same order on every machine.

import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', 'src', 'resources');
const ENTRY = /^ {2}'((?:[^'\\]|\\.)+)':/;
const OPEN = /= \{$/;
const CLOSE = /^\}( as const)?;$/;

/** The file with its object's entries sorted; throws on a shape it does not know. */
export function sortSource(source, name = 'file') {
  const lines = source.split('\n');
  const open = lines.findIndex((line) => OPEN.test(line));
  const close = lines.findIndex((line, i) => i > open && CLOSE.test(line));
  if (open < 0 || close < 0) throw new Error(`${name}: no "= {" ... "};" object found`);
  const entries = [];
  let pending = []; // comments waiting for the entry they describe
  for (const line of lines.slice(open + 1, close)) {
    const match = ENTRY.exec(line);
    if (match) {
      entries.push({ key: match[1], lines: [...pending, line] });
      pending = [];
    } else if (line.trim().startsWith('//')) {
      pending.push(line);
    } else if (line.trim() === '') {
      continue; // blank lines carry nothing once the order is by key
    } else if (entries.length > 0 && pending.length === 0) {
      entries[entries.length - 1].lines.push(line); // a value continued on the next line
    } else {
      throw new Error(`${name}: cannot place line "${line.trim()}"`);
    }
  }
  if (pending.length > 0) entries.push({ key: '￿', lines: pending }); // trailing comments
  const seen = new Set();
  for (const { key } of entries) {
    if (seen.has(key) && key !== '￿') throw new Error(`${name}: key "${key}" twice`);
    seen.add(key);
  }
  const sorted = [...entries].sort((a, b) => (a.key < b.key ? -1 : a.key > b.key ? 1 : 0));
  return [
    ...lines.slice(0, open + 1),
    ...sorted.flatMap((entry) => entry.lines),
    ...lines.slice(close),
  ].join('\n');
}

function labelFiles() {
  return readdirSync(ROOT)
    .filter((entry) => statSync(join(ROOT, entry)).isDirectory())
    .flatMap((module) =>
      readdirSync(join(ROOT, module))
        .filter((file) => /^[a-z]{2}\.ts$/.test(file))
        .map((file) => join(ROOT, module, file)),
    );
}

function main() {
  const check = process.argv.includes('--check');
  const unsorted = [];
  for (const file of labelFiles()) {
    const source = readFileSync(file, 'utf8');
    const sorted = sortSource(source, relative(ROOT, file));
    if (sorted === source) continue;
    unsorted.push(relative(ROOT, file));
    if (!check) writeFileSync(file, sorted);
  }
  if (check && unsorted.length > 0) {
    process.stderr.write(
      `Label keys out of order in: ${unsorted.join(', ')}\nRun: make labels-sort\n`,
    );
    process.exit(1);
  }
  if (!check) process.stdout.write(`labels-sort: ${String(unsorted.length)} file(s) sorted\n`);
}

if (process.argv[1] === fileURLToPath(import.meta.url)) main();
