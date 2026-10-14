import { expect, test, type Page } from '@playwright/test';
import { CSV_A, importCsv, mainNav, openTab, startLocal } from './helpers';

const TABS = ['Radar', 'Data', 'Sources', 'Settings', 'About'] as const;

async function loadSample(page: Page) {
  await openTab(page, 'Data');
  await page.getByRole('button', { name: 'Load sample data' }).click();
  await expect(page.getByTestId('sample-banner').first()).toBeVisible();
}

test.describe('backend offline', () => {
  test('an unreachable backend is explained and local-data mode keeps working', async ({
    page,
  }) => {
    await page.goto('./');
    await openTab(page, 'Settings');
    const address = page.getByRole('textbox', { name: 'Backend address' });
    await address.fill('http://127.0.0.1:59999');
    await page.getByRole('button', { name: 'Save and check connection' }).click();
    await expect(page.getByTestId('connection-status')).toContainText(
      /not reachable|offline|no answer/i,
    );
    await page.getByRole('radio', { name: 'Use the backend' }).check();

    // Falls back to local-data mode with a visible warning instead of failing silently.
    await expect(page.getByTestId('current-mode')).toContainText(/local-data mode/i);
    await openTab(page, 'Sources');
    await expect(page.getByTestId('sources-local')).toBeVisible();
    await expect(page.getByTestId('backend-state')).toContainText(
      /not reachable|offline|no answer/i,
    );

    // Everything local still works.
    await importCsv(page, 'Offline import', CSV_A);
    await openTab(page, 'Radar');
    await expect(page.getByTestId('radar-row').first()).toBeVisible();
  });
});

test.describe('persistence and recovery (local-data mode)', () => {
  test('data survives a reload; a corrupt workspace is recovered with a backup, not a crash', async ({
    page,
  }) => {
    await startLocal(page);
    await importCsv(page, 'Board A', CSV_A);
    await page.reload();
    await openTab(page, 'Radar');
    await expect(page.getByTestId('radar-row').first()).toBeVisible();
    const before = await page.getByTestId('radar-row').count();
    expect(before).toBeGreaterThan(0);

    await page.evaluate(() => localStorage.setItem('recruit-radar.workspace', '{"broken": '));
    await page.reload();
    await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
    await expect(page.getByTestId('notice-corrupt_recovered')).toBeVisible();
    await expect(page.getByTestId('notice-corrupt_recovered')).toContainText(
      'A copy of it was kept',
    );
    const backup = await page.evaluate(() =>
      localStorage.getItem('recruit-radar.workspace.unreadable-backup'),
    );
    expect(backup).toBe('{"broken": ');
    // The app is usable again.
    await importCsv(page, 'After recovery', CSV_A);
    await openTab(page, 'Radar');
    await expect(page.getByTestId('radar-row').first()).toBeVisible();
  });
});

test.describe('accessibility and layout', () => {
  test('keyboard only: skip link, tab order reaches navigation and a company, focus is visible', async ({
    page,
  }) => {
    await startLocal(page);
    await loadSample(page);
    await openTab(page, 'Radar');

    // A fresh load starts keyboard focus at the top of the document: the skip link is first.
    await page.reload();
    await expect(page.getByTestId('radar-row').first()).toBeVisible();
    await page.keyboard.press('Tab');
    await expect(page.getByRole('link', { name: 'Skip to main content' })).toBeFocused();
    await page.keyboard.press('Enter');
    await expect(page.locator('#main')).toBeFocused();

    // Walk the tab order from there; every stop must show a focus indicator.
    const invisible: string[] = [];
    for (let i = 0; i < 25; i += 1) {
      await page.keyboard.press('Tab');
      const info = await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el || el === document.body) return null;
        const s = getComputedStyle(el);
        const outline = s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0;
        const shadow = s.boxShadow !== 'none';
        return {
          label: (el.getAttribute('aria-label') || el.textContent || el.tagName)
            .trim()
            .slice(0, 40),
          visible: outline || shadow,
        };
      });
      if (info && !info.visible) invisible.push(info.label);
    }
    expect(invisible).toEqual([]);

    // Enter on a company name opens the detail; the back button returns to the radar.
    await page.getByRole('button', { name: 'Back to the radar' }).count();
    const first = page.getByTestId('radar-row').first().getByRole('button').first();
    await first.focus();
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('breakdown')).toBeVisible();
    await page.getByRole('button', { name: 'Back to the radar' }).focus();
    await page.keyboard.press('Enter');
    await expect(page.getByTestId('radar-row').first()).toBeVisible();
  });

  test('every control on every tab has an accessible name', async ({ page }) => {
    await startLocal(page);
    await loadSample(page);
    for (const tab of TABS) {
      await openTab(page, tab);
      const unnamed = await page.evaluate(() => {
        const bad: string[] = [];
        const nameOf = (el: Element): string => {
          const aria = el.getAttribute('aria-label');
          if (aria?.trim()) return aria.trim();
          const by = el.getAttribute('aria-labelledby');
          if (by) {
            const text = by
              .split(/\s+/)
              .map((id) => document.getElementById(id)?.textContent ?? '')
              .join(' ')
              .trim();
            if (text) return text;
          }
          const labels = (el as HTMLInputElement).labels;
          if (labels && labels.length > 0)
            return Array.from(labels)
              .map((l) => l.textContent ?? '')
              .join(' ')
              .trim();
          return (el.textContent ?? '').trim();
        };
        document.querySelectorAll('button, input, select, textarea, a[href]').forEach((el) => {
          if ((el as HTMLInputElement).type === 'hidden') return;
          if (!nameOf(el)) bad.push(el.outerHTML.slice(0, 100));
        });
        return bad;
      });
      expect(unnamed, `unnamed controls on ${tab}`).toEqual([]);
    }
  });

  for (const width of [375, 320]) {
    test(`no horizontal page overflow at ${width}px on any tab`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await startLocal(page);
      await loadSample(page);
      for (const tab of TABS) {
        await openTab(page, tab);
        const overflow = await page.evaluate(
          () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
        );
        expect(overflow, `${tab} overflows at ${width}px`).toBeLessThanOrEqual(0);
      }
    });
  }

  for (const scheme of ['light', 'dark'] as const) {
    test(`text contrast meets WCAG AA in ${scheme} mode`, async ({ page }) => {
      await page.emulateMedia({ colorScheme: scheme });
      await startLocal(page);
      await loadSample(page);
      const failures: string[] = [];
      for (const tab of TABS) {
        await openTab(page, tab);
        const found = await page.evaluate(() => {
          const parse = (c: string): [number, number, number, number] => {
            const m = c.match(/rgba?\(([^)]+)\)/);
            if (!m) return [0, 0, 0, 0];
            const p = m[1]!
              .split(/[ ,/]+/)
              .filter(Boolean)
              .map(Number);
            return [p[0] ?? 0, p[1] ?? 0, p[2] ?? 0, p[3] ?? 1];
          };
          const lum = ([r, g, b]: number[]) => {
            const f = (v: number) => {
              const s = v / 255;
              return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
            };
            return 0.2126 * f(r!) + 0.7152 * f(g!) + 0.0722 * f(b!);
          };
          const backgroundOf = (el: Element): [number, number, number] => {
            let node: Element | null = el;
            while (node) {
              const [r, g, b, a] = parse(getComputedStyle(node).backgroundColor);
              if (a >= 0.99) return [r, g, b];
              node = node.parentElement;
            }
            return [255, 255, 255];
          };
          const bad: string[] = [];
          const seen = new Set<string>();
          const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
          while (walker.nextNode()) {
            const node = walker.currentNode;
            const text = (node.textContent ?? '').trim();
            const el = node.parentElement;
            if (!text || !el) continue;
            const style = getComputedStyle(el);
            if (style.visibility === 'hidden' || style.display === 'none') continue;
            if (el.closest('.sr-only')) continue;
            if (el.closest('[disabled], [aria-disabled="true"]')) continue;
            const [fr, fg, fb, fa] = parse(style.color);
            const [br, bg, bb] = backgroundOf(el);
            const mix = [fr * fa + br * (1 - fa), fg * fa + bg * (1 - fa), fb * fa + bb * (1 - fa)];
            const l1 = lum(mix);
            const l2 = lum([br, bg, bb]);
            const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
            const size = parseFloat(style.fontSize);
            const bold = parseInt(style.fontWeight, 10) >= 700;
            const large = size >= 24 || (size >= 18.66 && bold);
            const need = large ? 3 : 4.5;
            const key = `${style.color}|${br},${bg},${bb}|${large}`;
            if (ratio < need && !seen.has(key)) {
              seen.add(key);
              bad.push(
                `${ratio.toFixed(2)} < ${need} "${text.slice(0, 40)}" (${el.tagName.toLowerCase()}.${el.className})`,
              );
            }
          }
          return bad;
        });
        for (const f of found) failures.push(`${tab}: ${f}`);
      }
      expect(failures).toEqual([]);
    });
  }

  test('honesty copy: score caption, no recruiter-need claims, no hiring-pain wording', async ({
    page,
  }) => {
    await startLocal(page);
    await loadSample(page);
    await openTab(page, 'Radar');
    await expect(page.getByTestId('score-caption').first()).toContainText(
      'Priority score = observed hiring activity in the roles you configured, from the sources you loaded. It is not evidence that a company needs or will use an outside recruiter.',
    );
    await page
      .getByRole('button', { name: /Tidewater Systems/ })
      .first()
      .click();
    await expect(
      page
        .getByText('Possible urgency signal (aged postings) — not evidence of hiring difficulty.')
        .first(),
    ).toBeVisible();
    for (const tab of TABS) {
      await openTab(page, tab);
      const text = (await page.locator('main').innerText()).toLowerCase();
      for (const forbidden of [
        'struggling to hire',
        'desperate',
        'will pay',
        'needs a recruiter',
        'hiring pain',
      ]) {
        if (tab === 'About') {
          // The method page may *deny* these claims ("never says or implies ... will pay ...");
          // every sentence mentioning one must be a negation.
          for (const sentence of text.split(/(?<=[.!?])\s+/)) {
            if (!sentence.includes(forbidden)) continue;
            expect(sentence, `About asserts "${forbidden}"`).toMatch(
              /\b(never|not|no|nor|without)\b/,
            );
          }
        } else {
          expect(text, `${tab} contains "${forbidden}"`).not.toContain(forbidden);
        }
      }
    }
  });
});

test('navigation stays operable: every tab opens and the active tab is announced', async ({
  page,
}) => {
  await startLocal(page);
  for (const tab of TABS) {
    await mainNav(page).getByRole('button', { name: tab }).click();
    await expect(page.getByRole('heading', { level: 1, name: tab })).toBeVisible();
    await expect(mainNav(page).getByRole('button', { name: tab })).toHaveAttribute(
      'aria-current',
      'page',
    );
  }
});

test('an unexpected rendering error shows an explanation, not a blank page', async ({ page }) => {
  await startLocal(page);
  await loadSample(page);
  await openTab(page, 'Radar');
  await expect(page.getByTestId('radar-row').first()).toBeVisible();

  // Make the next render throw: ordering the radar rows is part of drawing the table.
  await page.evaluate(() => {
    Array.prototype.sort = function failingSort(): never {
      throw new Error('simulated rendering failure');
    };
  });
  await page
    .getByRole('button', { name: /^Active roles/ })
    .first()
    .click();

  const fallback = page.getByTestId('render-error');
  await expect(fallback).toBeVisible();
  await expect(fallback).toContainText('Something went wrong');
  await expect(fallback).toContainText('Nothing you stored was changed');
  await expect(fallback).toContainText('simulated rendering failure');
  await expect(fallback.getByRole('button', { name: 'Reload the page' })).toBeVisible();

  // Rendering never touches storage: after a reload the same data is back.
  await page.reload();
  await expect(page.getByTestId('radar-row').first()).toBeVisible();
});
