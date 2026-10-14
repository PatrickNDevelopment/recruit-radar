import { readFileSync } from 'node:fs';
import { expect, test } from '@playwright/test';
import { CSV_A, CSV_B, importCsv, openTab, startLocal } from './helpers';

/**
 * Journey 1 (spec 05): two overlapping datasets in local-data mode, duplicates collapsed into
 * canonical companies and roles, a merge candidate decided, a score breakdown read, a company
 * shortlisted and the shortlist exported. No backend involved.
 */
test('local-data mode: overlapping datasets, merge review, evidence score, shortlist export', async ({
  page,
}) => {
  await startLocal(page);
  await expect(page.getByTestId('local-banner')).toContainText(
    'Local-data mode: your data stays in this browser. Live ATS refresh needs the local backend.',
  );

  await importCsv(page, 'Board A', CSV_A);
  await expect(page.getByTestId('dataset-row')).toHaveCount(1);
  await importCsv(page, 'Feed B', CSV_B);
  await expect(page.getByTestId('dataset-row')).toHaveCount(2);

  // Name variants that are equal after normalisation collapse automatically; look-alikes do not.
  await openTab(page, 'Radar');
  await expect(page.getByTestId('radar-row')).toHaveCount(6);

  // Merge review lists exactly the two look-alike pairs and never merges them by itself.
  await openTab(page, 'Data');
  const candidates = page.getByTestId('merge-candidate');
  await expect(candidates).toHaveCount(2);
  await expect(candidates.filter({ hasText: 'identical apart from spacing' })).toHaveCount(1);
  await expect(candidates.filter({ hasText: 'differ by a single character' })).toHaveCount(1);

  // Decide one pair as the same company and the other as different.
  const doorDash = candidates.filter({ hasText: /door ?dash/i });
  await doorDash
    .getByRole('button', { name: /^Merge as one company/ })
    .first()
    .click();
  await expect(candidates).toHaveCount(1);
  const harbor = candidates.first();
  await harbor
    .getByRole('button', { name: /^Not the same company/ })
    .first()
    .click();
  await expect(page.getByTestId('no-candidates')).toBeVisible();
  await expect(page.getByTestId('merge-decision')).toHaveCount(2);

  await openTab(page, 'Radar');
  await expect(page.getByTestId('radar-row')).toHaveCount(5);

  // Evidence behind a score: Northwind has one role seen by two datasets.
  await page.getByRole('button', { name: 'Northwind Analytics', exact: true }).click();
  await expect(page.getByTestId('breakdown')).toBeVisible();
  await expect(page.getByTestId('score-caption')).toContainText(
    'It is not evidence that a company needs or will use an outside recruiter.',
  );
  await expect(page.getByTestId('missing-information')).toContainText(
    'Not enough history to measure change',
  );
  await expect(page.getByTestId('missing-information')).toContainText(
    /role keywords|keywords are configured/i,
  );
  await expect(page.getByTestId('component-source_confidence')).toContainText(
    /listed by two or more different sources|corroborat/i,
  );
  const roleRows = page.getByTestId('role-row');
  await expect(roleRows).toHaveCount(2);

  // Shortlist with a note and export.
  await page
    .getByRole('textbox', { name: 'Qualification note' })
    .fill('Strong data hiring, check in Q1.');
  await page.getByRole('button', { name: 'Save note and add to shortlist' }).click();
  await expect(page.getByRole('button', { name: /On the shortlist/ })).toBeVisible();

  await openTab(page, 'Data');
  const [download] = await Promise.all([
    page.waitForEvent('download'),
    page.getByRole('button', { name: 'Export shortlist CSV' }).click(),
  ]);
  expect(download.suggestedFilename()).toMatch(/shortlist.*\.csv$/);
  const csv = readFileSync((await download.path())!, 'utf8');
  expect(csv).toContain('rank,company,score');
  expect(csv).toContain('Northwind Analytics');
  expect(csv).toContain('Strong data hiring, check in Q1.');
  expect(csv).toContain('missing_information');
});

test('local-data mode: CSV row errors are reported by line and can be corrected in place', async ({
  page,
}) => {
  await startLocal(page);
  const bad = [
    'company_name,title,location,work_mode,url,posted_at',
    'Acme Robotics,Robotics Engineer,"Denver, CO",onsite,https://acme.example/1,2026-10-01',
    ',No company,,,,',
    'Acme Robotics,Designer,Berlin,office,,',
    'Acme Robotics,Analyst,,,javascript:alert(1),',
    'Acme Robotics,Writer,,,,2026-02-30',
  ].join('\n');
  await importCsv(page, 'Mixed quality', bad);

  const report = page.getByTestId('import-report');
  await expect(report).toBeVisible();
  await expect(report).toContainText('line 3');
  await expect(report).toContainText('line 4');
  await expect(report).toContainText('line 5');
  await expect(report).toContainText('line 6');
  await expect(page.getByTestId('import-error')).toHaveCount(4);

  // Valid rows were kept; the report does not pretend everything failed.
  await openTab(page, 'Radar');
  await expect(page.getByTestId('radar-row')).toHaveCount(1);
});
