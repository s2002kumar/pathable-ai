#!/usr/bin/env node
/**
 * One-shot local setup: JavaScript workspace + Python environment.
 *
 * Equivalent to running `pnpm install` followed by `uv sync` inside
 * services/api. Exposed as `pnpm bootstrap` rather than `pnpm install`
 * because `install` is a reserved npm lifecycle script name and defining it
 * would make `pnpm install` recurse into itself.
 */
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { pnpmCommand, runUv } from './uv.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

function run(command) {
  return new Promise((resolve) => {
    // A single command string with shell:true — see pnpmCommand() for why.
    const child = spawn(command, [], { cwd: repoRoot, stdio: 'inherit', shell: true });
    child.on('error', () => resolve(1));
    child.on('close', (code) => resolve(code ?? 1));
  });
}

const frozen = process.argv.includes('--frozen');

console.log('→ Installing JavaScript workspace dependencies (pnpm)');
const pnpmCode = await run(pnpmCommand(frozen ? ['install', '--frozen-lockfile'] : ['install']));
if (pnpmCode !== 0) process.exit(pnpmCode);

console.log('\n→ Installing Python dependencies (uv)');
const uvCode = await runUv(frozen ? ['sync', '--frozen'] : ['sync']);
if (uvCode !== 0) process.exit(uvCode);

console.log('\n→ Installing Playwright browsers (chromium)');
const pwCode = await run(
  pnpmCommand([
    '--filter',
    '@pathable/web',
    'exec',
    'playwright',
    'install',
    '--with-deps',
    'chromium',
  ]),
);
if (pwCode !== 0) {
  console.warn(
    '\n! Playwright browser install failed. End-to-end tests will not run until\n' +
      '  `pnpm --filter @pathable/web exec playwright install chromium` succeeds.\n' +
      '  Everything else is ready.',
  );
}

console.log('\n✓ Bootstrap complete. Next: cp .env.example .env && pnpm dev');
