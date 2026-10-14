import { expect, test } from '@playwright/test';
import { eraseBackend, ghJob, openTab, setBoard, startConnected, startLocal } from './helpers';

// Generates the committed screenshots from the real production build. Inspect them visually.
test('desktop and mobile screenshots (local-data mode)', async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 900 });
  await startLocal(page);
  await openTab(page, 'Data');
  await page.getByRole('button', { name: 'Load sample data' }).click();
  await openTab(page, 'Radar');
  await expect(page.getByTestId('radar-row').first()).toBeVisible();
  await page.screenshot({ path: 'docs/screenshots/desktop-radar.png', fullPage: true });

  await page
    .getByRole('button', { name: /Tidewater Systems/ })
    .first()
    .click();
  await expect(page.getByTestId('breakdown')).toBeVisible();
  await page.screenshot({ path: 'docs/screenshots/desktop-company.png', fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await openTab(page, 'Radar').catch(async () => {
    await page.getByRole('button', { name: 'Back to the radar' }).click();
  });
  await page.screenshot({ path: 'docs/screenshots/mobile-radar.png', fullPage: true });

  await page.setViewportSize({ width: 1366, height: 900 });
  await page.emulateMedia({ colorScheme: 'dark' });
  await openTab(page, 'Radar');
  await page.screenshot({ path: 'docs/screenshots/desktop-radar-dark.png', fullPage: true });
});

test('desktop screenshot of Sources with refresh history (connected mode)', async ({
  page,
  request,
}) => {
  await eraseBackend(request);
  await setBoard(request, 'greenhouse', 'brightwater', {
    mode: 'ok',
    jobs: [
      ghJob(1, 'Senior Data Engineer'),
      ghJob(2, 'Staff Backend Engineer'),
      ghJob(3, 'Recruiter'),
    ],
  });
  await page.setViewportSize({ width: 1366, height: 900 });
  await startConnected(page);
  await openTab(page, 'Sources');
  await page.getByRole('textbox', { name: 'Board token (required)' }).fill('brightwater');
  await page.getByRole('textbox', { name: 'Company name (required)' }).fill('Brightwater Labs');
  await page.getByRole('button', { name: 'Add source' }).click();
  const row = page.getByTestId('source-row').filter({ hasText: 'Brightwater Labs' });
  await row.getByRole('button', { name: /^Refresh/ }).click();
  await expect(row.getByRole('button', { name: /^Refresh/ })).toBeEnabled();
  await setBoard(request, 'greenhouse', 'brightwater', {
    jobs: [
      ghJob(1, 'Principal Data Engineer'),
      ghJob(2, 'Staff Backend Engineer'),
      ghJob(4, 'ML Engineer'),
    ],
  });
  await row.getByRole('button', { name: /^Refresh/ }).click();
  await expect(row.getByRole('button', { name: /^Refresh/ })).toBeEnabled();
  await row.getByRole('button', { name: /^History/ }).click();
  await expect(page.getByTestId('run-events')).toBeVisible();
  await page.screenshot({ path: 'docs/screenshots/desktop-sources.png', fullPage: true });
});
