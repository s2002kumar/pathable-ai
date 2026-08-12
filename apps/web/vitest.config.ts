import { fileURLToPath } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    // Playwright owns tests/e2e; running them here would spawn browsers inside
    // the unit-test run.
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
    restoreMocks: true,
    clearMocks: true,
    coverage: {
      provider: 'v8',
      reporter: ['text', 'lcov', 'json-summary'],
      reportsDirectory: './coverage',
      include: ['src/**/*.{ts,tsx}'],
      exclude: [
        // Generated from the backend OpenAPI document — not authored here.
        '**/generated/**',
        // Test scaffolding and the tests themselves.
        'src/test/**',
        '**/*.test.{ts,tsx}',
        // Type-only modules compile away to nothing, so they cannot be covered.
        '**/*.d.ts',
        'src/**/types.ts',
        // Framework boilerplate: a static <html> shell plus exported metadata and
        // viewport objects. There is no branch or behaviour to assert that would
        // not simply restate the literal, and rendering a root <html> element
        // inside jsdom tests the framework rather than this project.
        'src/app/layout.tsx',
      ],
      thresholds: {
        statements: 80,
        branches: 80,
        functions: 80,
        lines: 80,
      },
    },
  },
});
