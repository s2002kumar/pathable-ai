# ADR 0008 — The accessibility cost model

- **Status**: Accepted
- **Date**: 2026-08-12
- **Supersedes**: nothing
- **Related**: [0004 PostGIS and the runtime graph](0004-postgis-and-runtime-graph.md),
  [0006 configurable Waterloo pilot](0006-configurable-waterloo-pilot.md)

## Context

PathAble has to turn "how does this person travel?" into "which way should they
go?". The mechanism decides what the product is, so it is worth stating the
decision rather than letting it accumulate.

Three properties had to hold:

1. A route must be **explainable**. Somebody deciding whether they can make a
   journey needs to know what the alternative cost them and why, in terms they
   can disagree with.
2. Missing data must never read as good data. OpenStreetMap's accessibility
   coverage is sparse and uneven, and the least-surveyed places are not the most
   accessible ones.
3. Nothing may look like a prediction. There is no model here, and the design
   must not leave room to imply there is.

## Decision

### Costs are _effective metres_

`evaluate_edge` returns what a segment costs in metres-of-effort, not an
abstract score. A 100 m gravel path costing 250 effective metres means "this
feels like two and a half times the distance".

The unit is the point. A dimensionless score of 0.37 cannot be argued with; a
claim that a rough 100 m path is worth 250 m of clear pavement can be, and being
arguable is what makes it honest. Every contribution is returned alongside the
total with the recorded attribute that produced it, so a route can show its
working down to the segment.

### Hard constraints and penalties are separate, and hard constraints fire only on evidence

A **hard constraint** removes a segment from the graph entirely. It is used only
where travel is genuinely not possible: a stairway in a wheelchair, a recorded
width narrower than the chair. A hard constraint can make a journey unroutable,
and that is sometimes the correct answer.

A **penalty** makes a segment cost more. Everything that is harder rather than
impossible lives here: rough surface, a steep but passable grade, an unrecorded
kerb, a crossing.

Critically, **no hard constraint fires on the absence of a tag**. A missing
width, gradient or surface never excludes a segment. The alternative would delete
most of the network — and it would delete precisely the parts nobody has
surveyed, which is the opposite of what a user needs.

### Absence is charged as uncertainty

Missing routing-relevant attributes add cost proportional to segment length and
to how many attributes are missing. Without this, the cheapest path through the
network is the one carrying the least information, which exactly inverts what
somebody needs from the product.

The penalty scales with length because a 500 m unsurveyed path is a bigger gamble
than a 20 m one. Every route also reports the share of its length that has
missing data, and the UI says plainly that missing data is not evidence a path is
clear.

### The standard route is the same engine with a zero-penalty profile

There is one Dijkstra implementation. The "standard" route is the identical code
run with a profile whose penalties are all zero. Two implementations would
eventually diverge for reasons that had nothing to do with the user's
preferences, and the entire product is the comparison between them.

The standard profile still refuses segments where foot access is prohibited:
that is a legal fact about the way, not a preference.

### The two errors are not symmetric

Telling somebody a blocked path is passable can strand them somewhere they
cannot leave. Telling them a passable path is difficult costs them a detour. The
weights lean toward the second, deliberately.

## Consequences

- A route can always be explained from the same numbers the router optimised.
  An explanation reconstructed separately would eventually stop matching.
- A profile can legitimately have no route. The API returns the shortest route
  anyway, along with the specific segments that blocked the accessible one, so
  "no route" arrives with a reason.
- The weights are engineering judgement, **not measurements**. They have not been
  validated against how people using these mobility aids actually travel. The
  product must not present them as if they had been, and validating them with
  real users is a prerequisite for taking this beyond a pilot.
- When learned predictions eventually exist, they enter as their own cost
  contribution with their own code, sitting beside the deterministic ones rather
  than replacing them — so "OSM says" and "a model thinks" stay distinguishable
  in the response, and `ml_predictions_used` becomes a meaningful flag rather
  than a constant.

## Alternatives considered

**A single accessibility score per segment.** Simpler to render and impossible to
argue with. It would have collapsed "this is rough", "this is steep" and "nobody
has looked" into one number, and it is exactly the kind of invented metric this
project must not ship.

**Excluding every segment with unknown attributes.** Safe-sounding and unusable:
it would refuse to route across most of a real city, and it would refuse hardest
in the least-mapped neighbourhoods.

**Treating unknown as acceptable.** The cheapest route would then be the least
documented one, and the product would confidently recommend paths nobody has
checked.
