import { expect, type APIRequestContext, type Page } from '@playwright/test';

export const ATS = 'http://127.0.0.1:8788';
export const API = 'http://127.0.0.1:8787/api';

export type Provider = 'greenhouse' | 'lever' | 'ashby';
export type BoardMode = 'ok' | '404' | '401' | '429' | '500' | 'malformed' | 'slow';

/** Wipes the backend database so connected-mode tests start from nothing. */
export async function eraseBackend(request: APIRequestContext): Promise<void> {
  const response = await request.delete(`${API}/data?confirm=erase-all`);
  expect(response.status()).toBe(204);
}

/** Replaces a fake ATS board's jobs and/or forces an error mode (test-only control endpoint). */
export async function setBoard(
  request: APIRequestContext,
  provider: Provider,
  token: string,
  body: { jobs?: unknown[]; mode?: BoardMode },
): Promise<void> {
  const response = await request.post(`${ATS}/__control/${provider}/${token}`, { data: body });
  expect(response.ok()).toBe(true);
}

export const mainNav = (page: Page) => page.getByRole('navigation', { name: 'Main' });

export async function openTab(
  page: Page,
  name: 'Radar' | 'Data' | 'Sources' | 'Settings' | 'About',
) {
  await mainNav(page).getByRole('button', { name }).click();
  await expect(page.getByRole('heading', { level: 1, name })).toBeVisible();
}

/** Starts the app and forces local-data mode through the real Settings control. */
export async function startLocal(page: Page): Promise<void> {
  await page.goto('./');
  await openTab(page, 'Settings');
  await page.getByRole('radio', { name: 'Always local-data mode' }).check();
  await expect(page.getByTestId('current-mode')).toContainText(/local-data mode/i);
}

/** Starts the app against the e2e backend (the default address). */
export async function startConnected(page: Page): Promise<void> {
  await page.goto('./');
  await expect(page.getByTestId('mode-chip').first()).toContainText(/connected/i);
}

export async function importCsv(page: Page, label: string, csv: string): Promise<void> {
  await openTab(page, 'Data');
  const form = page.getByRole('form', { name: 'Import a CSV file' });
  await form.getByRole('textbox', { name: 'Dataset label (required)' }).fill(label);
  await form.getByRole('textbox', { name: 'Or paste CSV text' }).fill(csv);
  await form.getByRole('button', { name: 'Import CSV' }).click();
}

export function ghJob(id: number, title: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    title,
    updated_at: '2026-10-10T09:00:00-04:00',
    first_published: '2026-09-01T09:00:00-04:00',
    absolute_url: `https://boards.example.test/brightwater/jobs/${id}`,
    location: { name: 'Remote - US' },
    departments: [{ id: 1, name: 'Engineering' }],
    ...extra,
  };
}

export function leverJob(id: string, text: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    text,
    hostedUrl: `https://jobs.example.test/lever/${id}`,
    categories: { location: 'Berlin, Germany', department: 'Product', team: 'Growth' },
    workplaceType: 'hybrid',
    createdAt: 1_788_000_000_000,
    ...extra,
  };
}

export function ashbyJob(slug: string, title: string, extra: Record<string, unknown> = {}) {
  return {
    title,
    location: 'Toronto, Canada',
    department: 'Operations',
    isListed: true,
    isRemote: false,
    workplaceType: 'Hybrid',
    publishedAt: '2026-09-15T12:00:00.000+00:00',
    jobUrl: `https://jobs.example.test/ashby/${slug}`,
    applyUrl: `https://jobs.example.test/ashby/${slug}/application`,
    ...extra,
  };
}

export const CSV_A = [
  'company_name,title,location,work_mode,posted_at,source_posting_id',
  'Northwind Analytics,Senior Data Engineer,"Austin, TX",hybrid,2026-08-20,a-1',
  'Northwind Analytics Inc.,Data Platform Engineer,Remote - US,remote,2026-09-25,a-2',
  'Harbor Freight Labs,Backend Engineer,Boston MA,onsite,2026-10-01,',
  'Pine Street Capital,Account Executive,Chicago,onsite,2026-10-02,',
  'Door Dash Robotics,Controls Engineer,Detroit,onsite,2026-10-03,',
].join('\n');

export const CSV_B = [
  'company_name,title,location,work_mode,posted_at,source_posting_id',
  'northwind analytics,Senior Data Engineer,TX - Austin,hybrid,2026-08-20,b-77',
  'Harbour Freight Labs,Backend Engineer,Boston MA,onsite,,',
  'DoorDash Robotics,Controls Engineer,Detroit,onsite,,',
  'Pine Street Capital Inc,Account Executive,Chicago,onsite,,',
].join('\n');
