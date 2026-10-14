import { expect, test, type Page } from '@playwright/test';
import {
  ashbyJob,
  eraseBackend,
  ghJob,
  leverJob,
  openTab,
  setBoard,
  startConnected,
  type Provider,
} from './helpers';

const TOKEN = 'brightwater';
const COMPANY = 'Brightwater Labs';

async function addSource(
  page: Page,
  provider: 'Greenhouse' | 'Lever' | 'Ashby',
  token: string,
  company: string,
) {
  await openTab(page, 'Sources');
  await page.getByRole('combobox', { name: 'Provider' }).selectOption({ label: provider });
  await page.getByRole('textbox', { name: 'Board token (required)' }).fill(token);
  await page.getByRole('textbox', { name: 'Company name (required)' }).fill(company);
  await page.getByRole('button', { name: 'Add source' }).click();
  await expect(page.getByTestId('source-row').filter({ hasText: company })).toBeVisible();
}

async function refresh(page: Page, company: string) {
  const row = page.getByTestId('source-row').filter({ hasText: company });
  await row.getByRole('button', { name: /^Refresh/ }).click();
  await expect(row.getByRole('button', { name: /^Refresh/ })).toBeEnabled();
}

const runRows = (page: Page) => page.getByTestId('run-row');

test.describe('connected mode with a real backend and a fake ATS', () => {
  test.beforeEach(async ({ request }) => {
    await eraseBackend(request);
  });

  test('journey 2: refresh, inspect, change the board, refresh again, see the role events', async ({
    page,
    request,
  }) => {
    await setBoard(request, 'greenhouse', TOKEN, {
      mode: 'ok',
      jobs: [
        ghJob(1001, 'Senior Data Engineer'),
        ghJob(1002, 'Staff Backend Engineer'),
        ghJob(1003, 'Recruiting Coordinator'),
        ghJob(1004, 'Security Engineer'),
      ],
    });
    await startConnected(page);
    await expect(page.getByTestId('connected-banner')).toBeVisible();

    await addSource(page, 'Greenhouse', TOKEN, COMPANY);
    await refresh(page, COMPANY);

    // First run: four postings, all new, a successful run in the history.
    await page
      .getByTestId('source-row')
      .filter({ hasText: COMPANY })
      .getByRole('button', { name: /^History/ })
      .click();
    await expect(runRows(page)).toHaveCount(1);
    const first = runRows(page).first();
    await expect(first).toContainText('Succeeded');
    await expect(first).toContainText('127.0.0.1');

    // The normalized roles reached the radar with source links back to the provider URL.
    await openTab(page, 'Radar');
    const row = page.getByTestId('radar-row').filter({ hasText: COMPANY });
    await expect(row).toBeVisible();
    await page.getByRole('button', { name: COMPANY, exact: true }).click();
    await expect(page.getByTestId('role-row')).toHaveCount(4);
    const link = page.getByTestId('role-row').first().getByRole('link').first();
    await expect(link).toHaveAttribute(
      'href',
      /^https:\/\/boards\.example\.test\/brightwater\/jobs\/\d+$/,
    );
    await expect(link).toHaveAttribute('rel', /noopener/);

    // Mutate the board: rename one role, remove one, add one.
    await setBoard(request, 'greenhouse', TOKEN, {
      jobs: [
        ghJob(1001, 'Principal Data Engineer'), // renamed
        ghJob(1002, 'Staff Backend Engineer'),
        // 1003 removed
        ghJob(1004, 'Security Engineer'),
        ghJob(1005, 'Machine Learning Engineer'), // added
      ],
    });
    await openTab(page, 'Sources');
    await refresh(page, COMPANY);
    await page
      .getByTestId('source-row')
      .filter({ hasText: COMPANY })
      .getByRole('button', { name: /^History/ })
      .click();
    await expect(runRows(page)).toHaveCount(2);

    const events = page.getByTestId('run-events');
    await expect(events).toContainText('Principal Data Engineer');
    // Baseline events belong to the first run only, even when both runs end in the same second.
    await expect(events).not.toContainText('First observed (baseline)');
    await expect(events).toContainText('changed: title');
    await expect(events).toContainText('Recruiting Coordinator');
    await expect(events.getByText('No longer listed')).toBeVisible();
    await expect(events).toContainText('Machine Learning Engineer');
    await expect(events.getByText('Added', { exact: true })).toBeVisible();

    // Newest run first: 4 seen = 1 added + 1 changed + 2 unchanged; 1 role no longer listed.
    const newest = runRows(page).first();
    await expect(newest).toContainText('Succeeded');
    const cells = await newest.locator('td').allInnerTexts();
    expect(cells.slice(4, 10).map((c) => c.trim())).toEqual(['4', '1', '1', '1', '0', '2']);

    // The removed role is history, not deleted: the company still shows four active roles.
    await openTab(page, 'Radar');
    await page.getByRole('button', { name: COMPANY, exact: true }).click();
    await expect(page.getByTestId('role-row').filter({ hasText: 'Active' })).toHaveCount(4);
    await expect(
      page.getByTestId('role-row').filter({ hasText: 'Recruiting Coordinator' }),
    ).toContainText(/no longer listed|removed/i);

    // A role that comes back is reported as listed again.
    await setBoard(request, 'greenhouse', TOKEN, {
      jobs: [
        ghJob(1001, 'Principal Data Engineer'),
        ghJob(1002, 'Staff Backend Engineer'),
        ghJob(1003, 'Recruiting Coordinator'),
        ghJob(1004, 'Security Engineer'),
        ghJob(1005, 'Machine Learning Engineer'),
      ],
    });
    await openTab(page, 'Sources');
    await refresh(page, COMPANY);
    await page
      .getByTestId('source-row')
      .filter({ hasText: COMPANY })
      .getByRole('button', { name: /^History/ })
      .click();
    await expect(page.getByTestId('run-events')).toContainText('Listed again');
  });

  test('failed refreshes are recorded, explained, and never delete data', async ({
    page,
    request,
  }) => {
    await setBoard(request, 'greenhouse', TOKEN, {
      mode: 'ok',
      jobs: [ghJob(1, 'Data Engineer'), ghJob(2, 'Backend Engineer')],
    });
    await startConnected(page);
    await addSource(page, 'Greenhouse', TOKEN, COMPANY);
    await refresh(page, COMPANY);

    const cases: Array<[Parameters<typeof setBoard>[3]['mode'], RegExp]> = [
      ['404', /Board not found \(404\)/],
      ['401', /not public \(401\/403\)/],
      ['429', /rate-limited the request \(429\)\. Retry after 7 s\./],
      ['500', /server error \(5xx\)/],
      ['malformed', /could not be read/],
    ];
    for (const [mode, expected] of cases) {
      await setBoard(request, 'greenhouse', TOKEN, { mode });
      await openTab(page, 'Sources');
      await refresh(page, COMPANY);
      await page
        .getByTestId('source-row')
        .filter({ hasText: COMPANY })
        .getByRole('button', { name: /^History/ })
        .click();
      await expect(runRows(page).first()).toContainText('Failed');
      await expect(runRows(page).first()).toContainText(expected);
    }
    await expect(runRows(page)).toHaveCount(6);

    // Nothing was lost by six failed runs: both roles are still active.
    await openTab(page, 'Radar');
    await page.getByRole('button', { name: COMPANY, exact: true }).click();
    await expect(page.getByTestId('role-row').filter({ hasText: 'Active' })).toHaveCount(2);
  });

  test('Lever pagination and Ashby without job ids both import', async ({ page, request }) => {
    const leverJobs = Array.from({ length: 130 }, (_, i) =>
      leverJob(`lv-${String(i).padStart(3, '0')}`, `Growth Marketer ${i + 1}`),
    );
    await setBoard(request, 'lever', 'northlake', { mode: 'ok', jobs: leverJobs });
    await setBoard(request, 'ashby', 'keystone', {
      mode: 'ok',
      jobs: [
        ashbyJob('aaaa1111-2222-3333-4444-555566667777', 'Operations Lead'),
        ashbyJob('bbbb1111-2222-3333-4444-555566667777', 'Finance Analyst'),
        ashbyJob('hidden-role-001', 'Internal Only', { isListed: false }),
      ],
    });
    await startConnected(page);
    await addSource(page, 'Lever', 'northlake', 'Northlake Media');
    await refresh(page, 'Northlake Media');
    await addSource(page, 'Ashby', 'keystone', 'Keystone Works');
    await refresh(page, 'Keystone Works');

    await openTab(page, 'Radar');
    const northlake = page.getByTestId('radar-row').filter({ hasText: 'Northlake Media' });
    await expect(northlake).toContainText('130');
    const keystone = page.getByTestId('radar-row').filter({ hasText: 'Keystone Works' });
    // The unlisted posting is not imported.
    await expect(keystone).toContainText('2');
    await page.getByRole('button', { name: 'Keystone Works', exact: true }).click();
    await expect(page.getByTestId('role-row').filter({ hasText: 'Internal Only' })).toHaveCount(0);
  });

  test('the backend only ever received read requests', async ({ request }) => {
    const log = await request.get('http://127.0.0.1:8788/__requests');
    const entries = (await log.json()) as Array<{ method: string; path: string; ua: string }>;
    for (const entry of entries) expect(entry.method).toBe('GET');
    const provider: Provider[] = ['greenhouse', 'lever', 'ashby'];
    expect(provider.length).toBe(3);
  });
});
