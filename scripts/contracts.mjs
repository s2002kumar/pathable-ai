#!/usr/bin/env node
/**
 * Contract pipeline: Pydantic schemas -> OpenAPI -> TypeScript.
 *
 *   node scripts/contracts.mjs generate   regenerate the committed artifacts
 *   node scripts/contracts.mjs check      fail if the committed artifacts are stale
 *
 * `check` regenerates into a temporary directory and compares bytes, so it works
 * on a clean checkout and does not depend on git state.
 */
import { spawn } from 'node:child_process';
import { mkdtemp, readFile, rm, writeFile } from 'node:fs/promises';
import { existsSync } from 'node:fs';
import { createRequire } from 'node:module';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { runUv } from './uv.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const contractsDir = path.join(repoRoot, 'packages', 'contracts');

const OPENAPI_PATH = path.join(contractsDir, 'openapi.json');
const TYPES_PATH = path.join(contractsDir, 'src', 'generated', 'api.ts');

const BANNER = `/**
 * GENERATED FILE — DO NOT EDIT.
 *
 * Produced from the PathAble API OpenAPI document by:
 *     pnpm contracts:generate
 *
 * The Pydantic response models in services/api/src/pathable_api/schemas are the
 * source of truth. Edit those, regenerate, and commit the result. CI fails if
 * this file does not match what the backend currently produces.
 */

`;

/**
 * Absolute path to the openapi-typescript CLI entry point.
 *
 * Resolved and executed with `node` directly rather than going through
 * `pnpm exec`: on Windows, Node refuses to spawn a `.cmd` shim without a shell
 * (EINVAL, since the CVE-2024-27980 fix), and spawning through a shell with a
 * separate args array is itself deprecated. Running the JS entry point avoids
 * both, and skips a process launch.
 */
function resolveOpenApiTypescriptCli() {
  const anchor = pathToFileURL(path.join(contractsDir, 'package.json')).href;
  const require = createRequire(anchor);
  const manifestPath = require.resolve('openapi-typescript/package.json');
  const manifest = require('openapi-typescript/package.json');
  const binField = manifest.bin;
  const relative = typeof binField === 'string' ? binField : binField['openapi-typescript'];
  return path.join(path.dirname(manifestPath), relative);
}

function run(command, args, options = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, args, {
      cwd: options.cwd ?? repoRoot,
      stdio: options.stdio ?? 'inherit',
      shell: false,
    });
    child.on('error', (error) => {
      process.stderr.write(`Failed to run ${command}: ${error.message}\n`);
      resolve(1);
    });
    child.on('close', (code) => resolve(code ?? 1));
  });
}

/** Export the OpenAPI document from the backend to `destination`. */
async function exportOpenApi(destination) {
  const code = await runUv(['run', 'python', '-m', 'pathable_api.openapi_export', destination]);
  if (code !== 0) {
    throw new Error(
      'OpenAPI export failed. Is the backend installed? Try `pnpm bootstrap`, or ' +
        '`uv sync` inside services/api.',
    );
  }
}

/** Generate TypeScript types from an OpenAPI document. */
async function generateTypes(openapiPath, destination) {
  const code = await run(process.execPath, [
    resolveOpenApiTypescriptCli(),
    openapiPath,
    '--output',
    destination,
  ]);
  if (code !== 0) {
    throw new Error('openapi-typescript failed. Run `pnpm install` and try again.');
  }

  // openapi-typescript emits its own short header; prepend the PathAble banner so
  // the provenance and the regeneration command are impossible to miss.
  const generated = await readFile(destination, 'utf8');
  if (!generated.startsWith('/**\n * GENERATED FILE')) {
    await writeFile(destination, BANNER + generated.replace(/^﻿/, ''), 'utf8');
  }
}

async function generate() {
  await exportOpenApi(OPENAPI_PATH);
  await generateTypes(OPENAPI_PATH, TYPES_PATH);
  console.log(`\n✓ Contracts regenerated:\n  ${OPENAPI_PATH}\n  ${TYPES_PATH}`);
}

async function check() {
  for (const [label, file] of [
    ['OpenAPI document', OPENAPI_PATH],
    ['TypeScript contracts', TYPES_PATH],
  ]) {
    if (!existsSync(file)) {
      console.error(`✗ ${label} is missing: ${file}\n  Run: pnpm contracts:generate`);
      process.exit(1);
    }
  }

  const scratch = await mkdtemp(path.join(tmpdir(), 'pathable-contracts-'));
  try {
    const freshOpenApi = path.join(scratch, 'openapi.json');
    const freshTypes = path.join(scratch, 'api.ts');

    await exportOpenApi(freshOpenApi);
    await generateTypes(freshOpenApi, freshTypes);

    const comparisons = [
      ['OpenAPI document', OPENAPI_PATH, freshOpenApi],
      ['TypeScript contracts', TYPES_PATH, freshTypes],
    ];

    const stale = [];
    for (const [label, committedPath, freshPath] of comparisons) {
      const [committed, fresh] = await Promise.all([
        readFile(committedPath, 'utf8'),
        readFile(freshPath, 'utf8'),
      ]);
      if (normalise(committed) !== normalise(fresh)) {
        stale.push({ label, committedPath, committed, fresh });
      }
    }

    if (stale.length > 0) {
      console.error('\n✗ Generated contracts are out of date.\n');
      for (const entry of stale) {
        console.error(`  ${entry.label}: ${path.relative(repoRoot, entry.committedPath)}`);
        console.error(firstDifference(entry.committed, entry.fresh));
      }
      console.error('\n  Fix with: pnpm contracts:generate  (then commit the result)\n');
      process.exit(1);
    }

    console.log('✓ Generated contracts match the backend schemas.');
  } finally {
    await rm(scratch, { recursive: true, force: true });
  }
}

/** Line endings differ between a Windows checkout and Linux CI; content does not. */
function normalise(text) {
  return text.replace(/\r\n/g, '\n');
}

/** Point at the first differing line so the failure is actionable in CI logs. */
function firstDifference(committed, fresh) {
  const committedLines = normalise(committed).split('\n');
  const freshLines = normalise(fresh).split('\n');
  const limit = Math.max(committedLines.length, freshLines.length);

  for (let index = 0; index < limit; index += 1) {
    if (committedLines[index] !== freshLines[index]) {
      return [
        `    first difference at line ${index + 1}:`,
        `      committed: ${JSON.stringify(committedLines[index] ?? '<end of file>')}`,
        `      expected:  ${JSON.stringify(freshLines[index] ?? '<end of file>')}`,
      ].join('\n');
    }
  }
  return '    files differ only in trailing content';
}

const command = process.argv[2];
try {
  if (command === 'generate') {
    await generate();
  } else if (command === 'check') {
    await check();
  } else {
    console.error('Usage: node scripts/contracts.mjs <generate|check>');
    process.exit(2);
  }
} catch (error) {
  console.error(`\n✗ ${error.message}\n`);
  process.exit(1);
}
