import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

// GitHub Pages project site: https://<user>.github.io/recruit-radar/
export default defineConfig({
  base: '/recruit-radar/',
  plugins: [react()],
  test: {
    include: ['tests/**/*.test.ts'],
    environment: 'node',
    // The randomized invariant suites replay hundreds of generated inputs; on a busy or small CI
    // runner they exceed vitest's 5 s default (seen once under load in acceptance testing).
    testTimeout: 30_000,
  },
});
