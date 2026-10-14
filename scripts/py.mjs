// Runs Python with the project's virtualenv when it exists, otherwise the interpreter on PATH
// (CI installs the pinned requirements globally). Usage: node scripts/py.mjs <python args...>
import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

const root = resolve(import.meta.dirname, '..');
const venvPython =
  process.platform === 'win32'
    ? resolve(root, '.venv', 'Scripts', 'python.exe')
    : resolve(root, '.venv', 'bin', 'python');
const python = existsSync(venvPython)
  ? venvPython
  : process.platform === 'win32'
    ? 'python'
    : 'python3';

const result = spawnSync(python, process.argv.slice(2), {
  cwd: root,
  stdio: 'inherit',
  env: { ...process.env, RR_REQUIRE_VECTORS: '1' },
});
if (result.error) {
  console.error(`Could not start ${python}: ${result.error.message}`);
  process.exit(127);
}
process.exit(result.status ?? 1);
