# Running the demo

How to reproduce the recorded demo on a laptop, with the real production images
and the real Waterloo dataset. Nothing here is deployed and nothing here is
staged: the comparison is computed by the engine while you watch.

## Before you start

Bring up the isolated production-like stack and wait for readiness — the API
loads the 180,554-segment Waterloo graph at startup and reports 503 until it can
route. See [`docs/deployment/PRODUCTION_SMOKE.md`](../deployment/PRODUCTION_SMOKE.md).

```bash
docker compose -f infra/production-smoke/compose.yaml up -d
curl -s http://localhost:8001/api/v1/health/ready | jq -r .status   # -> ready
open http://localhost:3001
```

While the graph loads the badge reads **Preparing routes · loading the Waterloo
routing graph**, not an error. That is the honest state and it is worth pointing
at: the service is up, and it will not accept traffic until it can actually
answer.

## What it shows

On the planner, `http://localhost:3001/planner`, press **Or run the verified
Waterloo example**. It loads the committed journey
`campus-library-to-student-life` — Davis Centre library to the Student Life
Centre, across the University of Waterloo campus — selects the wheelchair
profile, and sends a real request. The answer it should give, and the dataset
checksum it was verified against, are in the [claims ledger](../CLAIMS_LEDGER.md)
§7 and the [README](../../README.md#what-the-comparison-actually-says).

What each label on screen means — recorded in OpenStreetMap, derived from
elevation, the profile's rule, not recorded — is described in
[`UX04_GOLDEN_MASTER.md`](UX04_GOLDEN_MASTER.md).

## Recording it

**The current recording** is
[`media/pathable-ux04-demo.webm`](media/pathable-ux04-demo.webm), 63.7 s of the
PA-UX-04 interface against the production images: the landing page, the
verified example, one route's evidence and the details sheet. How it was made,
and the spec that re-records it, are in
[`UX04_GOLDEN_MASTER.md`](UX04_GOLDEN_MASTER.md#evidence). The September
recording, [`media/pathable-demo.webm`](media/pathable-demo.webm) with its GIF
excerpt, shows the interface before PA-UX-03B and is kept as history. Give the
demo live when you can, because a live answer is worth more than a recording of
one.

`http://localhost:3001/planner?example=campus-library-to-student-life` preselects
the journey and issues the same live request on load, which makes a screen recording
reproducible without a click. It is a preset for the inputs only — there is no
recorded response anywhere in the application, and the full-stack suite asserts
that the figures on screen are the ones the API returned.

## Where the demo is tested

The demo journey has its own full-stack suite,
`apps/web/tests/fullstack/recruiter-demo.spec.ts`, which drives a real browser
through the containers, watches the network, and checks that the figures on
screen are the ones the API returned.

It needs the real Waterloo network. CI loads the nine-node synthetic fixture —
ingesting a 970 MB extract on every pull request would be absurd — so these
tests **skip in CI with a printed reason** and run here, against the stack
above. Everything that does not need Waterloo, including the whole unit suite
and the stubbed browser suite, runs in CI as usual.

## The manual path still works

The example is a shortcut, not a replacement. Clear the journey, then set each
end yourself: type a Waterloo place, address or street into the field and choose
a result, or click the map. Press **Compare Routes** to ask for them; changing the
mobility profile beside an answer asks again.

Place search answers from a place index read out of the same OpenStreetMap
extract as the network. The production-smoke stack needs it built once — see
[`PRODUCTION_SMOKE.md`](../deployment/PRODUCTION_SMOKE.md#place-search). Until
then the field says search is not available here, and the map still works.
