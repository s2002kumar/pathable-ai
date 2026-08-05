#!/usr/bin/env node
/**
 * Runs the API and the web app together for native (non-Docker) development.
 *
 * Deliberately dependency-free rather than pulling in `concurrently`: the only
 * behaviour needed is prefixed output plus a single Ctrl+C that stops both
 * children, which is ~40 lines.
 */
import { spawn } from 'node:child_process';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { pnpmCommand, resolveUv } from './uv.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const apiDir = path.join(repoRoot, 'services', 'api');

const COLOURS = { api: '\u001b[36m', web: '\u001b[35m', reset: '\u001b[0m' };

const targets = [
  {
    name: 'api',
    command: resolveUv(),
    args: [
      'run',
      'uvicorn',
      'pathable_api.main:app',
      '--reload',
      '--host',
      '127.0.0.1',
      '--port',
      '8000',
    ],
    cwd: apiDir,
    shell: false,
  },
  {
    name: 'web',
    command: pnpmCommand(['--filter', '@pathable/web', 'dev']),
    args: [],
    cwd: repoRoot,
    shell: true,
  },
];

const children = [];
let shuttingDown = false;

function prefix(name, chunk) {
  const tag = `${COLOURS[name]}[${name}]${COLOURS.reset} `;
  return chunk
    .toString()
    .split('\n')
    .filter((line, index, all) => line.length > 0 || index < all.length - 1)
    .map((line) => tag + line)
    .join('\n');
}

function shutdown(code) {
  if (shuttingDown) return;
  shuttingDown = true;
  for (const child of children) {
    if (!child.killed) child.kill('SIGTERM');
  }
  setTimeout(() => process.exit(code), 500);
}

for (const target of targets) {
  const child = spawn(target.command, target.args, {
    cwd: target.cwd,
    shell: target.shell,
    stdio: ['ignore', 'pipe', 'pipe'],
  });
  child.stdout.on('data', (chunk) => console.log(prefix(target.name, chunk)));
  child.stderr.on('data', (chunk) => console.error(prefix(target.name, chunk)));
  child.on('error', (error) =>
    console.error(prefix(target.name, `failed to start: ${error.message}`)),
  );
  child.on('close', (code) => {
    if (!shuttingDown) {
      console.error(prefix(target.name, `exited with code ${code} — stopping the other process`));
      shutdown(code ?? 1);
    }
  });
  children.push(child);
}

process.on('SIGINT', () => shutdown(0));
process.on('SIGTERM', () => shutdown(0));

console.log('API  → http://127.0.0.1:8000  (docs at /docs)');
console.log('Web  → http://127.0.0.1:3000');
console.log('Press Ctrl+C to stop both.\n');
