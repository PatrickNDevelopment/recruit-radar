// Minimal, dependency-free secret/sensitive-data scan over tracked and untracked source files.
// Exits 1 if anything suspicious is found. It complements, not replaces, a dedicated scanner.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, sep } from 'node:path';

const root = process.cwd();
const SKIP_DIRS = new Set([
  'node_modules',
  'dist',
  '.git',
  'playwright-report',
  'test-results',
  'coverage',
  '.venv',
  '__pycache__',
  '.pytest_cache',
  '.mypy_cache',
  '.ruff_cache',
]);
const SKIP_EXT = /\.(png|jpg|jpeg|gif|ico|woff2?|lock)$/i;
const PATTERNS = [
  ['private key block', /-----BEGIN [A-Z ]*PRIVATE KEY-----/],
  ['AWS access key id', /\bAKIA[0-9A-Z]{16}\b/],
  ['GitHub token', /\bgh[pousr]_[A-Za-z0-9]{30,}\b/],
  ['GitHub fine-grained token', /\bgithub_pat_[A-Za-z0-9_]{40,}\b/],
  ['Slack token', /\bxox[baprs]-[A-Za-z0-9-]{10,}\b/],
  ['Anthropic/OpenAI style key', /\bsk-[A-Za-z0-9_-]{32,}\b/],
  ['Google API key', /\bAIza[0-9A-Za-z_-]{35}\b/],
  [
    'hard-coded password assignment',
    /\b(password|passwd|secret|api[_-]?key)\s*[:=]\s*['"][^'"\s]{8,}['"]/i,
  ],
  [
    'email address (personal data check)',
    /\b[A-Za-z0-9._%+-]+@(?!example\.(com|org)\b)[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b/,
  ],
];
const SELF = join('scripts', 'secret-scan.mjs');

const findings = [];
function walk(dir) {
  for (const name of readdirSync(dir)) {
    if (SKIP_DIRS.has(name)) continue;
    const p = join(dir, name);
    const st = statSync(p);
    if (st.isDirectory()) walk(p);
    else if (!SKIP_EXT.test(name) && st.size < 2_000_000) {
      const rel = relative(root, p);
      if (rel === SELF || rel === 'package-lock.json') continue;
      const lines = readFileSync(p, 'utf8').split(/\r?\n/);
      lines.forEach((line, i) => {
        for (const [label, re] of PATTERNS) {
          if (re.test(line)) findings.push(`${rel.split(sep).join('/')}:${i + 1}  ${label}`);
        }
      });
    }
  }
}
walk(root);

if (findings.length > 0) {
  console.error('Potential sensitive material found:\n' + findings.join('\n'));
  process.exit(1);
}
console.log('secret-scan: no findings');
