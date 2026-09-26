"""Read-only intake of Overture Maps transportation releases.

PathAble routes on its own OpenStreetMap graph, and this package does not
change that. It reads a bounded piece of one pinned Overture release — the
segments, connectors and changelog rows that fall inside a pilot region — and
measures how PathAble's existing OSM identities relate to Overture's Global
Entity Reference System (GERS).

Nothing here writes to the PathAble database, activates a dataset or changes a
route. The output is evidence: a manifest that says exactly what was read, and
a linkage report that keeps every ambiguity it found.

Why GERS is not a graph-edge key: a GERS segment can merge several OSM ways,
one OSM way can be split across several segments, and a PathAble edge is a
piece of one OSM way. The relationship is many-to-many with linear ranges on
the Overture side, so it is modelled as a relation between identities, never
as a column on an edge.
"""
