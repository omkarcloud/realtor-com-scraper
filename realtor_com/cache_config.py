"""Cache TTL per /realtor-com/* endpoint (cache.py, keyed on the validated
params). Listings move by the hour (new listings, price drops, pendings),
so search pages are short; one property's record changes with its listing
events; the agent, market, school and mortgage layers move daily or
slower. The seven per-property endpoints (details / history / estimates /
schools / environment / popularity / rental) slice ONE cached home record
(api._record), so a client hitting all of them pays one upstream call.
"""
from datetime import timedelta

# search_suggestions rows: geos never move, new addresses are rare.
LOCATIONS_CACHE = timedelta(days=7)
# free text -> the site's slug / city + state (shared by markets and agents).
GEO_CACHE = timedelta(days=7)
# for-sale / rent / sold / nearby / polygon / MLS search pages.
SEARCH_CACHE = timedelta(minutes=30)
# the full home record every per-property endpoint slices.
PROPERTY_CACHE = timedelta(hours=3)
# neighborhood boundaries: static polygons.
NEIGHBORHOODS_CACHE = timedelta(days=7)
# similar homes: a listing feed.
SIMILAR_CACHE = timedelta(hours=1)
# new-construction communities: builders update weekly.
COMMUNITIES_CACHE = timedelta(hours=6)
# agent directory pages: ratings and deal counts move weekly.
AGENTS_SEARCH_CACHE = timedelta(hours=12)
# agent profile (also feeds listings / sold through its MLS memberships).
AGENT_CACHE = timedelta(hours=24)
AGENT_REVIEWS_CACHE = timedelta(hours=24)
# an agent's active listings: a listing feed.
AGENT_LISTINGS_CACHE = timedelta(hours=1)
# an agent's closings: new sales land daily.
AGENT_SOLD_CACHE = timedelta(hours=12)
# housing-market medians and hotness: the site aggregates monthly.
MARKET_CACHE = timedelta(hours=24)
# daily mortgage rates.
MORTGAGE_CACHE = timedelta(hours=6)
# school directory: a yearly feed.
SCHOOLS_CACHE = timedelta(days=3)
