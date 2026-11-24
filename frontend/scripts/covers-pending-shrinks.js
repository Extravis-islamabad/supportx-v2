// CI: the `channel-covers` exemption list only shrinks against the target branch (§8.3).
//   node scripts/covers-pending-shrinks.js <base-list.json | -> <base-has-rule: yes | no>
// `-` means the target branch has no list; `base-has-rule` says whether it has the rule (so a
// missing list is "before the rule", which passes, or "finished and deleted", which a re-add fails).
import { existsSync, readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { shrinkProblem } from '../packages/eslint-plugin/pending-shrinks.js';

const here = dirname(fileURLToPath(import.meta.url));
const currentPath = resolve(here, '../packages/eslint-plugin/channel-covers-pending.json');
const [basePath, hasRule] = process.argv.slice(2);
if (basePath === undefined || (hasRule !== 'yes' && hasRule !== 'no')) {
  console.error('usage: node scripts/covers-pending-shrinks.js <base.json | -> <yes | no>');
  process.exit(2);
}

/** @param {string} path */
const listAt = (path) => JSON.parse(readFileSync(path, 'utf8')).files;
const problem = shrinkProblem({
  base: basePath === '-' ? null : listAt(basePath),
  baseHasRule: hasRule === 'yes',
  current: existsSync(currentPath) ? listAt(currentPath) : null,
});
if (problem !== null) {
  console.error(problem);
  process.exit(1);
}
console.log('channel-covers-pending.json: no file added against the target branch.');
