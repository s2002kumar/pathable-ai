"""Read-only audit of the City of Kitchener Active Transportation inventory.

PathAble routes on its own OpenStreetMap graph, and nothing in this package
changes that. It freezes one snapshot of the City's published inventory,
profiles it, and measures what the inventory could and could not contribute as
pedestrian accessibility evidence.

The question it answers is narrow on purpose: is there enough useful,
non-default, legally usable evidence in this source to justify building a
conflation system? A populated field is not evidence. Most of the attributes
that look useful carry an ArcGIS template default (``WIDTH_M=1.5``,
``SURFACE_MATERIAL=CONCRETE``, ``CURBCUT=N``, ``SURFACE_CONDITION=GOOD``), so a
value equal to its default cannot be told apart from one nobody ever entered.
Every classification here keeps null, blank, unknown, not-applicable, default
and non-default apart.

Nothing here writes to the PathAble database, matches a Kitchener record to an
OpenStreetMap way, or changes a route. Spatial relationships are computed for
description only: an intersection or a nearby edge is not a match.
"""
