"""Pilot region definitions and seeding.

Regions are rows, not constants — but the *pilot* region has to come from
somewhere on a fresh database, so its definition lives here and is applied
idempotently. Adding a second city means adding a definition and running the
seed, not editing routing code.
"""

from __future__ import annotations

from dataclasses import dataclass

from geoalchemy2.elements import WKTElement
from shapely.geometry import MultiPolygon, Point, box
from sqlalchemy.ext.asyncio import AsyncSession

from pathable_api.geo.datasets import get_region
from pathable_api.geo.models import SRID, PilotRegion

WATERLOO_SLUG = "waterloo"


@dataclass(frozen=True, slots=True)
class RegionDefinition:
    slug: str
    display_name: str
    #: (min_lon, min_lat, max_lon, max_lat)
    bounds: tuple[float, float, float, float]
    centre: tuple[float, float]
    default_zoom: float
    #: Metre-based CRS used wherever degrees would be meaningless.
    local_projected_crs: str
    enabled: bool = True

    def boundary(self) -> MultiPolygon:
        return MultiPolygon([box(*self.bounds)])


#: The pilot area: the City of Waterloo plus the immediately adjacent stretch of
#: Kitchener, which is where the university campuses and the transit spine are.
#: A rectangle is honest about what this is — a coverage extent, not a municipal
#: boundary — and the routing code treats it purely as "requests outside this are
#: refused rather than snapped to the nearest covered edge".
WATERLOO = RegionDefinition(
    slug=WATERLOO_SLUG,
    display_name="Waterloo, Ontario",
    bounds=(-80.5900, 43.4200, -80.4600, 43.5200),
    centre=(-80.5204, 43.4723),
    default_zoom=14.0,
    local_projected_crs="EPSG:32617",  # UTM zone 17N
)

#: The home of the synthetic test fixture. It is a *separate region* on purpose:
#: invented attributes and real survey data must never share an extent, and this
#: way a synthetic dataset structurally cannot become the active network for the
#: real Waterloo region. Disabled by default so it is never served unless a
#: developer or test asks for it explicitly.
WATERLOO_SYNTHETIC = RegionDefinition(
    slug="waterloo-synthetic",
    display_name="Synthetic test network (not real accessibility data)",
    bounds=(-80.5450, 43.4650, -80.5300, 43.4750),
    centre=(-80.5375, 43.4700),
    default_zoom=16.0,
    local_projected_crs="EPSG:32617",
    enabled=False,
)

#: Regions seeded on every deployment. The synthetic region is deliberately not
#: here; its fixture loader seeds it on demand.
PILOT_REGIONS: tuple[RegionDefinition, ...] = (WATERLOO,)


async def seed_region(session: AsyncSession, definition: RegionDefinition) -> PilotRegion:
    """Create the region if absent, refresh its extent if present.

    Idempotent: safe to run on every deployment and in every test that needs a
    region to exist.
    """
    boundary = WKTElement(definition.boundary().wkt, srid=SRID)
    centre = WKTElement(Point(*definition.centre).wkt, srid=SRID)

    region = await get_region(session, definition.slug)
    if region is None:
        region = PilotRegion(
            slug=definition.slug,
            display_name=definition.display_name,
            boundary=boundary,
            centre=centre,
            default_zoom=definition.default_zoom,
            local_projected_crs=definition.local_projected_crs,
            enabled=definition.enabled,
        )
        session.add(region)
    else:
        region.display_name = definition.display_name
        region.boundary = boundary
        region.centre = centre
        region.default_zoom = definition.default_zoom
        region.local_projected_crs = definition.local_projected_crs
        region.enabled = definition.enabled

    await session.flush()
    return region


async def seed_pilot_regions(session: AsyncSession) -> list[PilotRegion]:
    return [await seed_region(session, definition) for definition in PILOT_REGIONS]


def region_definition(slug: str) -> RegionDefinition:
    for definition in PILOT_REGIONS:
        if definition.slug == slug:
            return definition
    known = ", ".join(d.slug for d in PILOT_REGIONS)
    msg = f"Unknown pilot region {slug!r}. Known regions: {known}"
    raise KeyError(msg)
