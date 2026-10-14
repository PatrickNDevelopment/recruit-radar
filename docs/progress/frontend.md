# Frontend progress (role: frontend)

Owner area: `src/data/**`, `src/ui/**`, `src/main.tsx`, `src/App.tsx`, `src/styles.css`, `index.html`,
`tests/ui-*.test.ts`, `tests/data-*.test.ts`, `docs/spec/ambiguities/frontend.md`.

## Plan (milestones)

1. M1 data layer: types, errors, storage, LocalSource, RemoteSource, connection, sample, derive, prefs.
2. M2 data-layer unit tests (vitest).
3. M3 view-model + session store (pure TypeScript, no React) and their tests.
4. M4 React shell, styles, Radar + Company detail.
5. M5 Data (manual, CSV + correction, datasets, export, merge review), Sources, Settings, About.
6. M6 verification: tsc, eslint, prettier, vitest, build, Playwright run against `npm run preview`
   (port 4174), screenshots at 1366x900 and 390x844, fix what looks broken.

## Status

- [x] M1 data layer (`src/data/*`, `src/data/source.ts` is the public entry point)
- [x] M2 data-layer tests (`tests/data-*.test.ts`)
- [x] M3 `src/data/session.ts` (SessionStore = connection manager), `src/ui/viewModel.ts`,
      tests `tests/data-session.test.ts`, `tests/ui-viewmodel.test.ts`
- [ ] M4 React shell + Radar + Company detail
- [ ] M5 Data / Sources / Settings / About screens
- [ ] M6 verification + screenshots

## Verify commands

```
npx tsc --noEmit
npx eslint src tests
npx prettier --check src tests index.html docs/progress/frontend.md
npx vitest run
npm run build
```

Note: `tsc` may report an error in `tests/identity.test.ts` (engine agent's file, not owned here).
