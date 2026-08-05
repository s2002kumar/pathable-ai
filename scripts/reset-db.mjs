#!/usr/bin/env node
/**
 * Destroy the local database volume.
 *
 * Deliberately separate from `docker compose down`, and deliberately interactive:
 * `down -v` is one keystroke away from `down` and there is no undo. Once the
 * project stores collected accessibility reports, an accidental wipe stops being
 * an inconvenience.
 */
import { spawn } from 'node:child_process';
import { createInterface } from 'node:readline/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const VOLUME = 'pathable-db-data';

function run(command, args) {
  return new Promise((resolve) => {
    const child = spawn(command, args, { cwd: repoRoot, stdio: 'inherit', shell: false });
    child.on('error', () => resolve(1));
    child.on('close', (code) => resolve(code ?? 1));
  });
}

const force = process.argv.includes('--yes') || process.argv.includes('-y');

if (!force) {
  console.log(`\nThis will permanently delete the "${VOLUME}" volume and every`);
  console.log('row in your local PathAble database. Migrations will re-run from');
  console.log('an empty database on the next start.\n');

  const rl = createInterface({ input: process.stdin, output: process.stdout });
  const answer = await rl.question('Type "delete" to confirm: ');
  rl.close();

  if (answer.trim().toLowerCase() !== 'delete') {
    console.log('Cancelled. Nothing was deleted.');
    process.exit(0);
  }
}

console.log('\n→ Stopping the stack and removing volumes');
const code = await run('docker', ['compose', 'down', '-v']);
if (code !== 0) {
  console.error('\ndocker compose down failed. Is Docker running?');
  process.exit(code);
}

console.log('\n✓ Local database data deleted. Run `pnpm docker:up` to start fresh.');
