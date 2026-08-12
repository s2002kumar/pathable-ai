import nextCoreWebVitals from 'eslint-config-next/core-web-vitals';
import nextTypeScript from 'eslint-config-next/typescript';

// eslint-config-next 16 ships native flat configs, so no eslintrc compatibility
// shim is needed (and FlatCompat cannot load them — it fails on the plugin
// object's circular references).
const config = [
  {
    ignores: [
      '.next/**',
      'coverage/**',
      'test-results/**',
      'test-results-fullstack/**',
      'playwright-report/**',
      'playwright-report-fullstack/**',
      'next-env.d.ts',
      // Vendored MapLibre worker, copied verbatim from node_modules by
      // scripts/sync-maplibre-worker.mjs. Minified third-party code that we
      // neither author nor edit.
      'public/maplibre/**',
    ],
  },
  ...nextCoreWebVitals,
  ...nextTypeScript,
  {
    rules: {
      // A silently discarded promise in a map lifecycle or a fetch is a real bug
      // class here, so unused values must be named deliberately.
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_', caughtErrorsIgnorePattern: '^_' },
      ],
      // `any` would hollow out the generated contracts, which are the whole point
      // of the contracts package.
      '@typescript-eslint/no-explicit-any': 'error',
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      eqeqeq: ['error', 'always', { null: 'ignore' }],
    },
  },
  {
    files: [
      'tests/e2e/**/*.ts',
      'tests/fullstack/**/*.ts',
      'src/test/**/*.ts',
      '**/*.test.ts',
      '**/*.test.tsx',
    ],
    rules: {
      'no-console': 'off',
    },
  },
];

export default config;
