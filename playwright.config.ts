import { existsSync, mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join, resolve } from 'node:path';
import { defineConfig } from '@playwright/test';

/**
 * End-to-end tests run against the PRODUCTION build under the Pages prefix (/recruit-radar/),
 * a real FastAPI backend on a fresh temp SQLite database, and a local fake ATS server that
 * stands in for Greenhouse / Lever / Ashby (the adapters' base URLs are env-overridable for this).
 * Locally we reuse the installed Microsoft Edge (no download); CI installs Chromium, Firefox and WebKit.
 */
const BACKEND_PORT = 8787;
const ATS_PORT = 8788;
const WEB_PORT = 4174;
const isWindows = process.platform === 'win32';
// The project's virtualenv when present (local development), otherwise the interpreter on PATH
// (CI installs the pinned requirements globally).
const venvPython = resolve(
  process.cwd(),
  isWindows ? '.venv\\Scripts\\python.exe' : '.venv/bin/python',
);
const python = existsSync(venvPython) ? venvPython : isWindows ? 'python' : 'python3';
const py = `"${python}"`;
const dataDir = mkdtempSync(join(tmpdir(), 'recruit-radar-e2e-'));
const ats = `http://127.0.0.1:${ATS_PORT}`;

const EXTRA_BROWSERS = (process.env['PW_EXTRA_BROWSERS'] ?? '')
  .split(',')
  .map((b) => b.trim())
  .filter((b): b is 'firefox' | 'webkit' => b === 'firefox' || b === 'webkit');

export default defineConfig({
  testDir: 'e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list']],
  use: {
    baseURL: `http://localhost:${WEB_PORT}/recruit-radar/`,
    trace: 'retain-on-failure',
  },
  projects: [
    // Chromium is the gate everywhere (installed Edge locally, Chromium in CI). Firefox and WebKit run
    // when PW_EXTRA_BROWSERS lists them, as the CI workflow does.
    {
      name: 'chromium',
      use: { browserName: 'chromium', channel: process.env['CI'] ? undefined : 'msedge' },
    },
    ...EXTRA_BROWSERS.map((name) => ({ name, use: { browserName: name } })),
  ],
  webServer: [
    {
      command: `${py} e2e/fake-ats/server.py --port ${ATS_PORT}`,
      url: `${ats}/__health`,
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command: `${py} -m recruit_radar`,
      cwd: 'backend',
      url: `http://127.0.0.1:${BACKEND_PORT}/api/health`,
      reuseExistingServer: false,
      timeout: 60_000,
      env: {
        RECRUIT_RADAR_DB_PATH: join(dataDir, 'e2e.sqlite3'),
        RECRUIT_RADAR_PORT: String(BACKEND_PORT),
        RECRUIT_RADAR_HOST: '127.0.0.1',
        RECRUIT_RADAR_CORS_ORIGINS: `http://localhost:${WEB_PORT},http://127.0.0.1:${WEB_PORT}`,
        RECRUIT_RADAR_MIN_REFRESH_INTERVAL_S: '0',
        RECRUIT_RADAR_GREENHOUSE_BASE_URL: ats,
        RECRUIT_RADAR_LEVER_BASE_URL: ats,
        RECRUIT_RADAR_ASHBY_BASE_URL: ats,
      },
    },
    {
      command: 'npm run build && npm run preview',
      url: `http://localhost:${WEB_PORT}/recruit-radar/`,
      reuseExistingServer: false,
      timeout: 180_000,
    },
  ],
});
