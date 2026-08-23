"""Learned perception: datasets, models, predictions.

Everything here is kept structurally apart from `geo`, which holds deterministic
map facts. A prediction is never stored in a map-fact column, never merged into
one, and never allowed to overwrite one — that separation is the difference
between a product that says "OpenStreetMap records stairs here" and one that says
"a model thinks there are stairs here", and both sentences have to remain
available.
"""
