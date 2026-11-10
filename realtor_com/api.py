"""The /realtor-com/* endpoint functions (route_glue's route_table calls
them with the schema's loaded kwargs). Caching lives here (cache.cached_call),
keyed on the validated params:

  * a free-text location is resolved ONCE through the site's own
    search_suggestions (slug, city, state, ZIP) and shared by the market,
    agent-directory and school endpoints;
  * the seven per-property endpoints (details / history / estimates /
    schools / environment / popularity / neighborhood names) slice ONE
    cached home record, so a client hitting them all pays one upstream
    call; similar homes and neighborhood boundaries are their own queries;
  * an agent's profile is cached once and feeds agents/listings (through
    the fulfillment id) and agents/sold (through the MLS memberships).

Which upstream root serves what:
  locations/search            search_suggestions
  properties/search|nearby|polygon|batch|by-mls, agents/listings
                              home_search
  properties/details|history|estimates|schools|environment|popularity
                              home(property_id)
  properties/neighborhoods    home.location.neighborhoods (with boundary)
  properties/similar          home.related_homes
  communities/search          community_search
  agents/search               search_agents
  agents/details              agent_branding
  agents/reviews|recommendations
                              agent_branding_reviews / _recommendations
  agents/sold                 closings_search
  markets/stats|nearby        geo.geo_statistics / geo.recommended +
                              customer_nearby_locations
  mortgage/rates              mortgage_rate_trends
  schools/search              school_search
"""
import math
from datetime import date, timedelta

from cache import cached_call
from realtor_com import cache_config as ttl
from realtor_com import parsers, refs
from realtor_com import fetch as F
from realtor_com.fetch import RealtorNotFound
from realtor_com.schemas import AGENTS_OFFSET_CAP, SEARCH_OFFSET_CAP

CURRENCY = parsers.CURRENCY


# ---- helpers --------------------------------------------------------------------------

def _pagination(page, limit, total, cap=SEARCH_OFFSET_CAP):
    """The gateway serves the first `cap` rows of a query, so total_pages
    stops there even when the site counts more (total_count keeps the
    site's number)."""
    if total is None:
        return {"page": page, "items_per_page": limit, "total_pages": None, "total_count": None}
    reachable = min(int(total), cap)
    return {"page": page, "items_per_page": limit, "total_pages": max(1, math.ceil(reachable / limit)),
            "total_count": int(total)}


def _drop_nulls(data):
    return {k: v for k, v in data.items() if v is not None}


def _days_ago(days):
    return (date.today() - timedelta(days=days)).isoformat()


def _number(value):
    """Integral floats as ints: several criteria (hoa_fee, beds) are GraphQL
    Int and refuse 100.0 (2026-11-07)."""
    return int(value) if isinstance(value, float) and value.is_integer() else value


# ---- locations ------------------------------------------------------------------------

def _suggestions(query):
    return parsers.parse_suggestions(F.fetch_suggestions(query))


def _suggestions_cached(query):
    return cached_call("realtor_com.suggestions", {"query": " ".join(query.lower().split())},
                       _suggestions, ttl.LOCATIONS_CACHE)


def locations_search(query):
    rows = _suggestions_cached(query)
    return {"query": query, "count": len(rows), "results": rows}


_AREA_TYPES = ("city", "postal_code", "neighborhood", "county", "state", "school_district", "school",
               "university", "park", "street", "address")


def _geo_lookup(location):
    """Free text -> the site's own geo row for it (slug, city, state, ZIP)."""
    rows = _suggestions_cached(location)
    want_zip = refs.is_zip(location)
    for row in rows:
        if row.get("type") not in _AREA_TYPES:
            continue
        if want_zip and row.get("type") != "postal_code":
            continue
        if not row.get("slug"):
            continue
        return {
            "name": row.get("text"), "type": row.get("type"), "slug": row.get("slug"),
            "city": row.get("city"), "state_code": row.get("state_code"), "postal_code": row.get("postal_code"),
            "county": row.get("county"), "neighborhood": row.get("neighborhood"),
            "latitude": row.get("latitude"), "longitude": row.get("longitude"),
        }
    raise RealtorNotFound(f"No realtor.com location matches {location!r}")


def _geo(location):
    return cached_call("realtor_com.geo", {"location": " ".join(location.lower().split())},
                       _geo_lookup, ttl.GEO_CACHE)


# ---- listing search --------------------------------------------------------------------

def _criteria(data, status):
    """The validated filters -> a HomeSearchCriteria dict."""
    query = {"status": [status]}
    if data.get("property_types"):
        query["type"] = list(data["property_types"])
    for low, high, key in (("min_price", "max_price", "list_price"), ("min_beds", "max_beds", "beds"),
                           ("min_baths", "max_baths", "baths"), ("min_sqft", "max_sqft", "sqft"),
                           ("min_lot_sqft", "max_lot_sqft", "lot_sqft"), ("min_year_built", "max_year_built", "year_built")):
        bounds = {}
        if data.get(low) is not None:
            bounds["min"] = _number(data[low])
        if data.get(high) is not None:
            bounds["max"] = _number(data[high])
        if bounds:
            query[key] = bounds
    if data.get("max_hoa") is not None:
        query["hoa_fee"] = {"max": _number(data["max_hoa"])}
    # the gateway wants ISO dates in variables (its "$today-30D" macro only
    # expands inside query text, 2026-11-07)
    if data.get("listed_within_days"):
        query["list_date"] = {"min": _days_ago(int(data["listed_within_days"]))}
    if status == "sold" and data.get("sold_within_days"):
        query["sold_date"] = {"min": _days_ago(int(data["sold_within_days"]))}
    if data.get("include_pending") is True:
        query["or_filters"] = {"pending": True, "contingent": True}
    elif data.get("include_pending") is False:
        query["pending"] = False
        query["contingent"] = False
    for key in ("foreclosure", "new_construction"):
        if data.get(key) is not None:
            query[key] = bool(data[key])
    for key in ("cats", "dogs"):
        if data.get(key) is not None:
            # the gateway refuses the pet flags outside rentals ('"query.dogs" is not allowed', 2026-11-07)
            if status != "for_rent":
                raise ValueError(f"{key} applies to status=for_rent only.")
            query[key] = bool(data[key])
    if data.get("keywords"):
        query["keywords"] = list(data["keywords"])
    return query


def _sort(data, status):
    word = data.get("sort") or "relevant"
    if word == "relevant":
        return [{"field": "sold_date", "direction": "desc"}] if status == "sold" else None
    field, direction = refs.SEARCH_SORTS[word]
    return [{"field": field, "direction": direction}]


def _search_page(criteria, data, status, extra=None, site_order=True):
    page, limit = data.get("page") or 1, data.get("limit") or 50
    payload = F.fetch_search(criteria, limit, (page - 1) * limit, sort=_sort(data, status), site_order=site_order)
    cards, total = parsers.parse_search(payload)
    return {**(extra or {}), "status": status, "currency": CURRENCY, "results": cards,
            "pagination": _pagination(page, limit, total)}


def _search(**data):
    location = data.pop("location")
    status = data.pop("status")
    criteria = {**_criteria(data, status), "search_location": {"location": location}}
    try:
        return _search_page(criteria, data, status, {"location": location})
    except RealtorNotFound:
        # the gateway's own wording: "GeoParser API (Location not found or supported)"
        raise RealtorNotFound(f"No realtor.com location matches {location!r}")


def properties_search(**data):
    return cached_call("realtor_com.search", data, _search, ttl.SEARCH_CACHE)


def _search_nearby(**data):
    status = data.pop("status")
    latitude, longitude, radius = data.pop("latitude"), data.pop("longitude"), data.pop("radius")
    criteria = {**_criteria(data, status),
                "nearby": {"coordinates": [longitude, latitude], "radius": f"{radius:g}mi"}}
    # the site-order bucket is refused with a nearby query ("Check your
    # request", 2026-11-07): distance order is the gateway's own default
    return _search_page(criteria, data, status,
                        {"center": {"latitude": latitude, "longitude": longitude}, "radius_miles": radius},
                        site_order=False)


def properties_search_nearby(**data):
    return cached_call("realtor_com.search_nearby", data, _search_nearby, ttl.SEARCH_CACHE)


def _search_polygon(**data):
    status = data.pop("status")
    polygon = data.pop("polygon")
    criteria = {**_criteria(data, status), "boundary": {"type": "Polygon", "coordinates": [polygon]}}
    return _search_page(criteria, data, status, {"polygon": polygon})


def properties_search_polygon(**data):
    return cached_call("realtor_com.search_polygon", data, _search_polygon, ttl.SEARCH_CACHE)


def _batch(properties):
    payload = F.fetch_search({"property_id": list(properties)}, max(len(properties), 1), 0, site_order=False)
    cards, _ = parsers.parse_search(payload)
    found = {c["property_id"] for c in cards}
    return {"currency": CURRENCY, "count": len(cards), "results": cards,
            "missing": [p for p in properties if p not in found]}


def properties_batch(properties):
    return cached_call("realtor_com.batch", {"properties": sorted(properties)},
                       lambda **_: _batch(properties), ttl.SEARCH_CACHE)


def _by_mls(mls_id, mls_source=None):
    criteria = {"status": list(refs.SEARCH_STATUS), "source_listing_id": mls_id}
    if mls_source:
        criteria["source_id"] = mls_source.upper()
    payload = F.fetch_search(criteria, 20, 0, site_order=False)
    cards, _ = parsers.parse_search(payload)
    if not cards:
        raise RealtorNotFound(f"No realtor.com listing with MLS number {mls_id!r}"
                              + (f" in {mls_source.upper()}" if mls_source else ""))
    return {"mls_id": mls_id, "mls_source": mls_source.upper() if mls_source else None, "currency": CURRENCY,
            "count": len(cards), "results": cards}


def properties_by_mls(**data):
    return cached_call("realtor_com.by_mls", data, _by_mls, ttl.SEARCH_CACHE)


# ---- the shared home record ----------------------------------------------------------------

def _home_record(property_id):
    return parsers.parse_home(F.fetch_home(property_id))


def _record(property_id):
    return cached_call("realtor_com.property", {"property_id": property_id}, _home_record, ttl.PROPERTY_CACHE)


def _identity(record):
    return {"property_id": record["property_id"], "listing_id": record["listing_id"], "link": record["link"],
            "address": {k: record["address"].get(k) for k in ("line", "unit", "city", "state_code", "postal_code")}}


_DETAIL_SLICES = ("price_history", "tax_history", "estimates", "schools", "environment", "popularity")


def property_details(property):
    """Everything the gateway holds on one home except the layers with
    their own endpoints (price + tax history, estimates, schools,
    environment, popularity), which carry a headline here."""
    record = _record(property)
    out = {k: v for k, v in record.items() if k not in _DETAIL_SLICES}
    estimates = record.get("estimates") or {}
    out.update({
        "currency": CURRENCY,
        "estimate": estimates.get("estimate"),
        "estimate_source": estimates.get("estimate_source"),
        "price_history_count": len(record.get("price_history") or []),
        "tax_history_count": len(record.get("tax_history") or []),
        "views_last_30_days": next((p["views"] for p in record.get("popularity") or [] if p.get("days") == 30), None),
    })
    return out


def property_history(property):
    record = _record(property)
    return {**_identity(record), "currency": CURRENCY, "price_history": record["price_history"],
            "tax_history": record["tax_history"]}


def property_estimates(property):
    record = _record(property)
    return {**_identity(record), "currency": CURRENCY, **record["estimates"]}


def _nearby_schools(property_id, radius):
    return parsers.parse_schools(F.fetch_nearby_schools(property_id, radius))["nearby"]


def property_schools(property, radius=5):
    record = _record(property)
    schools = record["schools"]
    if float(radius) != F.NEARBY_SCHOOLS_RADIUS:
        nearby = cached_call("realtor_com.nearby_schools", {"property_id": property, "radius": float(radius)},
                             lambda **_: _nearby_schools(property, radius), ttl.PROPERTY_CACHE)
        schools = {**schools, "nearby": nearby}
    return {**_identity(record), "radius_miles": float(radius), **schools}


def property_environment(property):
    record = _record(property)
    return {**_identity(record), **(record["environment"] or parsers.parse_environment({}))}


def property_popularity(property):
    record = _record(property)
    return {**_identity(record), "periods": record["popularity"]}


def _neighborhoods(property_id):
    return parsers.parse_neighborhoods(F.fetch_neighborhoods(property_id))


def property_neighborhoods(property):
    record = _record(property)
    rows = cached_call("realtor_com.neighborhoods", {"property_id": property}, _neighborhoods, ttl.NEIGHBORHOODS_CACHE)
    return {**_identity(record), "count": len(rows), "neighborhoods": rows}


def _similar(property_id, status):
    home = F.fetch_similar(property_id, status)
    cards, _ = parsers.parse_search(home.get("related_homes") or {})
    return cards


def property_similar(property, status="for_sale"):
    record = _record(property)
    rows = cached_call("realtor_com.similar", {"property_id": property, "status": status},
                       _similar, ttl.SIMILAR_CACHE)
    return {**_identity(record), "status": status, "currency": CURRENCY, "count": len(rows), "results": rows}


# ---- communities ------------------------------------------------------------------------------

def _communities(location, limit, page):
    payload = F.fetch_communities({"search_location": {"location": location}}, limit, (page - 1) * limit)
    rows, total = parsers.parse_communities(payload)
    return {"location": location, "currency": CURRENCY, "results": rows, "pagination": _pagination(page, limit, total)}


def communities_search(**data):
    return cached_call("realtor_com.communities", data, _communities, ttl.COMMUNITIES_CACHE)


# ---- agents ------------------------------------------------------------------------------------

def _agents_search(**data):
    page, limit = data["page"], data["limit"]
    search_input = {"sort": refs.AGENT_SORTS[data.get("sort") or "relevant"], "limit": limit,
                    "offset": (page - 1) * limit}
    geo = None
    if data.get("location"):
        geo = _geo(data["location"])
        if geo.get("type") == "postal_code" and geo.get("postal_code"):
            search_input["postal_code"] = geo["postal_code"]
        elif geo.get("city") and geo.get("state_code"):
            search_input["marketing_area_city"] = f"{geo['state_code']}_{geo['city']}"
        else:
            raise RealtorNotFound(f"The agent directory covers cities and ZIP codes; {data['location']!r} "
                                  f"resolved to a {geo.get('type')}")
    if data.get("name"):
        search_input["name"] = data["name"]
    if data.get("language"):
        search_input["languages"] = [data["language"].lower()]
    if data.get("min_price") is not None:
        search_input["price_min"] = int(data["min_price"])
    if data.get("max_price") is not None:
        search_input["price_max"] = int(data["max_price"])
    agent_type = refs.AGENT_TYPES[data["agent_type"]] if data.get("agent_type") else None
    rows, total = parsers.parse_agents(F.fetch_agents(search_input, agent_type))
    return {"location": geo, "name": data.get("name"), "results": rows,
            "pagination": _pagination(page, limit, total, cap=AGENTS_OFFSET_CAP)}


def agents_search(**data):
    return cached_call("realtor_com.agents_search", _drop_nulls(data), lambda **_: _agents_search(**data),
                       ttl.AGENTS_SEARCH_CACHE)


def _agent_record(agent):
    return parsers.parse_agent(F.fetch_agent_branding(agent))


def _agent(agent):
    return cached_call("realtor_com.agent", {"agent": agent}, _agent_record, ttl.AGENT_CACHE)


def agent_details(agent):
    return _agent(agent)


def _agent_identity(record):
    return {"id": record["id"], "name": record["name"], "link": record["link"]}


def _agent_reviews(fulfillment_id):
    return parsers.parse_reviews(F.fetch_agent_reviews(fulfillment_id))


def agent_reviews(agent):
    record = _agent(agent)
    rows = cached_call("realtor_com.agent_reviews", {"agent": record["id"]}, lambda **_: _agent_reviews(record["id"]),
                       ttl.AGENT_REVIEWS_CACHE)
    return {**_agent_identity(record), "rating": record["rating"], "count": len(rows), "reviews": rows}


def _agent_recommendations(fulfillment_id):
    return parsers.parse_recommendations(F.fetch_agent_recommendations(fulfillment_id))


def agent_recommendations(agent):
    record = _agent(agent)
    rows = cached_call("realtor_com.agent_recommendations", {"agent": record["id"]},
                       lambda **_: _agent_recommendations(record["id"]), ttl.AGENT_REVIEWS_CACHE)
    return {**_agent_identity(record), "rating": record["rating"], "count": len(rows), "recommendations": rows}


def _agent_listings(fulfillment_id, status, limit, page):
    statuses = ["for_sale", "for_rent"] if status == "all" else [status]
    payload = F.fetch_search({"status": statuses, "fulfillment_id": fulfillment_id}, limit, (page - 1) * limit,
                             site_order=False)
    cards, total = parsers.parse_search(payload)
    return cards, total


def agent_listings(agent, status="all", limit=50, page=1):
    record = _agent(agent)
    rows, total = cached_call("realtor_com.agent_listings",
                              {"agent": record["id"], "status": status, "limit": limit, "page": page},
                              lambda **_: list(_agent_listings(record["id"], status, limit, page)),
                              ttl.AGENT_LISTINGS_CACHE)
    return {**_agent_identity(record), "status": status, "currency": CURRENCY, "results": rows,
            "pagination": _pagination(page, limit, total)}


def _agent_sold(record, limit, page):
    mls = [{"agent_id": m["agent_id"], "id": m["id"]} for m in record.get("mls") or [] if m.get("agent_id") and m.get("id")]
    if not mls:
        return [], 0
    payload = F.fetch_closings(mls, limit, (page - 1) * limit)
    return parsers.parse_closings(payload, [m["agent_id"] for m in mls])


def agent_sold(agent, limit=50, page=1):
    record = _agent(agent)
    rows, total = cached_call("realtor_com.agent_sold", {"agent": record["id"], "limit": limit, "page": page},
                              lambda **_: list(_agent_sold(record, limit, page)), ttl.AGENT_SOLD_CACHE)
    return {**_agent_identity(record), "currency": CURRENCY, "results": rows, "pagination": _pagination(page, limit, total)}


# ---- markets -------------------------------------------------------------------------------------

def _market(geo):
    payload = F.fetch_market(geo["slug"])
    if payload is None:
        raise RealtorNotFound(f"No realtor.com market stats for {geo['slug']}")
    market = parsers.parse_geo(payload)
    return {"location": geo, "currency": CURRENCY, "slug": market["slug"],
            "latitude": market["latitude"] or geo.get("latitude"), "longitude": market["longitude"] or geo.get("longitude"),
            **market["stats"]}


def market_stats(location):
    geo = _geo(location)
    return cached_call("realtor_com.market", {"slug": geo["slug"]}, lambda **_: _market(geo), ttl.MARKET_CACHE)


def _nearby(geo):
    data = F.fetch_nearby(geo["slug"], geo.get("city"), geo.get("state_code"))
    return {"location": geo, "currency": CURRENCY, **parsers.parse_nearby(data)}


def market_nearby(location):
    geo = _geo(location)
    return cached_call("realtor_com.market_nearby", {"slug": geo["slug"]}, lambda **_: _nearby(geo), ttl.MARKET_CACHE)


# ---- mortgage ------------------------------------------------------------------------------------

def _mortgage_rates(state, rate_type):
    rows = parsers.parse_mortgage_trends(F.fetch_mortgage_trends(state, refs.MORTGAGE_RATE_TYPES[rate_type]))
    return {"state": state, "rate_type": rate_type, "unit": "percent", "latest": rows[0] if rows else None,
            "count": len(rows), "rates": rows}


def mortgage_rates(**data):
    data["state"] = data["state"].upper()
    return cached_call("realtor_com.mortgage", data, _mortgage_rates, ttl.MORTGAGE_CACHE)


# ---- schools --------------------------------------------------------------------------------------

def _schools_search(geo, limit, page):
    if geo.get("type") == "postal_code" and geo.get("postal_code"):
        criteria = {"postal_code": geo["postal_code"]}
    elif geo.get("city") and geo.get("state_code"):
        criteria = {"city": geo["city"], "state_code": geo["state_code"]}
    else:
        raise RealtorNotFound(f"The school directory covers cities and ZIP codes; {geo.get('name')!r} "
                              f"is a {geo.get('type')}")
    rows, total = parsers.parse_school_search(F.fetch_schools(criteria, limit, (page - 1) * limit))
    return {"location": geo, "results": rows, "pagination": _pagination(page, limit, total)}


def schools_search(location, limit=50, page=1):
    geo = _geo(location)
    return cached_call("realtor_com.schools", {"slug": geo["slug"], "limit": limit, "page": page},
                       lambda **_: _schools_search(geo, limit, page), ttl.SCHOOLS_CACHE)
