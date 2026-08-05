#!/usr/bin/env node
/**
 * Cross-platform `uv` shim, always scoped to services/api.
 *
 * Why this exists: the founder develops on Windows, where uv installs to
 * %USERPROFILE%\.local\bin and is frequently absent from the PATH of whichever
 * shell pnpm happens to spawn. Resolving the binary ourselves keeps the root
 * package.json scripts identical on Windows, macOS, Linux and CI.
 *
 * Usage: node scripts/uv.mjs run pytest tests/unit
 */
import { spawn } from 'node:child_process';
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const apiDir = path.join(repoRoot, 'services', 'api');
const isWindows = process.platform === 'win32';
const exe = isWindows ? 'uv.exe' : 'uv';

/** @returns {string} an absolute path to uv, or the bare name to defer to PATH. */
export function resolveUv() {
  const candidates = [
    process.env.UV_BIN,
    path.join(homedir(), '.local', 'bin', exe),
    path.join(homedir(), '.cargo', 'bin', exe),
    isWindows ? path.join(homedir(), 'AppData', 'Roaming', 'uv', 'bin', exe) : '/usr/local/bin/uv',
  ].filter((candidate) => typeof candidate === 'string' && candidate.length > 0);

  for (const candidate of candidates) {
    if (existsSync(candidate)) return candidate;
  }
  // Fall back to PATH resolution; spawn reports a clear ENOENT if it is missing.
  return exe;
}

export function runUv(args, options = {}) {
  const uv = resolveUv();
  return new Promise((resolve) => {
    const child = spawn(uv, args, {
      cwd: options.cwd ?? apiDir,
      stdio: options.stdio ?? 'inherit',
      shell: false,
      env: { ...process.env, ...options.env },
    });
    child.on('error', (error) => {
      if (error.code === 'ENOENT') {
        process.stderr.write(
          '\nuv was not found. Install it with:\n' +
            '  Windows:  powershell -c "irm https://astral.sh/uv/install.ps1 | iex"\n' +
            '  macOS/Linux: curl -LsSf https://astral.sh/uv/install.sh | sh\n\n',
        );
      } else {
        process.stderr.write(`\nFailed to start uv: ${error.message}\n`);
      }
      resolve(1);
    });
    child.on('close', (code) => resolve(code ?? 1));
  });
}

/**
 * Build a single shell command string for pnpm.
 *
 * Windows installs pnpm as a `.cmd` shim, and since the CVE-2024-27980 fix Node
 * refuses to spawn `.cmd` without a shell (EINVAL). Passing one command string —
 * rather than `shell: true` plus a separate args array — also avoids DEP0190,
 * which warns that array arguments are concatenated unescaped.
 *
 * Arguments are asserted to be shell-safe rather than quoted, because every call
 * site here passes fixed literals. A future caller passing user input should get
 * a loud failure, not silent concatenation.
 */
export function pnpmCommand(args) {
  for (const arg of args) {
    if (!/^[A-Za-z0-9@/._:-]+$/.test(arg)) {
      throw new Error(
        `Refusing to build a pnpm command from an unsafe argument: ${JSON.stringify(arg)}`,
      );
    }
  }
  return ['pnpm', ...args].join(' ');
}

export { apiDir, repoRoot };

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const code = await runUv(process.argv.slice(2));
  process.exit(code);
}
