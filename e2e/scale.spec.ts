import { expect, test } from '@playwright/test';
import { importCsv, openTab, startLocal } from './helpers';

/**
 * Regression (acceptance 02B): 300 look-alike company names produced ~3,000 merge candidates, all
 * rendered at once; switching tabs then took 18 seconds. The review now shows a page at a time.
 */
test('look-alike names: merge review pages its candidates and the app stays responsive', async ({
  page,
}) => {
  await startLocal(page);
  const rows = ['company_name,title,location'];
  for (let i = 0; i < 150; i += 1) {
    rows.push(`Store ${String(i).padStart(3, '0')} Ltd,Shift Engineer,Depot ${i % 7}`);
  }
  await importCsv(page, 'Store list', rows.join('\n'));

  await openTab(page, 'Data');
  const candidates = page.getByTestId('merge-candidate');
  await expect(candidates).toHaveCount(25);
  const more = page.getByTestId('candidates-more');
  await expect(more).toContainText(/Showing 25 of [\d,]+ candidates/);

  await more.getByRole('button', { name: 'Show 25 more' }).click();
  await expect(candidates).toHaveCount(50);

  // Deciding one candidate works and removes it from the list.
  const first = candidates.first();
  await first.getByRole('button', { name: /^Not the same company/ }).click();
  await expect(page.getByTestId('merge-decision')).toHaveCount(1);

  const started = Date.now();
  await openTab(page, 'Radar');
  await expect(page.getByTestId('radar-row').first()).toBeVisible();
  expect(Date.now() - started).toBeLessThan(5000);
});
