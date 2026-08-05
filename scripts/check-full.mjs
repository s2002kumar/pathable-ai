#!/usr/bin/env node
/**
 * The complete verification gate.
 *
 *   pnpm check       fast developer gate — no database, no browsers
 *   pnpm check:full  everything, including real PostGIS and browser tests
 *
 * The distinction matters because P0-A01 was once reported as "all checks pass"
 * while the integration tests had never executed: `pnpm check` deliberately
 * excludes them, and that exclusion was invisible in the output.
 *
 * This command therefore **fails loudly when its prerequisites are missing**. It
 * never skips a suite quietly — a green run here has to mean the database was
 * real and the browser tests actually ran.
 */
import { spawn } from 'node:child_process';
import net from 'node:net';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { pnpmCommand, runUv } from './uv.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');

const GREEN = '\u001b[32m';
const RED = '\u001b[31m';
const DIM = '\u001b[2m';
const RESET = '\u001b[0m';

function run(command, { cwd = repoRoot } = {}) {
  return new Promise((resolve) => {
    const child = spawn(command, [], { cwd, stdio: 'inherit', shell: true });
    child.on('error', () => resolve(1));
    child.on('close', (code) => resolve(code ?? 1));
  });
}

/** Reachability check that does not need a database driver. */
function canConnect(host, port, timeoutMs = 3000) {
  return new Promise((resolve) => {
    const socket = new net.Socket();
    const done = (result) => {
      socket.destroy();
      resolve(result);
    };
    socket.setTimeout(timeoutMs);
    socket.once('connect', () => done(true));
    socket.once('timeout', () => done(false));
    socket.once('error', () => done(false));
    socket.connect(port, host);
  });
}

function parseDatabaseUrl(url) {
  try {
    // postgresql+psycopg://user:pass@host:port/db -> strip the driver for URL().
    const normalised = url.replace(/^postgresql\+\w+:/, 'postgresql:');
    const parsed = new URL(normalised);
    return { host: parsed.hostname, port: Number(parsed.port || 5432) };
  } catch {
    return null;
  }
}

// ---------------------------------------------------------------------------
// Preconditions — checked up front so failures are immediate and explicit.
// ---------------------------------------------------------------------------
console.log(`${DIM}Checking prerequisites for the full gate…${RESET}`);

const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl) {
  console.error(
    `\n${RED}✗ DATABASE_URL is not set.${RESET}\n\n` +
      '  The full gate runs the PostGIS integration suite and the full-stack browser\n' +
      '  tests against a real database. It will not fall back to mocks.\n\n' +
      '    docker compose up -d db\n' +
      '    export DATABASE_URL="postgresql+psycopg://pathable:pathable_local_dev_only@localhost:5433/pathable"\n' +
      '    uv --directory services/api run alembic upgrade head\n\n' +
      '  Use `pnpm check` for the fast gate that does not need a database.\n',
  );
  process.exit(1);
}

const target = parseDatabaseUrl(databaseUrl);
if (target === null) {
  console.error(`\n${RED}✗ DATABASE_URL is not a URL that can be parsed.${RESET}\n`);
  process.exit(1);
}

if (!(await canConnect(target.host, target.port))) {
  console.error(
    `\n${RED}✗ Nothing is listening on ${target.host}:${target.port}.${RESET}\n\n` +
      '  DATABASE_URL is set but the database is unreachable, so the integration\n' +
      '  suite cannot run. Start it and try again — this gate fails rather than\n' +
      '  silently skipping, which is the entire reason it exists.\n',
  );
  process.exit(1);
}

console.log(`${GREEN}✓${RESET} database reachable at ${target.host}:${target.port}\n`);

// ---------------------------------------------------------------------------
// Steps
// ---------------------------------------------------------------------------
const steps = [
  ['Prettier', () => run(pnpmCommand(['exec', 'prettier', '--check', '.']))],
  ['Ruff format', () => runUv(['run', 'ruff', 'format', '--check', '.'])],
  ['Ruff lint', () => runUv(['run', 'ruff', 'check', '.'])],
  ['ESLint', () => run(pnpmCommand(['--filter', '@pathable/web', 'lint']))],
  ['TypeScript', () => run(pnpmCommand(['-r', '--if-present', 'typecheck']))],
  ['mypy', () => runUv(['run', 'mypy', 'src', 'tests'])],
  ['Backend unit tests', () => runUv(['run', 'pytest', 'tests/unit'])],
  ['Backend integration tests (real PostGIS)', () => runUv(['run', 'pytest', 'tests/integration'])],
  ['Frontend unit tests', () => run(pnpmCommand(['--filter', '@pathable/web', 'test:unit']))],
  ['Contract drift', () => run(pnpmCommand(['run', 'contracts:check']))],
  ['Production build', () => run(pnpmCommand(['run', 'build']))],
  [
    'Browser tests (deterministic)',
    () => run(pnpmCommand(['--filter', '@pathable/web', 'test:e2e'])),
  ],
  [
    'Browser tests (full stack, no stubs)',
    () => run(pnpmCommand(['--filter', '@pathable/web', 'test:e2e:fullstack'])),
  ],
  [
    'Python dependency audit',
    () =>
      runUv([
        'run',
        '--with',
        'pip-audit',
        'pip-audit',
        '--strict',
        '--progress-spinner',
        'off',
        '-r',
        'requirements-audit.txt',
      ]),
  ],
];

const results = [];
let failed = false;

for (const [name, execute] of steps) {
  console.log(`\n${DIM}────────── ${name} ──────────${RESET}`);

  // The audit step needs its input generated first.
  if (name === 'Python dependency audit') {
    const exported = await runUv([
      'export',
      '--frozen',
      '--no-emit-project',
      '--no-hashes',
      '--all-groups',
      '-o',
      'requirements-audit.txt',
    ]);
    if (exported !== 0) {
      results.push([name, false]);
      failed = true;
      continue;
    }
  }

  const started = Date.now();
  const code = await execute();
  const seconds = ((Date.now() - started) / 1000).toFixed(1);
  const ok = code === 0;

  results.push([name, ok, seconds]);
  if (!ok) failed = true;
}

console.log(`\n${DIM}══════════ summary ══════════${RESET}`);
for (const [name, ok, seconds] of results) {
  const mark = ok ? `${GREEN}PASS${RESET}` : `${RED}FAIL${RESET}`;
  console.log(`  ${mark}  ${name}${seconds ? ` ${DIM}(${seconds}s)${RESET}` : ''}`);
}

if (failed) {
  console.error(`\n${RED}✗ Full gate failed.${RESET}\n`);
  process.exit(1);
}

console.log(`\n${GREEN}✓ Full gate passed.${RESET}\n`);
