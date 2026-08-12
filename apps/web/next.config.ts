import { fileURLToPath } from 'node:url';
import type { NextConfig } from 'next';

// Standalone output is opt-in (the Dockerfile sets it) rather than always on:
// `next start` refuses to serve a standalone build, and that is exactly how the
// e2e suite and `pnpm start` run the app locally.
const standalone = process.env.NEXT_OUTPUT_STANDALONE === '1';

const config: NextConfig = {
  // Emits a minimal self-contained server bundle, which keeps the runtime Docker
  // stage free of node_modules and the build toolchain.
  ...(standalone ? { output: 'standalone' as const } : {}),

  // The monorepo root, not apps/web, so standalone tracing picks up the pnpm
  // virtual store correctly. `fileURLToPath`, not `.pathname`: on Windows the
  // latter yields "/C:/..." with a leading slash, which Next cannot canonicalise.
  outputFileTracingRoot: fileURLToPath(new URL('../../', import.meta.url)),

  reactStrictMode: true,

  // Never leak framework details or an exact version in response headers.
  poweredByHeader: false,

  typescript: {
    // The build must not be the place type errors are discovered, but it must
    // also never be the place they are ignored.
    ignoreBuildErrors: false,
  },

  async headers() {
    return [
      {
        source: '/:path*',
        headers: [
          { key: 'X-Content-Type-Options', value: 'nosniff' },
          { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
          { key: 'X-Frame-Options', value: 'DENY' },
          {
            // Phase 0 collects no location, camera or microphone data, so the
            // browser is told to refuse those outright.
            key: 'Permissions-Policy',
            value: 'geolocation=(), camera=(), microphone=(), interest-cohort=()',
          },
        ],
      },
    ];
  },
};

export default config;
