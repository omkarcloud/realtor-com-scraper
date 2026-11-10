"""Raw GraphQL JSON -> clean dicts for every /realtor-com/* endpoint. Pure
functions, no I/O; every parser survives a partial or empty payload.

Value conventions (shared with the other scraper packages):
  * keys snake_case; `link` not `href`/`url`; booleans read as questions
  * identity first (id, name, link), then the main content, then ratings
    and stats, then nested objects, then metadata
  * prices are numbers with ONE top-level `currency: "USD"` per response
  * dates stay ISO as the site sends them ("2026-02-21" or
    "2026-02-21T14:21:38Z"); a null stays null, never "" or "N/A"
  * the site's `null` on a flag means false, so flags are real booleans
  * tracking junk (__typename, sorting_weight, lead_attributes, products,
    client-side display strings) is dropped

Fixtures (realtor_com/fixtures/, captured 2026-11-07 from the gateway with
the package's own queries): a for-sale search page, a rentals page, a sold
page (Seattle, with sale prices), an empty page, a full for-sale home, a
rental community home, an unknown-id error envelope, neighborhoods with
boundaries, similar homes, agents search, an agent profile + reviews +
recommendations + closings, market stats for a city and a ZIP, nearby
locations, suggestions, mortgage trends, schools and new-home communities.
"""
from realtor_com import refs

CURRENCY = "USD"


# ---- helpers -------------------------------------------------------------------------

def _get(obj, *path):
    for key in path:
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _num(value):
    """int / float as given; numeric strings parsed; anything else None."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        text = value.replace(",", "").replace("$", "").strip()
        try:
            number = float(text)
        except ValueError:
            return None
        return int(number) if number.is_integer() else number
    return None


def _int(value):
    number = _num(value)
    return int(number) if isinstance(number, (int, float)) else None


def _str(value):
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def _bool(value):
    return bool(value) if value is not None else False


def _list(value):
    return value if isinstance(value, list) else []


def _links(photos):
    out = []
    for photo in _list(photos):
        href = _get(photo, "href") if isinstance(photo, dict) else photo
        if isinstance(href, str) and href:
            out.append(_https(href))
    return out


def _https(href):
    return "https://" + href[len("http://"):] if isinstance(href, str) and href.startswith("http://") else href


def _site_link(href):
    if not href:
        return None
    if href.startswith("/"):
        return refs.SITE + href
    return _https(href)


def _phone(phone):
    if not isinstance(phone, dict):
        return None
    number = _str(phone.get("number")) or _str(phone.get("value"))
    if not number:
        return None
    return {
        "number": number,
        "type": (_str(phone.get("type")) or "").lower() or None,
        "is_primary": _bool(phone.get("primary")),
        "extension": _str(phone.get("ext")),
    }


def _phones(phones):
    return [p for p in (_phone(x) for x in _list(phones)) if p]


def _coordinate(coord):
    return {"latitude": _num(_get(coord, "lat")), "longitude": _num(_get(coord, "lon"))}


def _address(location):
    address = _get(location, "address") or {}
    county = _get(location, "county") or {}
    return {
        "line": _str(address.get("line")),
        "unit": _str(address.get("unit")),
        "city": _str(address.get("city")),
        "state_code": _str(address.get("state_code")),
        "state": _str(address.get("state")),
        "postal_code": _str(address.get("postal_code")),
        "county": _str(county.get("name")),
        "county_fips": _str(county.get("fips_code")),
        **_coordinate(address.get("coordinate")),
        "neighborhoods": [n for n in (_str(_get(x, "name")) for x in _list(_get(location, "neighborhoods"))) if n],
    }


_FLAG_KEYS = ("is_new_listing", "is_pending", "is_contingent", "is_coming_soon", "is_price_reduced",
              "is_new_construction", "is_foreclosure", "is_short_sale", "is_senior_community", "is_for_rent",
              "is_garage_present", "is_deal_available", "is_subdivision", "is_plan")


def _flags(flags):
    flags = flags or {}
    return {key: _bool(flags.get(key)) for key in _FLAG_KEYS}


def _office(office):
    if not isinstance(office, dict):
        return None
    out = {
        "id": _str(office.get("fulfillment_id")),
        "name": _str(office.get("name")),
        "email": _str(office.get("email")),
        "link": _https(_str(office.get("href"))),
        "phones": _phones(office.get("phones")),
    }
    if isinstance(office.get("address"), dict):
        address = office["address"]
        out["address"] = {
            "line": _str(address.get("line")) or _str(address.get("address_formatted_line_1")),
            "city": _str(address.get("city")),
            "state_code": _str(address.get("state_code")),
            "postal_code": _str(address.get("postal_code")),
        }
    return out


def _named(obj):
    """{name, fulfillment_id} -> {id, name} or None."""
    if not isinstance(obj, dict) or not (obj.get("name") or obj.get("fulfillment_id")):
        return None
    return {"id": _str(obj.get("fulfillment_id")), "name": _str(obj.get("name")),
            **({"link": _https(_str(obj["href"]))} if obj.get("href") else {})}


def _advertiser(adv):
    """A listing's advertiser (agent / office / builder / rental manager)."""
    if not isinstance(adv, dict):
        return None
    return {
        "id": _str(adv.get("fulfillment_id")),
        "name": _str(adv.get("name")),
        "type": (_str(adv.get("type")) or "").lower() or None,
        "email": _str(adv.get("email")),
        "phones": _phones(adv.get("phones")),
        "website": _https(_str(adv.get("href"))),
        "slogan": _str(adv.get("slogan")),
        "photo": _https(_get(adv, "photo", "href")),
        "license": _str(adv.get("state_license")),
        "nrds_id": _str(adv.get("nrds_id")),
        "mls_set": _str(adv.get("mls_set")),
        "office": _office(adv.get("office")),
        "broker": _named(adv.get("broker")),
        "builder": _named(adv.get("builder")),
    }


def _estimate(est):
    if not isinstance(est, dict):
        return None
    return {
        "source": _str(_get(est, "source", "name")),
        "source_type": _str(_get(est, "source", "type")),
        "estimate": _num(est.get("estimate")),
        "estimate_high": _num(est.get("estimate_high")),
        "estimate_low": _num(est.get("estimate_low")),
        "date": _str(est.get("date")),
        "is_best": _bool(est.get("isbest_homevalue")),
    }


def _open_house(oh):
    if not isinstance(oh, dict):
        return None
    return {"start": _str(oh.get("start_date")), "end": _str(oh.get("end_date")),
            "description": _str(oh.get("description")), "methods": [_str(m) for m in _list(oh.get("methods")) if m]}


def _unit(unit):
    if not isinstance(unit, dict):
        return None
    desc = unit.get("description") or {}
    return {
        "price": _num(unit.get("list_price")),
        "beds": _num(desc.get("beds")),
        "baths": _num(desc.get("baths")) if desc.get("baths") is not None else _num(desc.get("baths_consolidated")),
        "sqft": _num(desc.get("sqft")),
        "available_date": _str(_get(unit, "availability", "date")),
        "photos": _links(unit.get("photos")),
    }


def _pet_policy(policy):
    if not isinstance(policy, dict):
        return None
    return {"cats": policy.get("cats"), "dogs": policy.get("dogs"),
            "small_dogs": policy.get("dogs_small"), "large_dogs": policy.get("dogs_large")}


def _mls(source):
    if not isinstance(source, dict):
        return None
    return {
        "id": _str(source.get("id")),
        "name": _str(source.get("name")),
        "type": _str(source.get("type")),
        "listing_id": _str(source.get("listing_id")),
        "agents": [{"name": _str(a.get("agent_name")), "id": _str(a.get("agent_id")),
                    "office_name": _str(a.get("office_name")), "office_id": _str(a.get("office_id"))}
                   for a in _list(source.get("agents")) if isinstance(a, dict)],
        "disclaimer": _str(_get(source, "disclaimer", "text")),
    }


def _description_core(desc):
    desc = desc or {}
    return {
        "property_type": _str(desc.get("type")),
        "sub_type": _str(desc.get("sub_type")),
        "beds": _num(desc.get("beds")),
        "baths": _num(desc.get("baths")) if desc.get("baths") is not None else _num(desc.get("baths_consolidated")),
        "baths_full": _num(desc.get("baths_full")),
        "baths_half": _num(desc.get("baths_half")),
        "sqft": _num(desc.get("sqft")),
        "lot_sqft": _num(desc.get("lot_sqft")),
        "year_built": _num(desc.get("year_built")),
        "garage": _num(desc.get("garage")),
        "stories": _num(desc.get("stories")),
    }


# ---- search cards --------------------------------------------------------------------

def parse_card(card):
    """One home_search / related_homes result -> a listing card."""
    if not isinstance(card, dict):
        return None
    desc = card.get("description") or {}
    record = {
        "property_id": _str(card.get("property_id")),
        "listing_id": _str(card.get("listing_id")),
        "name": _str(desc.get("name")),
        "link": _https(_str(card.get("href"))) or refs.property_link({"permalink": card.get("permalink"),
                                                                        "status": card.get("status")}),
        "permalink": _str(card.get("permalink")),
        "status": _str(card.get("status")),
        "mls_status": _str(card.get("mls_status")),
        "price": _num(card.get("list_price")),
        "price_min": _num(card.get("list_price_min")),
        "price_max": _num(card.get("list_price_max")),
        "price_per_sqft": _num(card.get("price_per_sqft")),
        "last_sold_price": _num(card.get("last_sold_price")),
        "last_sold_date": _str(card.get("last_sold_date")),
        **_description_core(desc),
        "hoa_fee": _num(_get(card, "hoa", "fee")),
        "address": _address(card.get("location")),
        "photo": _https(_get(card, "primary_photo", "href")),
        "photos": _links(card.get("photos")),
        "tags": [_str(t) for t in _list(card.get("tags")) if t],
        "flags": _flags(card.get("flags")),
        "open_houses": [o for o in (_open_house(x) for x in _list(card.get("open_houses"))) if o],
        "virtual_tours": [{"link": _https(_str(v.get("href"))), "type": _str(v.get("type"))}
                          for v in _list(card.get("virtual_tours")) if isinstance(v, dict) and v.get("href")],
        "estimates": [e for e in (_estimate(x) for x in _list(card.get("current_estimates"))) if e],
        "advertisers": [a for a in (_advertiser(x) for x in _list(card.get("advertisers"))) if a],
        "mls": _mls(card.get("source")),
        "pet_policy": _pet_policy(card.get("pet_policy")),
        "units": [u for u in (_unit(x) for x in _list(card.get("units"))) if u],
        "tax_record": {"apn": _str(_get(card, "tax_record", "apn")),
                       "parcel_id": _str(_get(card, "tax_record", "tax_parcel_id"))}
        if isinstance(card.get("tax_record"), dict) else None,
        "list_date": _str(card.get("list_date")),
        "pending_date": _str(card.get("pending_date")),
        "last_status_change_date": _str(card.get("last_status_change_date")),
        "last_update_date": _str(card.get("last_update_date")),
    }
    return record


def parse_search(payload):
    """home_search payload -> (cards, total)."""
    payload = payload or {}
    cards = [c for c in (parse_card(x) for x in _list(payload.get("results"))) if c]
    return cards, _int(payload.get("total"))


# ---- the full home record -----------------------------------------------------------------

def _detail_sections(details):
    out = []
    for section in _list(details):
        if not isinstance(section, dict):
            continue
        out.append({"category": _str(section.get("category")),
                    "parent_category": _str(section.get("parent_category")),
                    "items": [_str(t) for t in _list(section.get("text")) if t]})
    return out


def _photo(photo):
    if not isinstance(photo, dict) or not photo.get("href"):
        return None
    tags = [{"label": _str(t.get("label")), "probability": _num(t.get("probability"))}
            for t in _list(photo.get("tags")) if isinstance(t, dict) and t.get("label")]
    return {"link": _https(photo["href"]), "title": _str(photo.get("title")), "tags": tags}


def _history_event(event):
    if not isinstance(event, dict):
        return None
    listing = event.get("listing") or {}
    return {
        "date": _str(event.get("date")),
        "event": _str(event.get("event_name")),
        "price": _num(event.get("price")),
        "price_change": _num(event.get("price_change")),
        "price_change_percentage": _num(event.get("price_change_percentage")),
        "price_per_sqft": _num(event.get("price_sqft")),
        "days_after_listed": _num(event.get("days_after_listed")),
        "source": _str(event.get("source_name")),
        "source_listing_id": _str(event.get("source_listing_id")),
        "listing": {
            "listing_id": _str(listing.get("listing_id")),
            "status": _str(listing.get("status")),
            "price": _num(listing.get("list_price")),
            "list_date": _str(listing.get("list_date")),
            "last_status_change_date": _str(listing.get("last_status_change_date")),
            "last_update_date": _str(listing.get("last_update_date")),
            "sqft": _num(_get(listing, "description", "sqft")),
            "photos": _links(listing.get("photos")),
        } if listing else None,
    }


def _tax_year(row):
    if not isinstance(row, dict):
        return None
    assessment = row.get("assessment") or {}
    market = row.get("market") or {}
    return {
        "year": _int(row.get("year")),
        "tax": _num(row.get("tax")),
        "assessment": {"building": _num(assessment.get("building")), "land": _num(assessment.get("land")),
                       "total": _num(assessment.get("total"))},
        "market_value": {"building": _num(market.get("building")), "land": _num(market.get("land")),
                         "total": _num(market.get("total"))},
    }


def _estimate_series(rows):
    out = []
    for row in _list(rows):
        if not isinstance(row, dict):
            continue
        out.append({"source": _str(_get(row, "source", "name")), "source_type": _str(_get(row, "source", "type")),
                    "values": [{"date": _str(v.get("date")), "estimate": _num(v.get("estimate"))}
                               for v in _list(row.get("estimates")) if isinstance(v, dict)]})
    return out


def parse_estimates(estimates):
    estimates = estimates or {}
    current = [e for e in (_estimate(x) for x in _list(estimates.get("current_values"))) if e]
    best = next((e for e in current if e["is_best"]), current[0] if current else None)
    return {
        "estimate": best["estimate"] if best else None,
        "estimate_high": best["estimate_high"] if best else None,
        "estimate_low": best["estimate_low"] if best else None,
        "estimate_source": best["source"] if best else None,
        "estimate_date": best["date"] if best else None,
        "current": current,
        "forecast": _estimate_series(estimates.get("forecast_values")),
        "history": _estimate_series(estimates.get("historical_values")),
    }


def _school(school):
    if not isinstance(school, dict):
        return None
    return {
        "id": _str(school.get("id")),
        "name": _str(school.get("name")),
        "rating": _num(school.get("rating")),
        "parent_rating": _num(school.get("parent_rating")),
        "funding_type": _str(school.get("funding_type")),
        "levels": [_str(x) for x in _list(school.get("education_levels")) if x],
        "grades": [_str(x) for x in _list(school.get("grades")) if x],
        "student_count": _int(school.get("student_count")),
        "distance_miles": _num(school.get("distance_in_miles")),
        "is_assigned": _bool(school.get("assigned")),
        "city": _str(_get(school, "location", "city")),
        **_coordinate(school.get("coordinate")),
        "district": {"id": _str(_get(school, "district", "id")), "name": _str(_get(school, "district", "name"))}
        if isinstance(school.get("district"), dict) else None,
    }


def parse_schools(home):
    home = home or {}
    assigned = [s for s in (_school(x) for x in _list(_get(home, "schools", "schools"))) if s]
    nearby = [s for s in (_school(x) for x in _list(_get(home, "nearby_schools", "schools"))) if s]
    return {"assigned": assigned, "nearby": nearby}


def parse_environment(local):
    local = local or {}
    noise = local.get("noise") or {}
    flood = local.get("flood") or {}
    return {
        "noise": {"score": _num(noise.get("score")),
                  "categories": [{"type": _str(c.get("type")), "text": _str(c.get("text"))}
                                 for c in _list(noise.get("noise_categories")) if isinstance(c, dict)]},
        "flood": {"fema_zones": [_str(z) for z in _list(flood.get("fema_zone")) if z],
                  "score": _num(flood.get("flood_factor_score")), "severity": _str(flood.get("flood_factor_severity")),
                  "trend": _str(flood.get("flood_trend")), "insurance": _str(flood.get("flood_insurance_text"))},
        "wildfire": {"score": _num(_get(local, "wildfire", "fire_factor_score")),
                     "severity": _str(_get(local, "wildfire", "fire_factor_severity"))},
        "heat": {"score": _num(_get(local, "heat", "heat_factor_score")),
                 "severity": _str(_get(local, "heat", "heat_factor_severity"))},
        "wind": {"score": _num(_get(local, "wind", "wind_factor_score"))},
        "air": {"score": _num(_get(local, "air", "air_factor_score"))},
    }


def parse_popularity(popularity):
    periods = []
    for period in _list(_get(popularity, "periods")):
        if not isinstance(period, dict):
            continue
        periods.append({
            "days": _int(period.get("last_n_days")),
            "views": _int(period.get("views_total")),
            "saves": _int(period.get("saves_total")),
            "clicks": _int(period.get("clicks_total")),
            "shares": _int(period.get("shares_total")),
            "leads": _int(period.get("leads_total")),
        })
    return periods


def _mortgage(mortgage):
    if not isinstance(mortgage, dict):
        return None
    estimate = mortgage.get("estimate") or {}
    return {
        "monthly_payment": _num(estimate.get("monthly_payment")),
        "total_payment": _num(estimate.get("total_payment")),
        "loan_amount": _num(estimate.get("loan_amount")),
        "down_payment": _num(estimate.get("down_payment")),
        "monthly_breakdown": [{"type": _str(d.get("type")), "name": _str(d.get("display_name")),
                               "amount": _num(d.get("amount"))}
                              for d in _list(estimate.get("monthly_payment_details")) if isinstance(d, dict)],
        "property_tax_rate": _num(mortgage.get("property_tax_rate")),
        "insurance_rate": _num(mortgage.get("insurance_rate")),
        "rates_link": _https(_str(mortgage.get("rates_url"))),
    }


def _fees(rows):
    return [{"description": _str(f.get("description")), "amount": _str(f.get("display_amount"))}
            for f in _list(rows) if isinstance(f, dict)]


def _community(community):
    if not isinstance(community, dict):
        return None
    return {
        "name": _str(_get(community, "description", "name")),
        "link": _https(_str(community.get("href"))),
        "description": _str(_get(community, "description", "text")),
        "advertisers": [a for a in (_advertiser(x) for x in _list(community.get("advertisers"))) if a],
    }


def _consumer_advertiser(adv):
    if not isinstance(adv, dict):
        return None
    href = _str(adv.get("href"))
    return {
        "type": (_str(adv.get("type")) or "").lower() or None,
        "name": _str(adv.get("name")),
        "agent_id": _str(adv.get("agent_id")),
        "office_id": _str(adv.get("office_id")),
        "phone": _str(adv.get("phone")),
        "link": _site_link(href),
    }


def _neighborhood(n, with_boundary=False):
    if not isinstance(n, dict):
        return None
    out = {
        "id": _str(n.get("id")),
        "name": _str(n.get("name")),
        "level": _str(n.get("level")),
        "type": _str(n.get("geo_type")),
        "slug": _str(n.get("slug_id")),
        "city": _str(n.get("city")),
        "state_code": _str(n.get("state_code")),
        **_coordinate(n.get("centroid")),
    }
    if with_boundary:
        out["boundary"] = n.get("boundary")
    return out


def parse_home(home):
    """The full home record (every section the gateway returns for one
    property). api.py slices it per endpoint."""
    home = home or {}
    desc = home.get("description") or {}
    raw = _get(home, "source", "raw") or {}
    return {
        "property_id": _str(home.get("property_id")),
        "listing_id": _str(home.get("listing_id")),
        "name": _str(desc.get("name")),
        "link": _https(_str(home.get("href"))) or refs.property_link(home),
        "permalink": _str(home.get("permalink")),
        "status": _str(home.get("status")),
        "mls_status": _str(home.get("mls_status")),
        "price": _num(home.get("list_price")),
        "price_min": _num(home.get("list_price_min")),
        "price_max": _num(home.get("list_price_max")),
        "price_per_sqft": _num(home.get("price_per_sqft")),
        "last_price_change": _num(home.get("last_price_change_amount")),
        "last_price_change_date": _str(home.get("last_price_change_date")),
        "last_sold_price": _num(home.get("last_sold_price")),
        "last_sold_date": _str(home.get("last_sold_date")),
        **_description_core(desc),
        "beds_min": _num(desc.get("beds_min")),
        "beds_max": _num(desc.get("beds_max")),
        "baths_min": _num(desc.get("baths_min")),
        "baths_max": _num(desc.get("baths_max")),
        "sqft_min": _num(desc.get("sqft_min")),
        "sqft_max": _num(desc.get("sqft_max")),
        "style": _str(raw.get("style")),
        "description": _str(desc.get("text")),
        "details": _detail_sections(home.get("details")),
        "hoa_fee": _num(_get(home, "hoa", "fee")),
        "annual_tax": _num(raw.get("tax_amount")),
        "address": {**_address(home.get("location")),
                    "parcel_id": _str(_get(home, "location", "parcel", "parcel_id")),
                    "street_view_link": _https(_str(_get(home, "location", "street_view_url")))},
        "neighborhoods": [n for n in (_neighborhood(x) for x in _list(_get(home, "location", "neighborhoods"))) if n],
        "photo": _https(_get(home, "primary_photo", "href")),
        "photo_count": _int(home.get("photo_count")),
        "photos": [p for p in (_photo(x) for x in _list(home.get("photos"))) if p],
        "virtual_tours": [{"link": _https(_str(v.get("href"))), "type": _str(v.get("type"))}
                          for v in _list(home.get("virtual_tours")) if isinstance(v, dict) and v.get("href")],
        "matterport_videos": _links(_get(home, "matterport", "videos")),
        "tags": [_str(t) for t in _list(home.get("tags")) if t],
        "flags": _flags(home.get("flags")),
        "open_houses": [o for o in (_open_house(x) for x in _list(home.get("open_houses"))) if o],
        "advertisers": [a for a in (_advertiser(x) for x in _list(home.get("advertisers"))) if a],
        "listing_contacts": [c for c in (_consumer_advertiser(x) for x in _list(home.get("consumer_advertisers"))) if c],
        "mls": _mls(home.get("source")),
        "mortgage": _mortgage(home.get("mortgage")),
        "rental": {
            "units": [u for u in (_unit(x) for x in _list(home.get("units"))) if u],
            "pet_policy": _pet_policy(home.get("pet_policy")),
            "monthly_fees": _fees(home.get("monthly_fees")),
            "one_time_fees": _fees(home.get("one_time_fees")),
            "terms": [{"category": _str(t.get("category")), "text": _str(t.get("text"))}
                      for t in _list(home.get("terms")) if isinstance(t, dict)],
            "community": _community(home.get("community")),
        } if (home.get("units") or home.get("pet_policy") or home.get("monthly_fees") or home.get("terms")
              or home.get("community") or home.get("status") == "for_rent") else None,
        "tax_record": {"apn": _str(_get(home, "tax_record", "apn")),
                       "parcel_id": _str(_get(home, "tax_record", "tax_parcel_id"))}
        if isinstance(home.get("tax_record"), dict) else None,
        "price_history": [e for e in (_history_event(x) for x in _list(home.get("property_history"))) if e],
        "tax_history": [t for t in (_tax_year(x) for x in _list(home.get("tax_history"))) if t],
        "estimates": parse_estimates(home.get("estimates")),
        "schools": parse_schools(home),
        "environment": parse_environment(home.get("local")) if home.get("local") else None,
        "popularity": parse_popularity(home.get("popularity")),
        "list_date": _str(home.get("list_date")),
        "pending_date": _str(home.get("pending_date")),
        "days_on_market": _int(home.get("days_on_market")),
        "last_status_change_date": _str(home.get("last_status_change_date")),
        "last_update_date": _str(home.get("last_update_date")),
    }


def parse_neighborhoods(home):
    return [n for n in (_neighborhood(x, with_boundary=True)
                        for x in _list(_get(home, "location", "neighborhoods"))) if n]


# ---- communities ----------------------------------------------------------------------

def parse_community(card):
    if not isinstance(card, dict):
        return None
    desc = card.get("description") or {}
    return {
        "id": _str(card.get("property_id")),
        "name": _str(desc.get("name")),
        "link": _https(_str(card.get("href"))),
        "status": _str(card.get("status")),
        "price_min": _num(card.get("list_price_min")),
        "price_max": _num(card.get("list_price_max")),
        "property_type": _str(desc.get("type")),
        "beds_min": _num(desc.get("beds_min")),
        "beds_max": _num(desc.get("beds_max")),
        "baths_min": _num(desc.get("baths_min")),
        "baths_max": _num(desc.get("baths_max")),
        "sqft_min": _num(desc.get("sqft_min")),
        "sqft_max": _num(desc.get("sqft_max")),
        "description": _str(desc.get("text")),
        "address": _address(card.get("location")),
        "photo": _https(_get(card, "primary_photo", "href")),
        "photo_count": _int(card.get("photo_count")),
        "photos": _links(card.get("photos")),
        "is_new_construction": _bool(_get(card, "flags", "is_new_construction")),
        "advertisers": [a for a in (_advertiser(x) for x in _list(card.get("advertisers"))) if a],
    }


def parse_communities(payload):
    payload = payload or {}
    rows = [c for c in (parse_community(x) for x in _list(payload.get("results"))) if c]
    return rows, _int(payload.get("total"))


# ---- locations ------------------------------------------------------------------------

def parse_suggestion(row):
    """One geo_results row -> a location suggestion."""
    geo = _get(row, "geo") or {}
    if not isinstance(row, dict) or not geo:
        return None
    area_type = _str(geo.get("area_type"))
    return {
        "type": area_type,
        "text": _str(row.get("text")),
        "slug": _str(geo.get("slug_id")),
        "geo_id": _str(geo.get("geo_id")),
        "city": _str(geo.get("city")),
        "city_slug": _str(geo.get("city_slug_id")),
        "state_code": _str(geo.get("state_code")),
        "postal_code": _str(geo.get("postal_code")),
        "county": _str(geo.get("county")),
        "neighborhood": _str(geo.get("neighborhood")),
        "street": _str(geo.get("street")),
        "address": _str(geo.get("line")),
        "school": _str(geo.get("school")),
        "school_district": _str(geo.get("school_district")),
        "property_id": _str(geo.get("mpr_id")),
        **_coordinate(geo.get("centroid")),
    }


def parse_suggestions(payload):
    payload = payload or {}
    return [s for s in (parse_suggestion(x) for x in _list(payload.get("geo_results"))) if s]


# ---- agents ---------------------------------------------------------------------------

def _rating(ratings):
    ratings = ratings or {}
    return {
        "average": _num(ratings.get("average_rating")),
        "reviews_count": _int(ratings.get("reviews_count")),
        "recommendations_count": _int(ratings.get("recommendations_count")),
        "total_count": _int(ratings.get("combined_testimonials_and_reviews_count")),
    }


def _listing_stats(stats):
    stats = stats or {}
    for_sale = stats.get("for_sale") or {}
    sold = stats.get("recently_sold") or {}
    recent = _get(stats, "recently_sold_listing_details", "listings")
    return {
        "price_range_min": _num(_get(stats, "combined_annual", "min")),
        "price_range_max": _num(_get(stats, "combined_annual", "max")),
        "for_sale": {"count": _int(for_sale.get("count")), "last_listing_date": _str(for_sale.get("last_listing_date")),
                     "price_min": _num(for_sale.get("min")), "price_max": _num(for_sale.get("max"))},
        "sold": {"count": _int(sold.get("count")), "last_sold_date": _str(sold.get("last_sold_date")),
                 "price_min": _num(sold.get("min")), "price_max": _num(sold.get("max"))} if sold else None,
        "sold_last_year_count": _int(_get(stats, "recently_sold_annual", "count")),
        "recent_sales": [{"beds": _num(l.get("beds")), "baths": _num(l.get("baths")), "city": _str(l.get("city")),
                          "state_code": _str(l.get("state_code")), "photo": _https(_str(l.get("photo")))}
                         for l in _list(recent) if isinstance(l, dict)],
    }


def agent_link(fulfillment_id, profile_id=None):
    """The agent's canonical profile page; the site resolves the bare
    profile id (the 24-hex `id` of a card)."""
    if profile_id:
        return f"{refs.SITE}/realestateagents/{profile_id}"
    return f"{refs.SITE}/realestateagents/{fulfillment_id}" if fulfillment_id else None


def parse_agent_card(agent):
    if not isinstance(agent, dict):
        return None
    return {
        "id": _str(agent.get("fulfillment_id")),
        "profile_id": _str(agent.get("id")),
        "name": _str(agent.get("fullname")),
        "link": agent_link(_str(agent.get("fulfillment_id")), _str(agent.get("id"))),
        "photo": _https(_get(agent, "avatar", "url")),
        "broker": _named(agent.get("broker")),
        "office": _str(_get(agent, "office", "name")),
        "is_realtor": _bool(agent.get("is_realtor")),
        "is_paid": _bool(agent.get("is_paid")),
        "is_realchoice_select": _bool(agent.get("has_rps")),
        "rating": _rating(agent.get("ratings_reviews")),
        "listings": _listing_stats(agent.get("listing_stats")),
        "experience_since": _int(_get(agent, "experience", "first_year")),
        "services": {"buyer": [_str(s) for s in _list(_get(agent, "services", "buyer")) if s],
                     "seller": [_str(s) for s in _list(_get(agent, "services", "seller")) if s]},
    }


def parse_agents(payload):
    payload = payload or {}
    rows = [a for a in (parse_agent_card(x) for x in _list(payload.get("agents"))) if a]
    return rows, _int(payload.get("matching_rows"))


def parse_agent(branding):
    """agent_branding.branding -> the full profile."""
    b = branding or {}
    office = b.get("office") or {}
    address = office.get("address") or {}
    social = b.get("social_media") or {}
    experience = b.get("experience") or {}
    return {
        "id": _str(b.get("fulfillment_id")),
        "profile_id": _str(b.get("id")),
        "name": _str(b.get("fullname")),
        "link": agent_link(_str(b.get("fulfillment_id")), _str(b.get("id"))),
        "photo": _https(_get(b, "avatar", "url")),
        "bio": _str(b.get("bio")) if b.get("bio") else None,
        "website": _https(_str(b.get("website"))),
        "phones": _phones(b.get("phones")),
        "license": {"number": _str(b.get("license_number")), "state_code": _str(b.get("license_state"))},
        "designations": [_str(d) for d in _list(b.get("designations")) if d],
        "languages": [_str(x) for x in _list(b.get("languages")) if x],
        "specializations": [_str(_get(s, "name")) for s in _list(b.get("specializations")) if _get(s, "name")],
        "represents": [(_str(t) or "").lower() for t in _list(b.get("intent_type")) if t],
        "served_areas": [{"name": _str(a.get("name")), "state_code": _str(a.get("state_code"))}
                         for a in _list(b.get("served_areas")) if isinstance(a, dict)],
        "is_realtor": _bool(b.get("is_realtor")),
        "is_paid": _bool(b.get("is_paid")),
        "is_realchoice_select": _bool(b.get("has_rps")),
        "rating": _rating(b.get("ratings_reviews")),
        "listings": _listing_stats(b.get("listing_stats")),
        "experience": {"since_year": _int(experience.get("first_year")), "since_month": _str(experience.get("first_month")),
                       "label": _str(experience.get("label"))},
        "services": {"buyer": [_str(s) for s in _list(_get(b, "services", "buyer")) if s],
                     "seller": [_str(s) for s in _list(_get(b, "services", "seller")) if s]},
        "mls": [{"id": _str(m.get("id")), "agent_id": _str(m.get("agent_id")), "mls_set": _str(m.get("mls_set")),
                 "license_number": _str(m.get("license_number")), "status": _str(m.get("status")),
                 "is_primary": _bool(m.get("primary")), "inactivation_date": _str(m.get("inactivation_date"))}
                for m in _list(b.get("mls")) if isinstance(m, dict)],
        "broker": {"id": _str(_get(b, "broker", "fulfillment_id")), "name": _str(_get(b, "broker", "name")),
                   "website": _https(_str(_get(b, "broker", "website")))} if b.get("broker") else None,
        "office": {
            "name": _str(office.get("name")),
            "website": _https(_str(office.get("website"))),
            "phones": _phones(office.get("phones")),
            "address": {"line": _str(address.get("address_formatted_line_1")),
                        "line2": _str(address.get("address_formatted_line_2")),
                        "city": _str(address.get("city")), "state_code": _str(address.get("state_code")),
                        "postal_code": _str(address.get("postal_code"))} if address else None,
        } if office else None,
        "social_media": {name: _https(_str(_get(social, name, "href"))) for name in
                         ("facebook", "instagram", "linkedin", "tiktok", "x", "youtube")},
        "video": {"source": _str(_get(b, "about_video", "source")), "id": _str(_get(b, "about_video", "id")),
                  "link": _https(_str(_get(b, "about_video", "url")))} if b.get("about_video") else None,
        "questions_and_answers": [{"question": _str(q.get("question_text")), "answer": _str(q.get("answer_text"))}
                                  for q in _list(b.get("questions_and_answers")) if isinstance(q, dict)],
        "is_empty_profile": _bool(b.get("is_empty_profile")),
    }


def parse_reviews(payload):
    out = []
    for review in _list(_get(payload, "reviews")):
        if not isinstance(review, dict):
            continue
        reply = review.get("reply") or {}
        out.append({
            "id": _str(review.get("id")),
            "rating": _num(review.get("rating")),
            "sub_ratings": {
                "responsiveness": _num(review.get("responsiveness")),
                "market_expertise": _num(review.get("market_expertise")),
                "negotiation_skills": _num(review.get("negotiation_skills")),
                "professionalism_communication": _num(review.get("professionalism_communication")),
            },
            "comment": _str(review.get("comment")),
            "reviewer": {"name": _str(review.get("display_name")), "role": _str(review.get("describe_yourself")),
                         "location": _str(review.get("location"))},
            "year": _int(review.get("year")),
            "date": _str(review.get("started_timestamp")),
            "date_label": _str(review.get("review_date_display")),
            "reply": {"message": _str(reply.get("message")), "date": _str(reply.get("reply_date"))}
            if reply.get("message") else None,
            "source": _str(review.get("source_id")),
        })
    return out


def parse_recommendations(payload):
    out = []
    for rec in _list(_get(payload, "recommendations")):
        if not isinstance(rec, dict):
            continue
        out.append({
            "comment": _str(rec.get("comment")),
            "name": _str(rec.get("display_name")),
            "date": _str(rec.get("started_timestamp")),
            "last_updated": _str(rec.get("last_updated")),
            "source": _str(rec.get("source_id")),
        })
    return out


def parse_closing(row, agent_mls_ids=()):
    """One closings_search result -> a closed deal; `agent_mls_ids` = the
    agent's MLS agent ids, to name the side the agent represented."""
    if not isinstance(row, dict):
        return None
    desc = row.get("description") or {}
    sides = [(_str(a.get("type")) or "").lower() for a in _list(_get(row, "source", "agents"))
             if isinstance(a, dict) and str(a.get("agent_id")) in set(map(str, agent_mls_ids))]
    return {
        "property_id": _str(row.get("property_id")),
        "listing_id": _str(row.get("listing_id")),
        "link": _https(_str(row.get("href"))),
        "status": _str(row.get("status")),
        "sold_date": _str(desc.get("sold_date")),
        "sold_price": _num(desc.get("sold_price")),
        "list_price": _num(row.get("list_price")),
        "beds": _num(desc.get("beds")),
        "baths": _num(desc.get("baths_consolidated")),
        "sqft": _num(desc.get("sqft")),
        "lot_sqft": _num(desc.get("lot_sqft")),
        "stories": _num(desc.get("stories")),
        "represented": sides[0] if sides else None,
        "address": _address(row.get("location")),
        "street_view_link": _https(_str(_get(row, "location", "street_view_url"))),
        "photo": _https(_get(row, "primary_photo", "href")),
        "photos": _links(row.get("photos")),
        "flags": {k: _bool(_get(row, "flags", k)) for k in ("is_new_construction", "is_foreclosure", "is_short_sale")},
        "mls_agents": [{"mls_id": _str(a.get("id")), "agent_id": _str(a.get("agent_id")),
                        "side": (_str(a.get("type")) or "").lower() or None}
                       for a in _list(_get(row, "source", "agents")) if isinstance(a, dict)],
    }


def parse_closings(payload, agent_mls_ids=()):
    payload = payload or {}
    rows = [c for c in (parse_closing(x, agent_mls_ids) for x in _list(payload.get("results"))) if c]
    return rows, _int(payload.get("total"))


# ---- markets ------------------------------------------------------------------------------

def parse_housing_market(stats):
    stats = stats or {}
    return {
        "median_listing_price": _num(stats.get("median_listing_price")),
        "median_rent": _num(stats.get("median_rent_price")),
        "median_sold_price": _num(stats.get("median_sold_price")),
        "median_days_on_market": _num(stats.get("median_days_on_market")),
        "median_price_per_sqft": _num(stats.get("median_price_per_sqft")),
        "hotness": {
            "local_score": _num(stats.get("local_hotness_score")),
            "national_score": _num(stats.get("national_hotness_score")),
            "local_temperature": _str(stats.get("local_temperature")),
            "national_temperature": _str(stats.get("national_temperature")),
            "badge": _str(stats.get("hot_market_badge")),
            "rank": _int(stats.get("hot_market_rank")),
        },
        "days_on_market_vs_county": _num(stats.get("ratio_of_days_on_market_vs_typical_property_in_county")),
        "views_vs_county": _num(stats.get("ratio_of_ldp_views_vs_typical_property_in_county")),
    }


def parse_geo(geo):
    geo = geo or {}
    return {
        "slug": _str(geo.get("slug_id")),
        "name": refs.slug_to_text(geo["slug_id"]) if geo.get("slug_id") else None,
        "state_code": _str(geo.get("state_code")),
        **_coordinate(geo.get("centroid")),
        "stats": parse_housing_market(_get(geo, "geo_statistics", "housing_market")),
    }


def parse_nearby(data):
    data = data or {}
    geo = data.get("geo") or {}
    nearby = data.get("customer_nearby_locations") or {}
    cities = [parse_geo(g) for g in _list(_get(geo, "recommended", "geos")) if isinstance(g, dict)]
    zips = [{"postal_code": _str(z.get("postal_code")), "city": _str(z.get("city")), "slug": _str(z.get("slug_id"))}
            for z in _list(nearby.get("nearby_zips")) if isinstance(z, dict)]
    more_cities = [{"city": _str(c.get("city")), "slug": _str(c.get("slug_id")), "postal_code": _str(c.get("postal_code"))}
                   for c in _list(nearby.get("nearby_cities")) if isinstance(c, dict)]
    return {"cities": cities, "other_cities": more_cities, "postal_codes": zips}


# ---- mortgage ---------------------------------------------------------------------------

_RATE_KEYS = (
    ("thirty_year_fix", "30_year_fixed"), ("thirty_year_fix_apr", "30_year_fixed_apr"),
    ("twenty_year_fix", "20_year_fixed"), ("fifteen_year_fix", "15_year_fixed"),
    ("fifteen_year_fix_apr", "15_year_fixed_apr"), ("ten_year_fix", "10_year_fixed"),
    ("five_one_arm", "5_1_arm"), ("five_one_arm_apr", "5_1_arm_apr"), ("seven_one_arm", "7_1_arm"),
    ("thirty_year_fix_fha", "30_year_fixed_fha"), ("thirty_year_fix_va", "30_year_fixed_va"),
    ("thirty_year_fix_jumbo", "30_year_fixed_jumbo"),
)


def parse_mortgage_trends(payload):
    rows = []
    for row in _list(_get(payload, "rate_trends")):
        if not isinstance(row, dict):
            continue
        year, month, day = _int(row.get("year")), _int(row.get("month")), _int(row.get("day"))
        date = f"{year:04d}-{month:02d}-{day:02d}" if year and month and day else None
        rows.append({"date": date, **{ours: _num(row.get(theirs)) for theirs, ours in _RATE_KEYS}})
    rows.sort(key=lambda r: r["date"] or "", reverse=True)
    return rows


# ---- schools ------------------------------------------------------------------------------

def parse_school_search(payload):
    payload = payload or {}
    rows = [s for s in (_school(x) for x in _list(payload.get("schools"))) if s]
    for row in rows:
        row.pop("distance_miles", None)
        row.pop("is_assigned", None)
    return rows, _int(payload.get("total"))
