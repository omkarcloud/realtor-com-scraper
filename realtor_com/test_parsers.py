"""Offline tests for the realtor.com parsers, reference resolvers and the
gateway envelope helper, against the captured fixtures
(realtor_com/fixtures/, 2026-11-07): happy paths, sparse records (a rental
community, a sold home in a disclosure state), empty pages and the
gateway's not-found envelopes. No network.

    python -m pytest realtor_com/test_parsers.py -q
"""
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from realtor_com import parsers as P, refs  # noqa: E402
from realtor_com import fetch as F  # noqa: E402

FX = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")


def fixture(name):
    with open(os.path.join(FX, name + ".json"), encoding="utf-8") as f:
        return json.load(f)


def _no_empty_strings(obj, path="root"):
    """Absent values are null, never "" / "N/A"; keys are snake_case."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            assert key == key.lower() and " " not in key and "-" not in key, f"{path}.{key}"
            assert not key.startswith("__"), f"{path}.{key}"
            _no_empty_strings(value, f"{path}.{key}")
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            _no_empty_strings(value, f"{path}[{i}]")
    elif isinstance(obj, str):
        assert obj.strip() not in ("", "N/A", "null"), path


# ---- refs -------------------------------------------------------------------------------

@pytest.mark.parametrize("value,expected", [
    ("8102930727", "8102930727"),
    ("M81029-30727", "8102930727"),
    ("m81029-30727", "8102930727"),
    ("Q717000097677", "717000097677"),
    ("1704-Shelbourne-Dr_Austin_TX_78752_M81029-30727", "8102930727"),
    ("https://www.realtor.com/realestateandhomes-detail/1704-Shelbourne-Dr_Austin_TX_78752_M81029-30727", "8102930727"),
    ("https://www.realtor.com/rentals/details/5500-Caprock-Summit-Dr_Austin_TX_78738_M94474-22407?x=1", "9447422407"),
    ("realtor.com/realestateandhomes-detail/Parten-7585_305-Bird-Hollow_Austin_TX_78737_Q717000097677", "717000097677"),
])
def test_resolve_property(value, expected):
    assert refs.resolve_property(value) == expected


@pytest.mark.parametrize("value", [
    "", "shelbourne", "12", "https://example.com/realestateandhomes-detail/x_M81029-30727",
    "https://www.realtor.com/realestateagents/Knolly-Williams_Austin_TX_184731_446999691",
    "https://www.realtor.com/realestateandhomes-search/Austin_TX",
])
def test_resolve_property_invalid(value):
    with pytest.raises(ValueError):
        refs.resolve_property(value)


@pytest.mark.parametrize("value,expected", [
    ("184731", "184731"),
    ("https://www.realtor.com/realestateagents/Knolly-Williams_Austin_TX_184731_446999691", "184731"),
    ("https://www.realtor.com/realestateagents/Knolly-Williams_Austin_TX_184731", "184731"),
    ("/realestateagents/Andra-Cortez-Jackson_Austin_TX_1918615_123", "1918615"),
    ("56a649a10fa417010073f11b", "56a649a10fa417010073f11b"),
    ("https://www.realtor.com/realestateagents/56a649a10fa417010073f11b", "56a649a10fa417010073f11b"),
])
def test_resolve_agent(value, expected):
    assert refs.resolve_agent(value) == expected


@pytest.mark.parametrize("value", [
    "", "knolly williams", "https://example.com/realestateagents/x_184731_1",
    "https://www.realtor.com/realestateagents/Austin_TX",
    "https://www.realtor.com/realestateandhomes-detail/x_M81029-30727",
])
def test_resolve_agent_invalid(value):
    with pytest.raises(ValueError):
        refs.resolve_agent(value)


@pytest.mark.parametrize("value,expected", [
    ("Austin, TX", "Austin, TX"),
    ("78704", "78704"),
    ("Austin_TX", "Austin, TX"),
    ("Zilker_Austin_TX", "Zilker, Austin, TX"),
    ("San-Antonio_TX", "San Antonio, TX"),
    ("https://www.realtor.com/realestateandhomes-search/Austin_TX", "Austin, TX"),
    ("https://www.realtor.com/realestateandhomes-search/Austin_TX/beds-3/pg-2", "Austin, TX"),
    ("https://www.realtor.com/realestateandhomes-search/78704", "78704"),
    ("https://www.realtor.com/apartments/Zilker_Austin_TX", "Zilker, Austin, TX"),
    ("https://www.realtor.com/realestateagents/Austin_TX", "Austin, TX"),
    ("https://www.realtor.com/local/market/texas/travis-county/austin", "Austin, Texas"),
    ("https://www.realtor.com/local/market/texas/travis-county/austin/78752", "78752"),
])
def test_resolve_location(value, expected):
    assert refs.resolve_location(value) == expected


@pytest.mark.parametrize("value", [
    "", "https://example.com/realestateandhomes-search/Austin_TX",
    "https://www.realtor.com/realestateandhomes-detail/1704-Shelbourne-Dr_Austin_TX_78752_M81029-30727",
    "https://www.realtor.com/realestateagents/Knolly-Williams_Austin_TX_184731_446999691",
    "https://www.realtor.com/mortgage/rates",
])
def test_resolve_location_invalid(value):
    with pytest.raises(ValueError):
        refs.resolve_location(value)


def test_location_slug_and_links():
    assert refs.location_slug("Austin, TX") == "Austin_TX"
    assert refs.location_slug("Zilker, Austin, TX") == "Zilker_Austin_TX"
    assert refs.location_slug("78704") == "78704"
    assert refs.property_link({"permalink": "a_M1-2", "status": "for_sale"}) == \
        "https://www.realtor.com/realestateandhomes-detail/a_M1-2"
    assert refs.property_link({"permalink": "a_M1-2", "status": "for_rent"}) == \
        "https://www.realtor.com/rentals/details/a_M1-2"
    assert refs.property_link({}) is None


# ---- envelope helper -------------------------------------------------------------------------

def test_root_not_found_envelope():
    with pytest.raises(F.RealtorNotFound):
        F.root(fixture("home_notfound"), "home", label="property 1234567890")


def test_root_null_without_error_is_none():
    assert F.root(fixture("market_notfound"), "geo") is None
    assert F.root(fixture("agent_branding_notfound"), "agent_branding") == {"branding": None}


def test_root_validation_error_is_bad_request():
    body = {"data": None, "errors": [{"message": 'Cannot query field "zzz" on type "Home".'}]}
    with pytest.raises(F.RealtorBadRequest):
        F.root(body, "home")


def test_root_other_error_is_upstream():
    with pytest.raises(F.RealtorUpstreamError):
        F.root({"data": {"home_search": None}, "errors": [{"message": "Check your request and try again"}]},
               "home_search")


def test_home_query_text_is_frozen():
    assert "nearby_schools(radius: 5.0, limit_per_level: 5)" in F.home_query()
    assert "nearby_schools(radius: 2.0, limit_per_level: 3)" in F.home_query(2, 3)
    assert "status: for_rent" in F.SIMILAR_QUERY % ("for_rent", F.RELATED_CARD)
    assert "mls_status" not in F.RELATED_CARD


# ---- search cards -------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def sale_cards():
    return P.parse_search(fixture("search_for_sale_austin"))


def test_search_for_sale(sale_cards):
    cards, total = sale_cards
    assert total == 6490 and len(cards) == 50
    card = cards[0]
    _no_empty_strings(card)
    assert card["property_id"] == "8395932351" and card["listing_id"] == "3001457163"
    assert card["link"] == ("https://www.realtor.com/realestateandhomes-detail/"
                            "6700-Tulloch-Way_Austin_TX_78754_M83959-32351")
    assert card["status"] == "for_sale" and card["mls_status"] == "Pending"
    assert card["price"] == 439999 and card["price_per_sqft"] == 115
    assert card["beds"] == 4 and card["baths"] == 4 and card["baths_half"] == 1 and card["sqft"] == 3840
    assert card["year_built"] == 2005 and card["lot_sqft"] == 8350 and card["hoa_fee"] == 41
    assert card["address"]["city"] == "Austin" and card["address"]["postal_code"] == "78754"
    assert card["address"]["county"] == "Travis" and card["address"]["county_fips"] == "48453"
    assert card["address"]["latitude"] == pytest.approx(30.354294)
    assert card["photo"].startswith("https://ap.rdcpix.com/") and len(card["photos"]) == 11
    assert card["flags"]["is_pending"] is True and card["flags"]["is_foreclosure"] is False
    assert "central_air" in card["tags"]
    assert card["mls"]["id"] and card["last_sold_date"] == "2005-08-30"
    assert card["list_date"] and card["last_update_date"]
    # every card has the identity triple and numeric prices
    for c in cards:
        assert c["property_id"] and c["link"]
        assert c["price"] is None or isinstance(c["price"], (int, float))


def test_search_cards_carry_agent_contacts(sale_cards):
    cards, _ = sale_cards
    with_agent = [c for c in cards if c["advertisers"]]
    assert with_agent
    adv = with_agent[0]["advertisers"][0]
    assert adv["type"] in ("seller", "builder", "community", "management", "agent", "office", None)
    assert set(adv) >= {"id", "name", "phones", "office", "broker", "email"}
    for phone in adv["phones"]:
        assert phone["number"] and isinstance(phone["is_primary"], bool)


def test_search_cards_carry_estimates(sale_cards):
    cards, _ = sale_cards
    with_estimate = [c for c in cards if c["estimates"]]
    assert with_estimate
    est = with_estimate[0]["estimates"][0]
    assert isinstance(est["estimate"], (int, float)) and est["source"] and isinstance(est["is_best"], bool)


def test_search_for_rent():
    cards, total = P.parse_search(fixture("search_for_rent_austin"))
    assert total > 1000 and len(cards) == 20
    card = cards[0]
    _no_empty_strings(card)
    assert card["status"] == "for_rent" and card["name"] == "Creeks Edge Apartments"
    assert card["link"].startswith("https://www.realtor.com/rentals/details/")
    assert card["price"] is None and card["price_min"] == 675 and card["price_max"] == 1050
    assert card["property_type"] == "apartment"
    assert any(c["units"] for c in cards)
    unit = next(u for c in cards for u in c["units"])
    assert set(unit) == {"price", "beds", "baths", "sqft", "available_date", "photos"}
    assert any(c["pet_policy"] for c in cards)


def test_search_sold_with_prices():
    cards, total = P.parse_search(fixture("search_sold_seattle"))
    assert total > 100 and len(cards) == 20
    card = cards[0]
    assert card["status"] == "sold" and card["mls_status"] == "Sold"
    assert card["last_sold_price"] == 639000 and card["last_sold_date"] == "2026-11-06"
    assert card["price"] == 649000


def test_search_filtered_and_sorted():
    cards, total = P.parse_search(fixture("search_filtered"))
    assert total == 20 and len(cards) == 5
    assert all(c["beds"] >= 3 and 300000 <= c["price"] <= 600000 for c in cards)
    assert all(c["property_type"] in ("single_family", "condos", "condo") for c in cards)
    dates = [c["list_date"] for c in cards]
    assert dates == sorted(dates, reverse=True)


def test_search_empty_page():
    cards, total = P.parse_search(fixture("search_empty"))
    assert cards == [] and total == 0
    assert P.parse_search({}) == ([], None)
    assert P.parse_search(None) == ([], None)
    assert P.parse_card(None) is None


def test_search_nearby_and_polygon():
    cards, total = P.parse_search(fixture("search_nearby"))
    assert total == 803 and len(cards) == 5 and cards[0]["address"]["line"] == "200 Congress Ave Unit 14C"
    cards, total = P.parse_search(fixture("search_polygon"))
    assert total > 0 and len(cards) == 5
    for c in cards:
        assert -97.80 <= c["address"]["longitude"] <= -97.70 and 30.20 <= c["address"]["latitude"] <= 30.30


def test_search_batch_and_mls():
    cards, _ = P.parse_search(fixture("search_batch"))
    assert {c["property_id"] for c in cards} == {"9447422407", "8102930727", "7420506606"}
    cards, _ = P.parse_search(fixture("search_mls"))
    assert [(c["property_id"], c["mls"]["id"]) for c in cards] == [("3868678113", "LINY"), ("8102930727", "AUTX")]
    assert all(c["mls"]["listing_id"] == "3401964" for c in cards)
    cards, _ = P.parse_search(fixture("search_mls_source"))
    assert [c["property_id"] for c in cards] == ["8102930727"]


def test_partial_card_never_crashes():
    card = P.parse_card({"property_id": "1", "description": None, "location": {"address": None},
                         "photos": "nope", "advertisers": [None, {"name": "x"}], "flags": None})
    assert card["property_id"] == "1" and card["beds"] is None and card["photos"] == []
    assert card["address"]["city"] is None and card["flags"]["is_pending"] is False
    assert card["advertisers"] == [{"id": None, "name": "x", "type": None, "email": None, "phones": [], "website": None,
                                    "slogan": None, "photo": None, "license": None, "nrds_id": None, "mls_set": None,
                                    "office": None, "broker": None, "builder": None}]


# ---- the home record ------------------------------------------------------------------------------

@pytest.fixture(scope="module")
def home():
    return P.parse_home(fixture("home_for_sale"))


def test_home_identity_and_prices(home):
    _no_empty_strings(home)
    assert home["property_id"] == "8102930727" and home["listing_id"] == "2991781467"
    assert home["link"] == ("https://www.realtor.com/realestateandhomes-detail/"
                            "1704-Shelbourne-Dr_Austin_TX_78752_M81029-30727")
    assert home["status"] == "for_sale" and home["mls_status"] == "Active"
    assert home["price"] == 400000 and home["price_per_sqft"] == 257
    assert home["last_price_change"] == 5000 and home["last_price_change_date"].startswith("2026-10-15")
    # Texas is a non-disclosure state: the sale date is known, the price is not
    assert home["last_sold_price"] is None and home["last_sold_date"] == "2022-10-21"
    assert home["beds"] == 3 and home["baths"] == 2 and home["sqft"] == 1556 and home["year_built"] == 1969
    assert home["style"] == "Single level Floor Plan" and home["annual_tax"] == 12242
    assert home["description"].startswith("LENDER-APPROVED SHORT SALE")
    assert home["list_date"] == "2026-02-21T14:21:38Z"


def test_home_address_and_neighborhoods(home):
    address = home["address"]
    assert address["line"] == "1704 Shelbourne Dr" and address["state"] == "Texas"
    assert address["county"] == "Travis" and address["county_fips"] == "48453"
    assert address["street_view_link"].startswith("https://maps.googleapis.com/")
    assert address["neighborhoods"] == ["Creekside", "Coronado Hills", "East Austin"]
    assert [n["slug"] for n in home["neighborhoods"]] == ["Creekside_Austin_TX", "Coronado-Hills_Austin_TX",
                                                          "East-Austin_Austin_TX"]
    assert home["neighborhoods"][0]["level"] == "residential_neighborhood"
    assert "boundary" not in home["neighborhoods"][0]


def test_home_details_photos_contacts(home):
    assert home["details"][0] == {"category": "Bedrooms", "parent_category": "Interior",
                                  "items": ["Bedrooms: 3", "Bedrooms On Main Level: 3", "Primary Bedroom Level: Main"]}
    assert len(home["photos"]) == 38 and home["photos"][0]["link"].startswith("https://")
    assert home["photos"][0]["tags"][0]["label"] == "exterior"
    assert home["photo_count"] == 38
    agent = home["advertisers"][0]
    assert agent["name"] == "Knolly Williams" and agent["email"] == "knolly@knolly.com"
    assert agent["id"] == "184731" and agent["nrds_id"] == "803000355" and agent["license"] == "0510003"
    assert agent["phones"] == [{"number": "7372051640", "type": "mobile", "is_primary": True, "extension": None}]
    assert agent["office"]["name"] == "eXp Realty, LLC" and agent["office"]["address"]["postal_code"] == "78759"
    assert agent["broker"] == {"id": None, "name": "eXp Realty, LLC"}
    assert home["listing_contacts"][0]["link"] == \
        "https://www.realtor.com/realestateagents/Knolly-Williams_Austin_TX_184731_446999691"
    assert home["mls"] == {"id": "AUTX", "name": "UnlockMLS", "type": "mls", "listing_id": "3401964",
                           "agents": [{"name": None, "id": "510003", "office_name": "eXp Realty, LLC",
                                       "office_id": "702963"}],
                           "disclaimer": "© 2026, Unlock MLS, All Rights Reserved."}
    assert home["mortgage"]["monthly_payment"] == 3368 and home["mortgage"]["loan_amount"] == 320000
    assert home["mortgage"]["monthly_breakdown"][0]["type"] == "principal_and_interest"
    assert home["mortgage"]["property_tax_rate"] == pytest.approx(0.030605)
    assert home["rental"] is None and home["open_houses"] == []
    assert home["flags"]["is_new_listing"] is False and home["flags"]["is_pending"] is False


def test_home_history_and_tax(home):
    first = home["price_history"][0]
    assert first["date"] == "2026-10-15" and first["event"] == "Price Changed" and first["price"] == 400000
    assert first["price_change"] == 5000 and first["price_per_sqft"] == pytest.approx(257.07, abs=0.01)
    assert first["listing"]["listing_id"] == "2991781467" and first["listing"]["photos"]
    assert len(home["price_history"]) == 11
    tax = home["tax_history"][0]
    assert tax["year"] == 2026 and tax["tax"] == 10568
    assert tax["assessment"] == {"building": 413615, "land": 102817, "total": 516432}
    assert tax["market_value"]["total"] == 516432
    assert len(home["tax_history"]) == 17
    assert home["tax_record"] == {"apn": None, "parcel_id": "c6fd7bbf-faf6-4822-b634-bf4182e43ae4"}


def test_home_estimates(home):
    est = home["estimates"]
    assert est["estimate"] == 391000 and est["estimate_high"] == 430100 and est["estimate_low"] == 351900
    assert est["estimate_source"] == "Collateral Analytics" and est["estimate_date"] == "2026-10-14"
    assert [e["source_type"] for e in est["current"]] == ["collateral", "quantarium", "corelogic"]
    assert est["current"][0]["is_best"] is True
    assert est["forecast"][0]["values"][0]["date"] == "2026-11-01" and len(est["forecast"][0]["values"]) == 12
    assert len(est["history"]) == 3 and est["history"][0]["values"][0]["estimate"] == 391000


def test_home_schools_environment_popularity(home):
    schools = home["schools"]
    assert len(schools["assigned"]) == 4 and len(schools["nearby"]) > 4
    assigned = schools["assigned"][0]
    assert assigned["name"] == "Northeast Early College High School" and assigned["rating"] == 3
    assert assigned["is_assigned"] is True and assigned["distance_miles"] == 0.5
    assert assigned["district"]["name"] == "Austin Independent School District"
    assert assigned["grades"] == ["9", "10", "11", "12"] and assigned["levels"] == ["high"]
    env = home["environment"]
    assert env["flood"]["score"] == 1 and env["flood"]["severity"] == "minimal" and env["flood"]["fema_zones"] == ["X (unshaded)"]
    assert env["heat"] == {"score": 8, "severity": "Severe"} and env["wind"]["score"] == 8 and env["air"]["score"] == 2
    assert env["wildfire"]["severity"] == "Minimal"
    assert [c["type"] for c in env["noise"]["categories"]] == ["airport", "traffic", "local", "score"]
    pop = home["popularity"]
    assert [p["days"] for p in pop] == [1, 7, 14, 21, 28, 30]
    assert pop[0] == {"days": 1, "views": 8753, "saves": 4, "clicks": 95, "shares": 3, "leads": 0}


def test_home_rental_community():
    home = P.parse_home(fixture("home_rental"))
    _no_empty_strings(home)
    assert home["status"] == "for_rent" and home["name"] == "The Artesian at Bee Cave"
    assert home["link"].startswith("https://www.realtor.com/rentals/details/")
    assert home["price"] is None and home["price_min"] == 1378 and home["price_max"] == 4025
    assert home["beds_min"] == 1 and home["beds_max"] == 3
    rental = home["rental"]
    assert len(rental["units"]) > 5
    unit = rental["units"][0]
    assert unit["price"] == 2410 and unit["beds"] == 1 and unit["sqft"] == 885 and unit["available_date"] == "2026-09-27"
    assert unit["photos"][0].startswith("https://")
    assert rental["pet_policy"] is not None and set(rental["pet_policy"]) == {"cats", "dogs", "small_dogs", "large_dogs"}
    assert isinstance(rental["monthly_fees"], list) and isinstance(rental["terms"], list)
    assert home["price_history"] is not None and home["estimates"]["estimate"] is None
    assert home["mls"] is None or home["mls"]["type"] is not None


def test_home_sold_disclosure_state():
    home = P.parse_home(fixture("home_sold"))
    assert home["status"] == "sold" and home["address"]["state_code"] == "WA"
    assert home["last_sold_price"] == 639000 and home["last_sold_date"] == "2026-11-06"
    assert home["address"]["neighborhoods"] == ["Magnolia", "Lawton Park"]


def test_home_partial_never_crashes():
    home = P.parse_home({"property_id": "1", "description": None, "location": None, "estimates": None,
                         "schools": None, "local": None, "popularity": None, "advertisers": None})
    assert home["property_id"] == "1" and home["link"] is None and home["estimates"]["current"] == []
    assert home["schools"] == {"assigned": [], "nearby": []} and home["environment"] is None
    assert home["popularity"] == [] and home["rental"] is None
    assert P.parse_home(None)["property_id"] is None


def test_neighborhood_boundaries():
    rows = P.parse_neighborhoods(fixture("neighborhoods"))
    assert [n["name"] for n in rows] == ["Creekside", "Coronado Hills", "East Austin"]
    assert rows[0]["boundary"]["type"] in ("Polygon", "MultiPolygon")
    assert rows[0]["latitude"] == pytest.approx(30.326536)
    assert P.parse_neighborhoods({}) == []


def test_nearby_schools_radius_query():
    nearby = P.parse_schools(fixture("nearby_schools"))["nearby"]
    assert nearby and all(s["distance_miles"] <= 2 for s in nearby)


def test_similar_homes():
    cards, _ = P.parse_search(fixture("similar_for_sale").get("related_homes"))
    assert len(cards) == 20
    card = cards[0]
    _no_empty_strings(card)
    assert card["property_id"] == "7334805120" and card["price"] == 390000 and card["beds"] == 3
    assert card["link"].endswith("_M73348-05120") and card["photo"].startswith("https://")
    assert card["estimates"][0]["estimate"] == 385659 and card["estimates"][0]["is_best"] is True
    assert card["mls_status"] is None and card["tags"] == []
    cards, _ = P.parse_search(fixture("similar_for_rent").get("related_homes"))
    assert len(cards) == 3 and cards[0]["price_min"] == 1550


# ---- communities ------------------------------------------------------------------------------------

def test_communities():
    rows, total = P.parse_communities(fixture("communities_austin"))
    assert total == 46 and len(rows) == 20
    row = rows[0]
    _no_empty_strings(row)
    assert row["id"] == "717000097677" and row["name"] == "Parten 75'/85'"
    assert row["link"].endswith("_Q717000097677") and row["status"] == "active"
    assert row["price_min"] == 1044900 and row["price_max"] == 1254900
    assert row["beds_min"] == 4 and row["beds_max"] == 5 and row["baths_max"] == 6
    assert row["address"]["postal_code"] == "78737" and row["photo_count"] == 13 and len(row["photos"]) == 13
    assert row["is_new_construction"] is True
    assert P.parse_communities({}) == ([], None)


# ---- locations --------------------------------------------------------------------------------------

def test_suggestions():
    rows = P.parse_suggestions(fixture("suggestions_78704"))
    assert rows[0] == {"type": "postal_code", "text": "78704, Austin, TX", "slug": "78704",
                       "geo_id": "804e35f5-d3b3-50b8-9ffa-18c6424c02a7", "city": "Austin", "city_slug": None,
                       "state_code": "TX", "postal_code": "78704", "county": None, "neighborhood": None,
                       "street": None, "address": None, "school": None, "school_district": None,
                       "property_id": None, "latitude": 30.24314, "longitude": -97.765757}
    rows = P.parse_suggestions(fixture("suggestions_austin"))
    assert rows[0]["type"] == "city" and rows[0]["slug"] == "Austin_TX" and rows[1]["slug"] == "Austin_MN"
    rows = P.parse_suggestions(fixture("suggestions_neighborhood"))
    assert rows[0]["type"] == "neighborhood" and rows[0]["slug"] == "Zilker_Austin_TX" and rows[0]["neighborhood"] == "Zilker"
    assert rows[1]["type"] == "school" and rows[1]["school"] == "Zilker Elementary School"
    rows = P.parse_suggestions(fixture("suggestions_address"))
    assert rows[0]["type"] == "address" and rows[0]["property_id"] == "8102930727"
    assert rows[0]["address"] == "1704 Shelbourne Dr" and rows[0]["postal_code"] == "78752"
    assert P.parse_suggestions(fixture("suggestions_nomatch")) == []
    assert P.parse_suggestions(None) == []


# ---- agents -----------------------------------------------------------------------------------------

def test_agents_search():
    rows, total = P.parse_agents(fixture("agents_austin"))
    assert total == 34867 and len(rows) == 20
    row = rows[0]
    _no_empty_strings(row)
    assert row["id"] == "1918615" and row["profile_id"] == "56a649a10fa417010073f11b"
    assert row["name"] == "Andra Cortez Jackson Realtor Austin TX"
    assert row["photo"].startswith("https://ap.rdcpix.com/")
    assert row["broker"] == {"id": "3337315", "name": "Team West Real Estate - Broker"}
    assert row["office"] == "Team West Real Estate"
    assert row["is_realtor"] is True and row["is_paid"] is True and row["is_realchoice_select"] is False
    assert row["rating"] == {"average": 5, "reviews_count": 11, "recommendations_count": 62, "total_count": 73}
    assert row["listings"]["for_sale"]["count"] == 3 and row["listings"]["sold_last_year_count"] == 11
    assert row["listings"]["price_range_min"] == 325000 and len(row["listings"]["recent_sales"]) == 3
    assert row["experience_since"] == 2011 and row["services"]["buyer"]
    assert "sorting_weight" not in row


def test_agents_search_variants():
    rows, total = P.parse_agents(fixture("agents_zip"))
    assert total > 0 and len(rows) == 5
    rows, total = P.parse_agents(fixture("agents_name"))
    assert any("Knolly" in r["name"] for r in rows)
    rows, total = P.parse_agents(fixture("agents_buyer_spanish"))
    assert len(rows) == 5 and total > 0
    assert P.parse_agents(fixture("agents_empty")) == ([], 0)
    assert P.parse_agents(None) == ([], None)


def test_agent_profile():
    agent = P.parse_agent(fixture("agent_branding_1918615"))
    _no_empty_strings(agent)
    assert agent["id"] == "1918615" and agent["profile_id"] == "56a649a10fa417010073f11b"
    assert agent["bio"].startswith("🏡 Andra Cortez Jackson Jr.")
    assert agent["website"] == "https://www.teamwestre.com"
    assert agent["phones"][0] == {"number": "(512) 565-8448", "type": "mobile", "is_primary": False, "extension": None}
    assert agent["license"] == {"number": "0642309", "state_code": "TX"}
    assert agent["languages"] == ["English"] and "contracts" in agent["specializations"]
    assert agent["represents"] == ["buyer", "seller"]
    assert {"name": "Austin", "state_code": "TX"} in agent["served_areas"] and len(agent["served_areas"]) == 18
    assert agent["rating"]["reviews_count"] == 11 and agent["rating"]["recommendations_count"] == 62
    assert agent["listings"]["sold"] == {"count": 17, "last_sold_date": "2026-09-11", "price_min": None, "price_max": None}
    assert agent["experience"] == {"since_year": 2011, "since_month": "January",
                                   "label": "15 years 10 months of experience"}
    assert agent["mls"] == [{"id": "AUTX", "agent_id": "642309", "mls_set": "A-AUTX-642309", "license_number": "0642309",
                             "status": "A", "is_primary": True, "inactivation_date": None},
                            agent["mls"][1]]
    assert agent["broker"]["id"] == "3337315"
    assert agent["office"]["name"] == "Team West Real Estate" and agent["office"]["address"]["line"] == "13812 Research Blvd."
    assert agent["office"]["phones"] == [{"number": "(512) 296-0669", "type": "office", "is_primary": False, "extension": None}]
    assert agent["social_media"]["facebook"] == "https://www.facebook.com/AndraJacksonHomes"
    assert agent["social_media"]["tiktok"] is None and agent["social_media"]["x"] == "https://twitter.com/andra_cortez"
    assert agent["video"] == {"source": "YOUTUBE", "id": "EhSPmmvO4aI", "link": "https://youtu.be/EhSPmmvO4aI"}
    assert len(agent["questions_and_answers"]) == 4 and agent["questions_and_answers"][0]["question"]
    assert agent["services"]["seller"] == ["Professional photography", agent["services"]["seller"][1],
                                           agent["services"]["seller"][2], agent["services"]["seller"][3]]
    assert agent["is_empty_profile"] is False


def test_agent_profile_by_profile_id_is_the_same_agent():
    assert P.parse_agent(fixture("agent_branding_by_profile"))["id"] == "1918615"


def test_agent_profile_sparse():
    agent = P.parse_agent(fixture("agent_branding_184731"))
    assert agent["id"] == "184731" and agent["name"] == "Knolly Williams"
    assert agent["mls"] == [{"id": "AUTX", "agent_id": "510003", "mls_set": "A-AUTX-510003", "license_number": "0510003",
                             "status": "A", "is_primary": True, "inactivation_date": None}]
    assert agent["office"]["address"]["line2"] == "AUSTIN, TX 78759" and agent["office"]["website"] is None
    assert agent["video"] is None or agent["video"]["link"]
    assert P.parse_agent({})["id"] is None and P.parse_agent(None)["office"] is None


def test_agent_reviews_and_recommendations():
    reviews = P.parse_reviews(fixture("agent_reviews_1918615"))
    assert len(reviews) == 11
    review = reviews[0]
    _no_empty_strings(review)
    assert review["rating"] == 5 and review["sub_ratings"] == {"responsiveness": 5, "market_expertise": 5,
                                                              "negotiation_skills": 5, "professionalism_communication": 5}
    assert review["reviewer"] == {"name": "Nick", "role": "BUYER", "location": "Hutto, TX"}
    assert review["year"] == 2026 and review["date"].startswith("2026-09-11") and review["reply"] is None
    assert any(r["reply"] for r in reviews)
    recs = P.parse_recommendations(fixture("agent_recommendations_1918615"))
    assert len(recs) == 62 and recs[0]["name"] == "David K" and recs[0]["comment"].startswith("Andra made")
    assert P.parse_reviews(fixture("agent_reviews_empty")) == []
    assert P.parse_recommendations(fixture("agent_recommendations_empty")) == []
    assert P.parse_reviews(None) == [] and P.parse_recommendations({"recommendations": None}) == []


def test_agent_closings():
    rows, total = P.parse_closings(fixture("closings_184731"), ["510003"])
    assert total == 51 and len(rows) == 20
    row = rows[0]
    _no_empty_strings(row)
    assert row["property_id"] == "7672804345" and row["status"] == "sold"
    assert row["sold_date"] == "2026-10-22" and row["sold_price"] is None   # Texas: non-disclosure
    assert row["beds"] == 4 and row["baths"] == 4.5 and row["sqft"] == 4840 and row["lot_sqft"] == 35066
    assert row["represented"] == "seller"
    assert row["address"]["city"] == "Taylor" and row["address"]["postal_code"] == "76574"
    assert row["mls_agents"] == [{"mls_id": "AUTX", "agent_id": "510003", "side": "seller"},
                                 {"mls_id": "AUTX", "agent_id": "762025", "side": "buyer"}]
    assert row["link"].endswith("_M76728-04345")
    assert P.parse_closings(fixture("closings_empty")) == ([], 0)


def test_agent_listings_are_search_cards():
    cards, total = P.parse_search(fixture("agent_listings_184731"))
    assert total >= len(cards) > 0
    assert all(any(a["id"] == "184731" for a in c["advertisers"]) for c in cards)


# ---- markets / mortgage / schools -----------------------------------------------------------------------

def test_market_stats():
    city = P.parse_geo(fixture("market_austin"))
    assert city["slug"] == "Austin_TX" and city["name"] == "Austin, TX" and city["state_code"] == "TX"
    assert city["latitude"] == pytest.approx(30.2986219)
    assert city["stats"]["median_listing_price"] == 500000 and city["stats"]["median_rent"] == 1949
    assert city["stats"]["median_days_on_market"] == 81 and city["stats"]["median_price_per_sqft"] == 310
    assert city["stats"]["median_sold_price"] is None and city["stats"]["hotness"]["rank"] is None
    zipcode = P.parse_geo(fixture("market_78752"))
    assert zipcode["name"] == "78752" and zipcode["stats"]["hotness"] == {
        "local_score": pytest.approx(39.534883721), "national_score": pytest.approx(22.541789577),
        "local_temperature": "warm", "national_temperature": "cool", "badge": "Other", "rank": 12345}
    assert zipcode["stats"]["days_on_market_vs_county"] == 4
    nbhd = P.parse_geo(fixture("market_neighborhood"))
    assert nbhd["name"] == "Zilker, Austin, TX" and nbhd["stats"]["median_listing_price"] == 799000
    assert P.parse_geo(None)["slug"] is None


def test_market_nearby():
    nearby = P.parse_nearby(fixture("nearby_austin"))
    assert [c["slug"] for c in nearby["cities"][:3]] == ["Round-Rock_TX", "Georgetown_TX", "Leander_TX"]
    assert nearby["cities"][0]["name"] == "Round Rock, TX" and nearby["cities"][0]["stats"]["median_listing_price"] == 407000
    assert isinstance(nearby["postal_codes"], list) and isinstance(nearby["other_cities"], list)
    for row in nearby["postal_codes"]:
        assert set(row) == {"postal_code", "city", "slug"}
    assert P.parse_nearby(None) == {"cities": [], "other_cities": [], "postal_codes": []}


def test_mortgage_trends():
    rows = P.parse_mortgage_trends(fixture("mortgage_tx_purchase"))
    assert len(rows) == 520 and rows[0]["date"] == "2026-11-06" and rows[-1]["date"] == "2025-06-01"
    assert rows[0]["30_year_fixed"] == 7.01 and rows[0]["30_year_fixed_apr"] == 7.052
    assert rows[0]["15_year_fixed"] == 6.216 and rows[0]["5_1_arm"] == 6.648 and rows[0]["30_year_fixed_jumbo"] == 7.217
    assert set(rows[0]) == {"date", "30_year_fixed", "30_year_fixed_apr", "20_year_fixed", "15_year_fixed",
                            "15_year_fixed_apr", "10_year_fixed", "5_1_arm", "5_1_arm_apr", "7_1_arm",
                            "30_year_fixed_fha", "30_year_fixed_va", "30_year_fixed_jumbo"}
    refi = P.parse_mortgage_trends(fixture("mortgage_ca_refinance"))
    assert len(refi) > 300 and refi[0]["30_year_fixed"] != rows[0]["30_year_fixed"]
    assert P.parse_mortgage_trends(None) == []


def test_school_search():
    rows, total = P.parse_school_search(fixture("schools_78704"))
    assert total == 27 and len(rows) == 20
    row = rows[0]
    _no_empty_strings(row)
    assert row == {"id": "0768941411", "name": "Athena Montessori Academy", "rating": None, "parent_rating": None,
                   "funding_type": "private", "levels": ["elementary"], "grades": ["K"], "student_count": 140,
                   "city": "Austin", "latitude": 30.229225, "longitude": -97.781021,
                   "district": {"id": "06211428551", "name": None}}
    rows, total = P.parse_school_search(fixture("schools_austin"))
    assert total == 374 and rows[0]["name"] == "Govalle Elementary School"
    assert P.parse_school_search(fixture("schools_empty")) == ([], None)
