"""Journeys in the Waterloo pilot area, for evaluating the real network.

These are ordinary trips: campus to transit, home to shops, hospital to parking,
park paths, and the awkward ones across arterial roads. They are chosen to span
the things that ought to make an accessibility profile behave differently —
crossings, ravine footbridges, campus underpasses, a rail corridor — and to span
distance, from a two-block walk to a few kilometres.

Coordinates are approximate positions of the named places, not surveyed points.
That is deliberate and it is also the realistic case: a user taps a map or types
an address, and the engine has to attach that to the network. Every result
records how far the point had to move to reach a walkable segment, so a case
whose endpoint landed 60 m away is visible as such rather than quietly folded
into the distance.

**No case is here because it produced a good result.** The list was fixed before
the routes were run, and every one of them is reported whatever it did.
"""

from __future__ import annotations

from pathable_api.routing.evaluation import RouteCase

#: Approximate positions, (longitude, latitude).
_UW_DC_LIBRARY = (-80.5424, 43.4728)
_UW_STUDENT_LIFE = (-80.5449, 43.4715)
_LAURIER_QUAD = (-80.5275, 43.4740)
_UPTOWN_SQUARE = (-80.5222, 43.4650)
_WATERLOO_PARK = (-80.5330, 43.4680)
_WATERLOO_REC_COMPLEX = (-80.5405, 43.4794)
_CONESTOGA_MALL = (-80.5262, 43.4998)
_NORTHFIELD_STATION = (-80.5285, 43.4914)
_RIM_PARK = (-80.4790, 43.5060)
_ERB_AND_WESTMOUNT = (-80.5450, 43.4640)
_BELMONT_VILLAGE = (-80.5100, 43.4460)
_KITCHENER_CITY_HALL = (-80.4925, 43.4516)
_VICTORIA_PARK = (-80.4967, 43.4463)
_KITCHENER_MARKET = (-80.4855, 43.4506)
_GRAND_RIVER_HOSPITAL = (-80.5069, 43.4574)
_THE_BOARDWALK = (-80.5760, 43.4430)
_LAUREL_CREEK = (-80.5550, 43.4870)
_BRIDGEPORT_AND_WEBER = (-80.5150, 43.4720)
_COLUMBIA_AND_KING = (-80.5240, 43.4790)
_UPTOWN_TRANSIT_HUB = (-80.5228, 43.4664)


#: Fixed before any route was computed. Order is stable so results are
#: comparable between runs.
WATERLOO_CASES: tuple[RouteCase, ...] = (
    RouteCase(
        key="campus-library-to-student-life",
        description="Short walk across the University of Waterloo campus",
        origin=_UW_DC_LIBRARY,
        destination=_UW_STUDENT_LIFE,
    ),
    RouteCase(
        key="campus-to-laurier",
        description="Between the two universities, across University Avenue",
        origin=_UW_DC_LIBRARY,
        destination=_LAURIER_QUAD,
    ),
    RouteCase(
        key="laurier-to-uptown",
        description="Laurier campus down to Uptown Waterloo",
        origin=_LAURIER_QUAD,
        destination=_UPTOWN_SQUARE,
    ),
    RouteCase(
        key="uptown-to-waterloo-park",
        description="Uptown to the park, crossing the rail corridor",
        origin=_UPTOWN_SQUARE,
        destination=_WATERLOO_PARK,
    ),
    RouteCase(
        key="park-to-campus",
        description="Waterloo Park through to campus",
        origin=_WATERLOO_PARK,
        destination=_UW_DC_LIBRARY,
    ),
    RouteCase(
        key="uptown-to-transit-hub",
        description="Two blocks in Uptown to the transit hub",
        origin=_UPTOWN_SQUARE,
        destination=_UPTOWN_TRANSIT_HUB,
    ),
    RouteCase(
        key="rec-complex-to-campus",
        description="Recreation complex south to campus",
        origin=_WATERLOO_REC_COMPLEX,
        destination=_UW_STUDENT_LIFE,
    ),
    RouteCase(
        key="northfield-to-conestoga",
        description="Northfield station up to Conestoga Mall",
        origin=_NORTHFIELD_STATION,
        destination=_CONESTOGA_MALL,
    ),
    RouteCase(
        key="conestoga-to-rim-park",
        description="Mall east to Rim Park — long, and partly along arterials",
        origin=_CONESTOGA_MALL,
        destination=_RIM_PARK,
    ),
    RouteCase(
        key="erb-westmount-to-uptown",
        description="West Waterloo along Erb Street into Uptown",
        origin=_ERB_AND_WESTMOUNT,
        destination=_UPTOWN_SQUARE,
    ),
    RouteCase(
        key="uptown-to-belmont",
        description="Uptown Waterloo south to Belmont Village",
        origin=_UPTOWN_SQUARE,
        destination=_BELMONT_VILLAGE,
    ),
    RouteCase(
        key="belmont-to-hospital",
        description="Belmont Village to Grand River Hospital",
        origin=_BELMONT_VILLAGE,
        destination=_GRAND_RIVER_HOSPITAL,
    ),
    RouteCase(
        key="hospital-to-city-hall",
        description="Hospital across to Kitchener City Hall",
        origin=_GRAND_RIVER_HOSPITAL,
        destination=_KITCHENER_CITY_HALL,
    ),
    RouteCase(
        key="city-hall-to-victoria-park",
        description="City Hall to Victoria Park, downtown Kitchener",
        origin=_KITCHENER_CITY_HALL,
        destination=_VICTORIA_PARK,
    ),
    RouteCase(
        key="city-hall-to-market",
        description="City Hall east to the Kitchener Market",
        origin=_KITCHENER_CITY_HALL,
        destination=_KITCHENER_MARKET,
    ),
    RouteCase(
        key="victoria-park-to-market",
        description="Across downtown Kitchener, park to market",
        origin=_VICTORIA_PARK,
        destination=_KITCHENER_MARKET,
    ),
    RouteCase(
        key="boardwalk-to-uptown",
        description="The Boardwalk to Uptown Waterloo — a long suburban walk",
        origin=_THE_BOARDWALK,
        destination=_UPTOWN_SQUARE,
    ),
    RouteCase(
        key="laurel-creek-to-campus",
        description="Laurel Creek area down to campus",
        origin=_LAUREL_CREEK,
        destination=_UW_DC_LIBRARY,
    ),
    RouteCase(
        key="bridgeport-to-columbia",
        description="Bridgeport and Weber north to Columbia and King",
        origin=_BRIDGEPORT_AND_WEBER,
        destination=_COLUMBIA_AND_KING,
    ),
    RouteCase(
        key="columbia-to-rec-complex",
        description="Columbia and King west to the recreation complex",
        origin=_COLUMBIA_AND_KING,
        destination=_WATERLOO_REC_COMPLEX,
    ),
)
