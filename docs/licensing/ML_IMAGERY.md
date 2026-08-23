# Imagery and training data for Gate C

**Status: a clean path exists.** Reviewed 2026-08-23. Nothing has been
downloaded, nothing trained, nothing committed. This document records what may
lawfully be used and what must not be.

The previous review ([`DATA_SOURCES.md` §6](DATA_SOURCES.md)) asked whether
street-level imagery could be licensed for a commercial CV model and concluded
it could not. That conclusion stands for _street-level panoramas_. This review
asked a narrower and more useful question — **what may be used to train a stairs
detector** — and found four datasets that are unambiguously usable.

---

## The four that pass

All CC BY 4.0. Attribution only: no share-alike, no non-commercial clause, no
obligation on model weights. All are **self-captured by their authors**, which is
what makes the licence effective rather than decorative.

| Dataset                                                                                                                                         | Licence   | Stairs content                                                                    | Provenance                          |
| ----------------------------------------------------------------------------------------------------------------------------------------------- | --------- | --------------------------------------------------------------------------------- | ----------------------------------- |
| [**StairNet**](https://ieee-dataport.org/documents/stairnet-computer-vision-dataset-stair-recognition) (`10.21227/12jm-e336`)                   | CC BY 4.0 | ~515,000 labelled images across level-ground, incline-stairs and both transitions | Self-captured, inherits ExoNet      |
| [**ExoNet**](https://ieee-dataport.org/open-access/exonet-database-wearable-camera-images-human-locomotion-environments) (`10.21227/rz46-2n31`) | CC BY 4.0 | ~89,000 stair-labelled images; 12-class scheme with incline and decline stairs    | Self-captured, chest-mounted iPhone |
| [**Stair dataset with depth maps**](https://data.mendeley.com/datasets/p28ncjnvgk/2) (`10.17632/p28ncjnvgk.2`)                                  | CC BY 4.0 | 2,996 RGB-D pairs, convex/concave stair-line labels                               | Self-captured, RealSense D435i      |
| [**RGB-D stair dataset**](https://data.mendeley.com/datasets/6kffmjt7g2/1) (`10.17632/6kffmjt7g2.1`)                                            | CC BY 4.0 | 2,986 RGB-D pairs incl. a separately captured test set                            | Self-captured                       |

**ExoNet and StairNet come from Canadian labs** — University of Waterloo and
University of Toronto respectively. Neither paper states where the images were
taken, so Ontario coverage cannot be assumed.

Two caveats to settle before download:

- ExoNet's CC BY 4.0 is recorded in its **DataCite metadata**
  (`api.datacite.org/dois/10.21227/rz46-2n31`), not on the rendered IEEE
  DataPort page. Capture the licence field at download.
- **StairNet requires an IEEE DataPort subscription.** That is a cost, and
  therefore a founder decision. ExoNet is open access.

---

## Ground truth that needs no imagery

| Source                                                                                                         | Licence                                                                                          | What it gives                                                                                                                                  |
| -------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------------------------- |
| [**StatCan Canadian Pedestrian Network**](https://www150.statcan.gc.ca/n1/pub/34-26-0004/2025001/meta-eng.htm) | [StatCan Open Licence](https://www.statcan.gc.ca/en/reference/licence) — commercial use explicit | **Stairways as an infrastructure type, across 23 Ontario municipalities.** Compiled from municipal open data, not OSM, so no ODbL entanglement |
| [**Project Sidewalk**](https://sidewalk-sea.cs.washington.edu/developer)                                       | **CC0 1.0** — "We place no restrictions on its use"                                              | Crowd-validated accessibility labels with lat/lon, including a `stairs` tag under Obstacle                                                     |

This is the answer to "could labels replace computer vision entirely?" — partly.
StatCan gives Ontario stair locations for **evaluation and auto-labelling our own
captures**. Project Sidewalk's stairs data is far too sparse to train on: 4
stairs-tagged labels in Burnaby, its only Canadian deployment, and low single-digit
thousands worldwide.

**Project Sidewalk's CC0 covers the labels only.** Its own API page says so:
imagery "remains subject to each provider's terms". The pixel coordinates in
those labels point into Google panoramas we may not fetch.

---

## Rejected, and why

### Provenance traps — a licence that cannot grant what it claims

**[RampNet](https://huggingface.co/datasets/projectsidewalk/rampnet-dataset) —
tagged MIT, contains 214,376 Google Street View panoramas (462 GB).** A
university cannot sublicense Google's imagery under MIT. The
[paper](https://arxiv.org/abs/2508.09415) does not discuss Street View terms at
all. This comes from the most credible group in the field, which is exactly why
it is worth naming: a permissive tag on a redistributed corpus is not a licence.

**[Mendeley `3jjdm6rn96`](https://data.mendeley.com/datasets/3jjdm6rn96/3)** —
tagged CC BY 4.0, and its own description admits "we get some stair images from
the internet" plus a relabelled third-party dataset of unstated licence. There is
no per-image provenance field, so the clean subset cannot be separated. **Use the
depth-map siblings above instead — same authors, same domain, clean.**

**[`segments/sidewalk-semantic`](https://huggingface.co/datasets/segments/sidewalk-semantic)**
is CC BY-**NC** 4.0 and has ~28 clones on Hugging Face with the licence tag
stripped. Copying a dataset does not launder its licence; it only removes your
notice of it.

**GuideTWSI** claims CC BY 4.0 while aggregating SideGuide (non-commercial) and
arbitrary Roboflow community sets.

### Non-commercial

ADE20K (best stairs taxonomy anywhere — six relevant classes — and contractually
non-commercial), Cityscapes, Mapillary Vistas, KITTI, nuScenes, Argoverse,
Waymo, SideGuide. Waymo's licence is the most explicit: its own FAQ gives
"deploy them in a system you intend to use for current or future customers" as
an unacceptable use, and its non-commercial term propagates to model weights.

### No licence at all

SUN397 — the primary site is **offline** and no licence was ever stated. TP-Dataset —
distributed by file-sharing link with no terms. **Silence is not permission.**

---

## Panoramax: the exception worth understanding

The previous review recorded Panoramax as having no North American coverage. **That
was wrong.** It has **≥11,454 pictures in Waterloo Region**, street-level, as
recent as 2025 — precisely the viewpoint and geography this product needs.

Its licence is the obstacle, and unusually, deliberately so.
[Panoramax's documentation](https://docs.panoramax.fr/federated-catalog/#pictures-and-metadata-licenses)
permits derived data "including AI models" under LO 2.0, CC BY 4.0 or ODbL 1.0,
and then states the intent outright:

> This also prevents to create closed derivated data, including AI models or
> training datasets.

So the data is excellent and the grant is real, but it is conditioned on the
model being open. That is a product decision, not an engineering one. It is also
the only source found that offers an **explicit ODbL relicensing path**, which
would dissolve the contamination problem described in
[`DATA_SOURCES.md` §6](DATA_SOURCES.md) — if open weights are acceptable.

---

## Two cross-cutting questions, and where they actually stand

**Does training on CC BY-SA imagery make the weights CC BY-SA?** Unsettled.
Creative Commons' own FAQ poses the question without resolving it. Their
conservative reading is that a publicly shared model trained on ShareAlike data
should carry the same licence. **Canada has no text-and-data-mining exception**
and fair dealing for AI training is untested here, so the "an exception applies"
escape is not reliably available.

**This is why the four CC BY 4.0 datasets matter: BY without SA removes the
question entirely.**

**Does attaching model-derived labels to an OSM-derived graph create an ODbL
conflict?** The OSMF's
[attribution guidelines](https://osmfoundation.org/wiki/Licence/Attribution_Guidelines)
are the clearest published position: a training set extracted from OSM is a
Derivative Database requiring ODbL; a model trained on one needs attribution in
its documentation; and **predictions made by the model are not implicated**. Our
predictions are stored apart from map facts and never merged into them, which
keeps us on the right side of that line.

---

## Decision

**If PathAble may train exactly one stairs model today without further legal
sign-off, it should use ExoNet** — CC BY 4.0, open access, self-captured,
~89,000 stair-labelled images, no obligation beyond attribution. StairNet is
better and needs a subscription decision.

Three things still need a lawyer, and none of them blocks starting:

1. **Panoramax**: is a closed-weight commercial model contrary to its licence in
   fact, or only in stated intent? This decides whether the best Waterloo imagery
   in existence is available.
2. **IEEE DataPort subscription terms**: does the subscription agreement add
   restrictions on top of the deposited CC BY 4.0?
3. **Privacy, which no licence resolves.** ExoNet and StairNet are real-world
   footage of streets and buildings. ExoNet's paper records that ethics review
   was not required and says nothing about faces or bystanders. PIPEDA applies
   independently of copyright, and Ontario has no general private-sector privacy
   statute to supplement it.

## What is still missing, and cannot be bought

**No Ontario stairs imagery dataset exists.** Not one of the sources reviewed —
open, commercial or academic — provides street-level stairs imagery from
Ontario. Freeze-thaw damage, snow cover and Canadian stair geometry are absent
from every candidate.

A model trained on any of the four permitted datasets will be **evaluated out of
domain** in Waterloo. That is a real limitation on the claim such a model can
make, it must be stated wherever the model's output is shown, and the only
durable fix is capturing our own Ontario imagery — which also happens to be the
only path with a completely clean chain of title.
