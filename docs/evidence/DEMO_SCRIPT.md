# The sixty-second demo

How to show what PathAble does, on a laptop, with the real production images and
the real Waterloo dataset. Nothing here is deployed and nothing here is staged:
the comparison is computed by the engine while you watch.

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

## The script

**0:00 — What this is.** "PathAble compares an ordinary walking route with one
that respects how you travel, and explains the difference using what
OpenStreetMap actually records." The subtitle and the pilot badge say the rest.

**0:10 — One press.** _Try a wheelchair route example._ It fills a journey from
the committed twenty-journey evaluation corpus — Davis Centre library to the
Student Life Centre, across the University of Waterloo campus — selects the
wheelchair profile, and sends a real request. Measured at 2.8 s desktop and
3.5 s mobile from page load to the comparison on screen.

**0:20 — The map.** Two routes, distinguishable without colour: the wheelchair
route is a solid line, the shortest walking route is dashed, and the key beside
the map names both in words.

**0:30 — The answer.** _Why are they different?_

|                        |                             |
| ---------------------- | --------------------------- |
| Shortest walking route | 287 m, 4 stairways          |
| Wheelchair route       | 354 m, no stairways         |
| Extra distance         | +67 m, to avoid 4 stairways |

**0:40 — Where each claim comes from.** Four labels, because four different
kinds of statement are on screen and a viewer who cannot tell them apart cannot
judge any of them:

- **Recorded in OpenStreetMap** — "Avoids 4 stairways (16 steps in total, plus 2
  with no recorded step count)." A surveyor wrote that down.
- **Your profile's rules** — the 67 m detour, and why the wheelchair profile
  produces it.
- **Derived from an elevation model** — slope came from NRCan's terrain model of
  the ground, not from a survey of the path.
- **Not recorded** — OpenStreetMap has no accessibility details for 100% of this
  route. Missing information, not a clear path.

**0:55 — The point.** That last label is the product. Every routing system can
draw a line; this one distinguishes what was observed, what was inferred, what
the profile decided, and what nobody knows — and it refuses to let the fourth
category read as the first.

## What to say, and what not to

Say: it runs locally against a real 155,714-node network; the routing is
deterministic rules over recorded map attributes; every response carries
`ml_predictions_used: false`.

Do not say: that it is deployed, that it is live, that a route is safe or
accessible, or that anything here is machine learning. It is none of those, and
the interface is careful not to claim them.

The full list of what may and may not be said, with the evidence behind each
supportable claim, is the [claims ledger](../CLAIMS_LEDGER.md). Prepared answers
at three lengths are in [interview explanations](../INTERVIEW_EXPLANATIONS.md),
and the depth behind them in the [project defence](../PROJECT_DEFENSE.md).

## Recording it

**A recording already exists:** [`media/pathable-demo.webm`](media/pathable-demo.webm),
66.8 s, captured from exactly this script against the production containers, with
a 13.5-second excerpt at [`media/pathable-demo.gif`](media/pathable-demo.gif) for
the README. Use them when you cannot bring the stack up; give the demo live when
you can, because a live answer is worth more than a recording of one.

`http://localhost:3001/?example=campus-library-to-student-life` preselects the
journey and issues the same live request on load, which makes a screen recording
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

The example is a shortcut, not a replacement. Press **Clear**, then click the map
twice to set your own start and end, or use the place search. Changing the
mobility profile re-runs the comparison.
