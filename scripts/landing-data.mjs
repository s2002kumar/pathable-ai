#!/usr/bin/env node
/**
 * Regenerate the two real-data assets behind the landing page.
 *
 *   node scripts/landing-data.mjs route   [--api http://127.0.0.1:8001]
 *   node scripts/landing-data.mjs network [--psql "docker exec -i pathable-envelope-db-1 psql -U pathable -d pathable"]
 *
 * `route` asks a running routing API for the verified campus journey and
 * writes `apps/web/src/features/landing/verified-route.ts`: every figure,
 * coordinate and per-segment evidence value copied from that one response,
 * nothing rounded beyond six coordinate decimals and nothing added.
 *
 * `network` reads the pedestrian network around that journey from the same
 * dataset in PostGIS and writes `apps/web/public/landing/campus-paths.svg`,
 * the faint street-and-path backdrop the landing page draws its routes on.
 * It is OpenStreetMap data as PathAble ingested it, credited in the file.
 *
 * Both are manual, like `capture-map-evidence.mjs`: they need the local
 * production envelope (docs/deployment/PRODUCTION_SMOKE.md), so CI never runs
 * them. Re-run both if the dataset or the routing policy changes; the landing
 * page states which dataset and policy produced what it shows.
 */
import { execSync } from 'node:child_process';
import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const webDir = path.join(repoRoot, 'apps', 'web');

/** The campus example's inputs, exactly as `verified-example.ts` sends them. */
const REQUEST = {
  origin: { longitude: -80.5424, latitude: 43.4728 },
  destination: { longitude: -80.5449, latitude: 43.4715 },
  profile: 'wheelchair',
};

/** The dataset the landing page's record and backdrop must both come from. */
const DATASET_CHECKSUM = '51e75f7896ab725d29120fe4363c607bea68eed260d830482d6677f827d2e906';

/**
 * The drawing frame, shared with `stage-frame.ts` (a unit test holds the two
 * together): metres from this origin, x east, y south. Equirectangular with
 * the longitude scaled at the origin's latitude — at the scale of a campus,
 * indistinguishable from a proper projection.
 */
const FRAME = { longitude: -80.5435, latitude: 43.4721, metresPerDegree: 111195.08 };
/**
 * Half-extent of the backdrop in metres: what the widest stage crop shows (a
 * landscape phone, about 590 m across) and no more, because every extra metre
 * is paint on the first frame.
 */
const HALF = { x: 340, y: 240 };

function arg(name, fallback) {
  const index = process.argv.indexOf(name);
  return index > -1 ? process.argv[index + 1] : fallback;
}

function project([longitude, latitude]) {
  const k = Math.cos((FRAME.latitude * Math.PI) / 180);
  return [
    (longitude - FRAME.longitude) * k * FRAME.metresPerDegree,
    (FRAME.latitude - latitude) * FRAME.metresPerDegree,
  ];
}

const round6 = (value) => Math.round(value * 1e6) / 1e6;

// ---------------------------------------------------------------------------
// route
// ---------------------------------------------------------------------------

function segmentRecord(segment) {
  return {
    lengthM: segment.length_m,
    highway: segment.highway,
    steps: segment.steps,
    stepCount: segment.step_count,
    surface: segment.surface,
    smoothnessClass: segment.smoothness_class,
    widthM: segment.width_m,
    inclinePercent: segment.incline_percent,
    derivedGradePercent: segment.derived_grade_percent,
    excludedByProfile: segment.excluded_by_profile,
  };
}

function routeRecord(route) {
  // The landing page draws segment i between coordinates i and i + 1; refuse
  // a response where that is not true rather than draw a wrong line.
  route.segments.forEach((segment, index) => {
    const [a, b] = [segment.coordinates[0], segment.coordinates.at(-1)];
    const [p, q] = [route.coordinates[index], route.coordinates[index + 1]];
    const same = (u, v) => Math.abs(u[0] - v[0]) < 1e-6 && Math.abs(u[1] - v[1]) < 1e-6;
    if (segment.coordinates.length !== 2 || !same(a, p) || !same(b, q)) {
      throw new Error(
        `segment ${index} is not the straight piece between coordinates ${index} and ${index + 1}`,
      );
    }
  });
  const stairs = route.segments.filter((segment) => segment.steps === 'yes');
  return {
    distanceM: route.distance_m,
    stairways: route.stairway_count,
    recordedSteps: route.step_count,
    stairwaysWithoutStepCount: stairs.filter((segment) => segment.step_count === null).length,
    stairwaysRuledOut: route.segments.filter((segment) => segment.excluded_by_profile === 'steps')
      .length,
    unknownDataFraction: route.unknown_data_fraction,
    gradientSource: route.gradient_source,
    crossingCount: route.crossing_count,
    evidenceCoverage: route.evidence_coverage,
    gradient: {
      recordedFraction: route.gradient.recorded_fraction,
      estimatedFraction: route.gradient.estimated_fraction,
      unknownFraction: route.gradient.unknown_fraction,
      steepestUphillPercent: route.gradient.steepest_uphill?.percent ?? null,
      steepestDownhillPercent: route.gradient.steepest_downhill?.percent ?? null,
    },
    coordinates: route.coordinates.map(([lng, lat]) => [round6(lng), round6(lat)]),
    stairs: stairs.map((segment) =>
      segment.coordinates.map(([lng, lat]) => [round6(lng), round6(lat)]),
    ),
    segments: route.segments.map(segmentRecord),
  };
}

async function recordRoute() {
  const api = arg('--api', 'http://127.0.0.1:8001');
  const response = await fetch(`${api}/api/v1/routes/compare`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(REQUEST),
  });
  if (!response.ok) throw new Error(`compare answered ${response.status}`);
  const body = await response.json();
  if (body.dataset.checksum !== DATASET_CHECKSUM) {
    throw new Error(`the API is serving dataset ${body.dataset.checksum}, not ${DATASET_CHECKSUM}`);
  }
  if (body.ml_predictions_used !== false) throw new Error('a model took part in this response');

  const record = {
    recordedOn: new Date().toISOString().slice(0, 10),
    request: REQUEST,
    datasetChecksum: body.dataset.checksum,
    datasetSourceTimestamp: body.dataset.source_timestamp,
    routingPolicyVersion: body.routing_policy_version,
    mlPredictionsUsed: body.ml_predictions_used,
    originLabel: 'Davis Centre library',
    destinationLabel: 'Student Life Centre',
    extraDistanceM: body.extra_distance_m,
    extraDistanceFraction: body.extra_distance_fraction,
    standard: routeRecord(body.standard_route),
    accessible: routeRecord(body.accessible_route),
  };

  const file = path.join(webDir, 'src', 'features', 'landing', 'verified-route.ts');
  writeFileSync(
    file,
    `${ROUTE_HEADER}export const VERIFIED_ROUTE = ${JSON.stringify(record, null, 2)} as const;\n`,
    { encoding: 'utf8' },
  );
  execSync(`pnpm exec prettier --write "${file}"`, { cwd: repoRoot, stdio: 'inherit' });
  console.log(
    `recorded ${record.standard.distanceM} m / ${record.accessible.distanceM} m → ${path.relative(repoRoot, file)}`,
  );
}

const ROUTE_HEADER = `/**
 * The verified Waterloo example as one real run of the routing API recorded it.
 *
 * GENERATED by \`node scripts/landing-data.mjs route\` — do not edit by hand.
 *
 * The landing page is static, so it cannot ask the API; it shows this record
 * instead, and says so. Every figure, coordinate and per-segment evidence value
 * here was copied from a single \`POST /api/v1/routes/compare\` response — the
 * campus example's coordinates, the wheelchair profile — served by the local
 * production envelope on the date below. Coordinates are kept to six decimals
 * (about 10 cm); nothing else is rounded and nothing is added. Segment i is the
 * straight piece between coordinates i and i + 1 (the script refuses a
 * response where it is not). The planner computes the same journey live.
 *
 * Re-record it if the dataset or the routing policy changes; the checksum and
 * policy version below say which ones produced it.
 */
`;

// ---------------------------------------------------------------------------
// network
// ---------------------------------------------------------------------------

function networkSql() {
  const k = Math.cos((FRAME.latitude * Math.PI) / 180);
  const dLng = HALF.x / (k * FRAME.metresPerDegree);
  const dLat = HALF.y / FRAME.metresPerDegree;
  const [w, e] = [FRAME.longitude - dLng, FRAME.longitude + dLng].map((v) => v.toFixed(7));
  const [s, n] = [FRAME.latitude - dLat, FRAME.latitude + dLat].map((v) => v.toFixed(7));
  return `
with ds as (
  select id from dataset_versions where checksum = '${DATASET_CHECKSUM}'
), box as (
  select ST_MakeEnvelope(${w}, ${s}, ${e}, ${n}, 4326) as g
), classified as (
  select case
      when e.indoor = 'yes' or e.highway = 'corridor' then 'indoor'
      when e.highway in ('footway', 'path', 'pedestrian', 'steps', 'cycleway', 'track', 'bridleway') then 'path'
      else 'street'
    end as class,
    ST_ClipByBox2D(e.geometry, box.g) as geom
  from graph_edges e, ds, box
  where e.dataset_version_id = ds.id and e.geometry && box.g
)
select class, count(*),
  ST_AsGeoJSON(ST_SimplifyPreserveTopology(ST_LineMerge(ST_Collect(geom)), 0.000004), 7)
from classified
where not ST_IsEmpty(geom)
group by class
order by class;`;
}

function svgNumber(value) {
  return (Math.round(value * 10) / 10).toString();
}

function pathData(lines) {
  let d = '';
  for (const line of lines) {
    let previous = null;
    for (const coordinate of line) {
      const [x, y] = project(coordinate).map((v) => Math.round(v * 10) / 10);
      if (previous === null) {
        d += `M${svgNumber(x)} ${svgNumber(y)}`;
      } else {
        const [dx, dy] = [x - previous[0], y - previous[1]];
        if (Math.abs(dx) < 0.05 && Math.abs(dy) < 0.05) continue;
        const sx = svgNumber(dx);
        const sy = svgNumber(dy);
        d += `l${sx}${sy.startsWith('-') ? '' : ' '}${sy}`;
      }
      previous = [x, y];
    }
  }
  return d;
}

const STYLES = {
  // Streets read as the city's structure, paths as the walkable mesh, and
  // indoor corridors stay faintest: the journey starts in one.
  street: 'stroke="#2a3a5c" stroke-width="1.5"',
  path: 'stroke="#22314f" stroke-width="0.9"',
  indoor: 'stroke="#1b2740" stroke-width="0.7" stroke-dasharray="2 2"',
};

function buildNetwork() {
  const psql = arg('--psql', 'docker exec -i pathable-envelope-db-1 psql -U pathable -d pathable');
  const meta = execSync(`${psql} -At -F "|"`, {
    input: `select source_timestamp from dataset_versions where checksum = '${DATASET_CHECKSUM}';`,
    encoding: 'utf8',
  }).trim();
  const rows = execSync(`${psql} -At -F "|"`, {
    input: networkSql(),
    encoding: 'utf8',
    maxBuffer: 64 * 1024 * 1024,
  })
    .trim()
    .split('\n')
    .map((line) => {
      const [cls, count, geojson] = line.split('|');
      const geometry = JSON.parse(geojson);
      const lines = geometry.type === 'LineString' ? [geometry.coordinates] : geometry.coordinates;
      return { cls, count: Number(count), lines };
    });
  if (rows.length === 0) throw new Error('no network rows: is the dataset loaded?');

  const order = ['indoor', 'path', 'street'];
  rows.sort((a, b) => order.indexOf(a.cls) - order.indexOf(b.cls));
  const total = rows.reduce((sum, row) => sum + row.count, 0);
  const paths = rows
    .map((row) => `<path data-class="${row.cls}" ${STYLES[row.cls]} d="${pathData(row.lines)}"/>`)
    .join('\n');
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${-HALF.x} ${-HALF.y} ${2 * HALF.x} ${2 * HALF.y}" width="${2 * HALF.x}" height="${2 * HALF.y}">
<title>Pedestrian network around the University of Waterloo campus</title>
<desc>${total} routable segments from OpenStreetMap (© OpenStreetMap contributors, ODbL 1.0) as ingested in PathAble dataset ${DATASET_CHECKSUM.slice(0, 8)} (source timestamp ${meta}). Generated by scripts/landing-data.mjs network. Frame: metres from ${FRAME.longitude}, ${FRAME.latitude}; x east, y south. A drawing of the routing graph, not a basemap.</desc>
<g fill="none" stroke-linecap="round" stroke-linejoin="round">
${paths}
</g>
</svg>
`;
  const outDir = path.join(webDir, 'public', 'landing');
  mkdirSync(outDir, { recursive: true });
  const file = path.join(outDir, 'campus-paths.svg');
  writeFileSync(file, svg, { encoding: 'utf8' });
  console.log(
    `${total} segments (${rows.map((r) => `${r.cls} ${r.count}`).join(', ')}) → ${path.relative(repoRoot, file)}, ${(svg.length / 1024).toFixed(1)} KiB`,
  );
}

const command = process.argv[2];
if (command === 'route') {
  await recordRoute();
} else if (command === 'network') {
  buildNetwork();
} else if (command === 'network-sql') {
  console.log(networkSql());
} else {
  console.error('usage: node scripts/landing-data.mjs <route|network|network-sql> [options]');
  process.exit(2);
}
