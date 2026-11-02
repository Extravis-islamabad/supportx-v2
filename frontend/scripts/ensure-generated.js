/**
 * Before tsc, ESLint, Vitest and builds: the generated API files must exist (D-127). They are never
 * committed (`make generated` writes them; `make setup` runs it). When one is missing, this
 * tries `make generated` once (it needs the backend's uv environment), and otherwise stops with
 * what to run, instead of a wall of type errors.
 */
import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../../', import.meta.url));
const FILES = [
  'frontend/packages/api-client/openapi.json',
  'frontend/packages/api-client/src/schema.ts',
];
const missing = () => FILES.filter((file) => !existsSync(`${root}${file}`));

if (missing().length > 0) {
  console.log(`Generated files missing (${missing().join(', ')}): running make generated`);
  spawnSync('make', ['generated'], { cwd: root, stdio: 'inherit' });
  if (missing().length > 0) {
    console.error('Still missing. Run `make setup` (or `make generated`) from the repo root.');
    process.exit(1);
  }
}
