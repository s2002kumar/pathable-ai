#!/usr/bin/env node
/**
 * Capture screenshots of the map against the REAL development tile provider.
 *
 *   node scripts/capture-map-evidence.mjs
 *
 * This is a manual verification aid, deliberately **not** part of CI and not a
 * test. It reaches a third-party tile server, so making it a required check
 * would mean a green build depends on someone else's uptime — exactly what the
 * automated suites avoid by using a local, source-less style.
 *
 * Output: apps/web/artifacts/screenshots/real-basemap-*.png plus a console-error
 * summary. Evidence only; never a visual-regression baseline.
 */
import { execSync, spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import path from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { pnpmCommand } from './uv.mjs';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const webDir = path.join(repoRoot, 'apps', 'web');
const outDir = path.join(webDir, 'artifacts', 'screenshots');

const PORT = Number(process.env.MAP_EVIDENCE_PORT ?? 3300);
const BASE_URL = `http://127.0.0.1:${PORT}`;
const STYLE_URL =
  process.env.NEXT_PUBLIC_MAP_STYLE_URL ?? 'https://tiles.openfreemap.org/styles/liberty';

const buildEnv = {
  ...process.env,
  NODE_ENV: 'production',
  NEXT_TELEMETRY_DISABLED: '1',
  NEXT_PUBLIC_MAP_STYLE_URL: STYLE_URL,
  NEXT_PUBLIC_API_BASE_URL: process.env.NEXT_PUBLIC_API_BASE_URL ?? 'http://127.0.0.1:8100',
  NEXT_PUBLIC_PILOT_CENTER_LAT: '43.4668',
  NEXT_PUBLIC_PILOT_CENTER_LON: '-80.5164',
  NEXT_PUBLIC_PILOT_ZOOM: '15',
  NEXT_PUBLIC_PILOT_REGION_NAME: 'Waterloo, Ontario',
};

function run(command, { cwd = repoRoot, detached = false } = {}) {
  return spawn(command, [], { cwd, env: buildEnv, shell: true, detached, stdio: 'pipe' });
}

function waitForExit(child) {
  return new Promise((resolve) => child.on('close', (code) => resolve(code ?? 1)));
}

/**
 * Free the port before starting.
 *
 * Without this, a `next start` left behind by a previous run keeps answering
 * while serving a `.next` directory that the new build has already replaced.
 * The symptom is baffling — chunk requests 500 with a `text/plain` MIME type and
 * the page never hydrates — and it looks exactly like a broken application.
 */
function freePort(port) {
  try {
    if (process.platform === 'win32') {
      const output = execSync(`netstat -ano | findstr :${port}`, { encoding: 'utf8' });
      const pids = [
        ...new Set(
          output
            .split('\n')
            .map((line) => line.trim().split(/\s+/).pop())
            .filter((pid) => /^\d+$/.test(pid) && pid !== '0'),
        ),
      ];
      for (const pid of pids) {
        try {
          execSync(`taskkill /PID ${pid} /T /F`, { stdio: 'ignore' });
          console.log(`  reclaimed port ${port} from pid ${pid}`);
        } catch {
          // Already gone.
        }
      }
    } else {
      execSync(`lsof -ti tcp:${port} | xargs -r kill -9`, { stdio: 'ignore' });
    }
  } catch {
    // Nothing listening, which is the normal case.
  }
}

async function waitForServer(url, timeoutMs = 120_000) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    try {
      const response = await fetch(url);
      if (response.ok) return true;
    } catch {
      // not up yet
    }
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  return false;
}

console.log(`Tile provider under test: ${STYLE_URL}\n`);

console.log('→ Building the web app with the real map style');
const build = run(pnpmCommand(['exec', 'next', 'build']), { cwd: webDir });
build.stdout.on('data', (chunk) => process.stdout.write(chunk));
build.stderr.on('data', (chunk) => process.stderr.write(chunk));
if ((await waitForExit(build)) !== 0) {
  console.error('\n✗ Build failed.');
  process.exit(1);
}

console.log(`\n→ Starting the server on ${BASE_URL}`);
freePort(PORT);
const server = run(pnpmCommand(['exec', 'next', 'start', '--port', String(PORT)]), {
  cwd: webDir,
  detached: true,
});

let exitCode = 0;
try {
  if (!(await waitForServer(`${BASE_URL}/api/healthz`))) {
    throw new Error('The web server did not become ready.');
  }

  // Playwright lives in the web workspace, not at the repo root, so it is
  // resolved from there rather than relying on hoisting.
  const requireFromWeb = createRequire(pathToFileURL(path.join(webDir, 'package.json')).href);
  const imported = await import(pathToFileURL(requireFromWeb.resolve('@playwright/test')).href);
  // @playwright/test is CommonJS, so importing it yields the exports under
  // `.default` on some resolutions and at the top level on others.
  const playwright = imported.default ?? imported;
  const { chromium, devices } = playwright;
  await mkdir(outDir, { recursive: true });

  const browser = await chromium.launch({
    args: ['--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader'],
  });

  const targets = [
    { name: 'desktop', options: { viewport: { width: 1440, height: 900 } } },
    { name: 'mobile', options: devices['Pixel 7'] },
  ];

  const report = [];

  for (const target of targets) {
    const context = await browser.newContext(target.options);
    const page = await context.newPage();

    const consoleErrors = [];
    const consoleWarnings = [];
    const failedRequests = [];
    const tileTraffic = new Map();

    page.on('console', (message) => {
      const type = message.type();
      if (type === 'error') consoleErrors.push(message.text());
      else if (type === 'warning') consoleWarnings.push(message.text());
    });
    page.on('requestfailed', (request) => {
      failedRequests.push(`${request.url()} — ${request.failure()?.errorText ?? 'unknown'}`);
    });
    page.on('response', (response) => {
      // Count what the tile provider actually returned. This is what separates
      // "the provider is down" from "our code is wrong" from "software rendering
      // is simply too slow to finish".
      const url = response.url();
      if (!url.includes('openfreemap.org')) return;
      const kind = /\.pbf|\/planet/.test(url)
        ? 'vector-tiles'
        : /sprite/.test(url)
          ? 'sprites'
          : /fonts?|glyph/.test(url)
            ? 'glyphs'
            : /\.png/.test(url)
              ? 'raster-tiles'
              : 'style';
      const key = `${kind} ${response.status()}`;
      tileTraffic.set(key, (tileTraffic.get(key) ?? 0) + 1);
    });

    await page.goto(BASE_URL, { waitUntil: 'domcontentloaded' });

    const frame = page.getByTestId('map-frame');
    await frame.waitFor({ state: 'visible', timeout: 30_000 });

    // Wait for the real style and its tiles to settle.
    let state = 'initialising';
    const deadline = Date.now() + 75_000;
    while (Date.now() < deadline) {
      state = (await frame.getAttribute('data-map-state')) ?? 'unknown';
      if (state !== 'initialising') break;
      await page.waitForTimeout(500);
    }
    await page.waitForTimeout(4_000); // let tiles finish painting

    // Screenshot first: the point of this script is evidence, including evidence
    // of failure. Probing controls must never prevent the capture.
    const file = path.join(outDir, `real-basemap-${target.name}.png`);
    await page.screenshot({ path: file });

    let attributionVisible = false;
    let controlsInsideMap = false;
    let overlayText = null;
    try {
      const attribution = page.locator('.maplibregl-ctrl-attrib');
      if ((await attribution.count()) > 0) {
        attributionVisible = await attribution.isVisible();
        const frameBox = await frame.boundingBox();
        const attribBox = await attribution.boundingBox();
        controlsInsideMap =
          frameBox !== null &&
          attribBox !== null &&
          attribBox.x >= frameBox.x - 1 &&
          attribBox.x + attribBox.width <= frameBox.x + frameBox.width + 1 &&
          attribBox.y + attribBox.height <= frameBox.y + frameBox.height + 1;
      }
      const overlay = page.getByTestId('map-overlay');
      if ((await overlay.count()) > 0) overlayText = (await overlay.innerText()).trim();
    } catch (probeError) {
      console.warn(`  (control probe failed: ${probeError.message})`);
    }

    report.push({
      target: target.name,
      mapState: state,
      attributionVisible,
      controlsInsideMap,
      overlayText,
      tileTraffic: Object.fromEntries(tileTraffic),
      consoleErrors,
      consoleWarnings: consoleWarnings.slice(0, 10),
      failedRequests,
      screenshot: path.relative(repoRoot, file),
    });

    console.log(`\n[${target.name}]`);
    console.log(`  map state          : ${state}`);
    console.log(`  attribution visible: ${attributionVisible}`);
    console.log(`  controls in map    : ${controlsInsideMap}`);
    if (overlayText !== null)
      console.log(`  overlay text       : ${overlayText.split('\n').join(' | ')}`);
    console.log(`  tile provider      : ${JSON.stringify(Object.fromEntries(tileTraffic))}`);
    console.log(`  console warnings   : ${consoleWarnings.length}`);
    consoleWarnings.slice(0, 3).forEach((w) => console.log(`      - ${w.slice(0, 160)}`));
    console.log(`  console errors     : ${consoleErrors.length}`);
    consoleErrors.forEach((e) => console.log(`      - ${e}`));
    console.log(`  failed requests    : ${failedRequests.length}`);
    failedRequests.slice(0, 5).forEach((e) => console.log(`      - ${e}`));
    console.log(`  screenshot         : ${report.at(-1).screenshot}`);

    await context.close();
  }

  await browser.close();

  const reportPath = path.join(outDir, 'real-basemap-report.json');
  await writeFile(
    reportPath,
    `${JSON.stringify({ styleUrl: STYLE_URL, capturedAt: new Date().toISOString(), report }, null, 2)}\n`,
    'utf8',
  );
  console.log(`\n✓ Evidence written to ${path.relative(repoRoot, reportPath)}`);

  if (report.some((entry) => entry.mapState !== 'ready')) {
    console.warn(
      '\n! The map did not reach "ready" for every target. If the tile provider is\n' +
        '  unavailable, record that honestly rather than retrying until it passes.',
    );
    exitCode = 2;
  }
} catch (error) {
  console.error(`\n✗ ${error.message}`);
  exitCode = 1;
} finally {
  try {
    process.kill(-server.pid, 'SIGTERM');
  } catch {
    server.kill('SIGTERM');
  }
}

process.exit(exitCode);
