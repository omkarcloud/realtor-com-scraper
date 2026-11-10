"""Offline tests for the /realtor-com/* request schemas: accepted forms,
rejected forms and the error message / field each rejection names.

    python -m pytest realtor_com/test_schemas.py -q
"""
import os
import sys

import pytest
from marshmallow import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from realtor_com import schemas as S  # noqa: E402


def rejects(schema, data, field=None, contains=None):
    with pytest.raises(ValidationError) as exc:
        schema().load(data)
    messages = exc.value.normalized_messages()
    if field:
        assert field in messages, messages
    if contains:
        assert contains in str(messages), messages
    return messages


# ---- listings --------------------------------------------------------------------------

def test_search_defaults():
    loaded = S.SearchSchema().load({"location": " Austin, TX "})
    assert loaded["location"] == "Austin, TX" and loaded["status"] == "for_sale"
    assert loaded["sort"] == "relevant" and loaded["limit"] == 50 and loaded["page"] == 1
    assert loaded["property_types"] is None and loaded["include_pending"] is None


def test_search_accepts_every_location_form():
    for value, expected in (("78704", "78704"), ("Austin_TX", "Austin, TX"),
                            ("https://www.realtor.com/realestateandhomes-search/Zilker_Austin_TX", "Zilker, Austin, TX"),
                            ("https://www.realtor.com/apartments/78704", "78704")):
        assert S.SearchSchema().load({"location": value})["location"] == expected


def test_search_filters():
    loaded = S.SearchSchema().load({
        "location": "Austin, TX", "status": "SOLD", "property_types": "single_family, Condos", "min_price": "300000",
        "max_price": "600000", "min_beds": "0", "max_beds": "4", "min_baths": "1.5", "min_sqft": "1500",
        "max_hoa": "0", "listed_within_days": "30", "sold_within_days": "90", "include_pending": "yes",
        "foreclosure": "false", "keywords": "pool, garage", "cats": "1", "sort": "Price_Low", "limit": "200", "page": "50",
    })
    assert loaded["status"] == "sold" and loaded["property_types"] == ["single_family", "condos"]
    assert loaded["min_price"] == 300000 and loaded["min_beds"] == 0 and loaded["min_baths"] == 1.5
    assert loaded["max_hoa"] == 0 and loaded["include_pending"] is True and loaded["foreclosure"] is False
    assert loaded["keywords"] == ["pool", "garage"] and loaded["cats"] is True and loaded["dogs"] is None
    assert loaded["sort"] == "price_low" and loaded["limit"] == 200 and loaded["page"] == 50


@pytest.mark.parametrize("data,field,contains", [
    ({}, "location", "required"),
    ({"location": ""}, "location", "empty"),
    ({"location": "https://example.com/realestateandhomes-search/Austin_TX"}, "location", "realtor.com"),
    ({"location": "Austin, TX", "status": "pending"}, "status", "Must be one of"),
    ({"location": "Austin, TX", "property_types": "castle"}, "property_types", "not one of"),
    ({"location": "Austin, TX", "min_price": "600000", "max_price": "300000"}, "max_price", "must not exceed"),
    ({"location": "Austin, TX", "min_beds": "5", "max_beds": "2"}, "max_beds", "must not exceed"),
    ({"location": "Austin, TX", "limit": "201"}, "limit", None),
    ({"location": "Austin, TX", "limit": "200", "page": "51"}, "page", "10,000"),
    ({"location": "Austin, TX", "sort": "cheapest"}, "sort", "Must be one of"),
    ({"location": "Austin, TX", "include_pending": "maybe"}, "include_pending", "true or false"),
    ({"location": "Austin, TX", "url": "x"}, "url", "Unknown"),
    ({"location": "Austin, TX", "id": "x"}, "id", "Unknown"),
])
def test_search_rejects(data, field, contains):
    rejects(S.SearchSchema, data, field, contains)


def test_search_page_cap_follows_limit():
    assert S.SearchSchema().load({"location": "Austin, TX", "limit": "50", "page": "200"})["page"] == 200
    rejects(S.SearchSchema, {"location": "Austin, TX", "limit": "50", "page": "201"}, "page")


def test_search_nearby():
    loaded = S.SearchNearbySchema().load({"latitude": "30.2672", "longitude": "-97.7431"})
    assert loaded["latitude"] == 30.2672 and loaded["longitude"] == -97.7431 and loaded["radius"] == 2
    assert loaded["status"] == "for_sale"
    loaded = S.SearchNearbySchema().load({"latitude": "30.2672", "longitude": "-97.7431", "radius": "0.5", "status": "for_rent"})
    assert loaded["radius"] == 0.5 and loaded["status"] == "for_rent"
    rejects(S.SearchNearbySchema, {"longitude": "-97.7431"}, "latitude", "required")
    rejects(S.SearchNearbySchema, {"latitude": "95", "longitude": "-97.7431"}, "latitude")
    rejects(S.SearchNearbySchema, {"latitude": "30", "longitude": "-97", "radius": "51"}, "radius")
    rejects(S.SearchNearbySchema, {"latitude": "30", "longitude": "-97", "location": "Austin"}, "location", "Unknown")


def test_search_polygon():
    loaded = S.SearchPolygonSchema().load({"polygon": "-97.80 30.30, -97.70 30.30, -97.70 30.20, -97.80 30.20"})
    assert loaded["polygon"] == [[-97.8, 30.3], [-97.7, 30.3], [-97.7, 30.2], [-97.8, 30.2], [-97.8, 30.3]]
    assert loaded["status"] == "for_sale"
    rejects(S.SearchPolygonSchema, {}, "polygon", "required")
    rejects(S.SearchPolygonSchema, {"polygon": "-97.8 30.3, -97.7 30.3"}, "polygon", "at least 3")
    rejects(S.SearchPolygonSchema, {"polygon": "-97.8,30.3,-97.7"}, "polygon", "lng lat")
    rejects(S.SearchPolygonSchema, {"polygon": "a b, c d, e f"}, "polygon", "numbers")
    rejects(S.SearchPolygonSchema, {"polygon": "-200 30, -97 30, -97 31"}, "polygon", "-180..180")
    too_many = ", ".join(f"-97.{i:02d} 30.{i:02d}" for i in range(61))
    rejects(S.SearchPolygonSchema, {"polygon": too_many}, "polygon", "At most 60")


# ---- properties ---------------------------------------------------------------------------

def test_property_schema_accepts_id_tail_and_link():
    for value in ("8102930727", "M81029-30727", "1704-Shelbourne-Dr_Austin_TX_78752_M81029-30727",
                  "https://www.realtor.com/realestateandhomes-detail/1704-Shelbourne-Dr_Austin_TX_78752_M81029-30727",
                  "https://www.realtor.com/rentals/details/1704-Shelbourne-Dr_Austin_TX_78752_M81029-30727"):
        assert S.PropertySchema().load({"property": value}) == {"property": "8102930727"}


@pytest.mark.parametrize("value,contains", [
    ("", "empty"), ("shelbourne", "property id"), ("https://example.com/x_M81029-30727", "realtor.com"),
    ("https://www.realtor.com/realestateagents/Knolly-Williams_Austin_TX_184731_446999691", "property link"),
])
def test_property_schema_rejects(value, contains):
    rejects(S.PropertySchema, {"property": value}, "property", contains)


def test_property_schema_rejects_sibling_params():
    rejects(S.PropertySchema, {"property": "8102930727", "url": "x"}, "url", "Unknown")
    rejects(S.PropertySchema, {"property_id": "8102930727"}, "property", "required")


def test_property_schools_and_similar():
    assert S.PropertySchoolsSchema().load({"property": "8102930727"})["radius"] == 5
    assert S.PropertySchoolsSchema().load({"property": "8102930727", "radius": "2"})["radius"] == 2
    rejects(S.PropertySchoolsSchema, {"property": "8102930727", "radius": "30"}, "radius")
    assert S.PropertySimilarSchema().load({"property": "8102930727"})["status"] == "for_sale"
    assert S.PropertySimilarSchema().load({"property": "8102930727", "status": "For_Rent"})["status"] == "for_rent"
    rejects(S.PropertySimilarSchema, {"property": "8102930727", "status": "off_market"}, "status", "Must be one of")


def test_properties_batch():
    loaded = S.PropertiesBatchSchema().load({"properties": "8102930727, M94474-22407, 8102930727,"
                                                           "https://www.realtor.com/realestateandhomes-detail/x_M74205-06606"})
    assert loaded == {"properties": ["8102930727", "9447422407", "7420506606"]}
    rejects(S.PropertiesBatchSchema, {}, "properties", "required")
    rejects(S.PropertiesBatchSchema, {"properties": "8102930727, bogus"}, "properties", "'bogus'")
    rejects(S.PropertiesBatchSchema, {"properties": ",".join(str(1000000000 + i) for i in range(21))},
            "properties", "At most 20")


def test_by_mls():
    assert S.ByMlsSchema().load({"mls_id": " 3401964 "}) == {"mls_id": "3401964", "mls_source": None}
    assert S.ByMlsSchema().load({"mls_id": "3401964", "mls_source": "autx"})["mls_source"] == "autx"
    rejects(S.ByMlsSchema, {}, "mls_id", "required")
    rejects(S.ByMlsSchema, {"mls_id": "3401964", "mls_source": "x" * 21}, "mls_source")


# ---- communities / locations ----------------------------------------------------------------

def test_communities_and_locations():
    loaded = S.CommunitiesSearchSchema().load({"location": "Austin_TX", "limit": "10", "page": "3"})
    assert loaded == {"location": "Austin, TX", "limit": 10, "page": 3}
    rejects(S.CommunitiesSearchSchema, {}, "location", "required")
    assert S.LocationsSearchSchema().load({"query": " 787 "}) == {"query": "787"}
    rejects(S.LocationsSearchSchema, {}, "query", "required")
    rejects(S.LocationsSearchSchema, {"query": "x" * 201}, "query")


# ---- agents ----------------------------------------------------------------------------------

def test_agents_search():
    loaded = S.AgentsSearchSchema().load({"location": "Austin, TX"})
    assert loaded["location"] == "Austin, TX" and loaded["name"] is None and loaded["sort"] == "relevant"
    assert loaded["limit"] == 20 and loaded["page"] == 1 and loaded["agent_type"] is None
    loaded = S.AgentsSearchSchema().load({"name": "Knolly", "agent_type": "Buyer", "language": "Spanish",
                                          "min_price": "300000", "max_price": "900000", "sort": "most_sales",
                                          "limit": "100", "page": "50"})
    assert loaded["location"] is None and loaded["agent_type"] == "buyer" and loaded["language"] == "Spanish"
    assert loaded["min_price"] == 300000 and loaded["sort"] == "most_sales"
    assert S.AgentsSearchSchema().load({"location": "https://www.realtor.com/realestateagents/Austin_TX"})["location"] == "Austin, TX"


@pytest.mark.parametrize("data,field,contains", [
    ({}, "location", "location (city or ZIP) and/or an agent name"),
    ({"sort": "ratings"}, "location", "and/or"),
    ({"location": "Austin, TX", "agent_type": "broker"}, "agent_type", "Must be one of"),
    ({"location": "Austin, TX", "sort": "best"}, "sort", "Must be one of"),
    ({"location": "Austin, TX", "limit": "101"}, "limit", None),
    ({"location": "Austin, TX", "limit": "100", "page": "51"}, "page", "5,000"),
    ({"location": "Austin, TX", "min_price": "900000", "max_price": "300000"}, "max_price", "must not exceed"),
    ({"name": "K"}, "name", None),
    ({"location": "Austin, TX", "query": "x"}, "query", "Unknown"),
])
def test_agents_search_rejects(data, field, contains):
    rejects(S.AgentsSearchSchema, data, field, contains)


def test_agent_schema():
    for value in ("184731", "https://www.realtor.com/realestateagents/Knolly-Williams_Austin_TX_184731_446999691"):
        assert S.AgentSchema().load({"agent": value}) == {"agent": "184731"}
    assert S.AgentSchema().load({"agent": "56a649a10fa417010073f11b"}) == {"agent": "56a649a10fa417010073f11b"}
    rejects(S.AgentSchema, {}, "agent", "required")
    rejects(S.AgentSchema, {"agent": "knolly williams"}, "agent", "agent id")
    rejects(S.AgentSchema, {"agent": "https://www.realtor.com/realestateagents/Austin_TX"}, "agent", "profile link")
    rejects(S.AgentSchema, {"agent": "184731", "id": "184731"}, "id", "Unknown")


def test_agent_listings_and_sold():
    loaded = S.AgentListingsSchema().load({"agent": "184731"})
    assert loaded == {"agent": "184731", "status": "all", "limit": 50, "page": 1}
    assert S.AgentListingsSchema().load({"agent": "184731", "status": "FOR_RENT"})["status"] == "for_rent"
    rejects(S.AgentListingsSchema, {"agent": "184731", "status": "sold"}, "status", "Must be one of")
    loaded = S.AgentSoldSchema().load({"agent": "184731", "limit": "200", "page": "50"})
    assert loaded["limit"] == 200 and loaded["page"] == 50
    rejects(S.AgentSoldSchema, {"agent": "184731", "limit": "200", "page": "51"}, "page", "10,000")


# ---- markets / mortgage / schools -------------------------------------------------------------

def test_market_schema():
    assert S.MarketSchema().load({"location": "78752"}) == {"location": "78752"}
    assert S.MarketSchema().load({"location": "https://www.realtor.com/local/market/texas/travis-county/austin"}) == \
        {"location": "Austin, Texas"}
    rejects(S.MarketSchema, {}, "location", "required")


def test_mortgage_schema():
    assert S.MortgageRatesSchema().load({"state": "tx"}) == {"state": "tx", "rate_type": "purchase"}
    assert S.MortgageRatesSchema().load({"state": "CA", "rate_type": "Refinance"})["rate_type"] == "refinance"
    rejects(S.MortgageRatesSchema, {}, "state", "required")
    rejects(S.MortgageRatesSchema, {"state": "XX"}, "state", "Must be one of")
    rejects(S.MortgageRatesSchema, {"state": "TX", "rate_type": "heloc"}, "rate_type", "Must be one of")
    rejects(S.MortgageRatesSchema, {"state": "TX", "zip": "78704"}, "zip", "Unknown")


def test_schools_schema():
    loaded = S.SchoolsSearchSchema().load({"location": "78704"})
    assert loaded == {"location": "78704", "limit": 50, "page": 1}
    rejects(S.SchoolsSearchSchema, {}, "location", "required")
    rejects(S.SchoolsSearchSchema, {"location": "78704", "limit": "0"}, "limit")
