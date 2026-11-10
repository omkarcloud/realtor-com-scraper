"""Marshmallow request schemas for every /realtor-com/* route.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair; the resolvers live in realtor_com/refs.py):

    location   "Austin, TX", "78704", "Zilker, Austin, TX", the site's slug
               ("Austin_TX") or a realtor.com search / apartments / agents /
               market page link
    property   a property id (8102930727), the permalink tail (M81029-30727),
               the full permalink, or the property / rental page link
    agent      a fulfillment id (184731) or the agent's profile link

Paging follows the gateway's caps (2026-11-07): at most 200 rows a call and
offset + limit <= 10,000 per listing search; the agent directory answers
offsets up to 5,000.
"""
from marshmallow import ValidationError, fields, missing, validate, validates_schema

from schema_fields import (
    BaseSchema, ChoiceField, CommaListField, Flag, LimitField, NonNegativeNumber, PageField, PositiveInt,
    QueryField, RefField, StrippedString,
)
from realtor_com import refs

SEARCH_PAGE_SIZE = 50
SEARCH_MAX_LIMIT = 200
SEARCH_OFFSET_CAP = 10000
AGENTS_PAGE_SIZE = 20
AGENTS_MAX_LIMIT = 100
AGENTS_OFFSET_CAP = 5000
MAX_POLYGON_POINTS = 60
MAX_BATCH = 20


class LocationRefField(RefField):
    resolver = staticmethod(refs.resolve_location)


class PropertyRefField(RefField):
    resolver = staticmethod(refs.resolve_property)


class AgentRefField(RefField):
    resolver = staticmethod(refs.resolve_agent)


class _NonNegativeInt(fields.Integer):
    def __init__(self, max_value=None, **kwargs):
        kwargs.setdefault("load_default", None)
        kwargs.setdefault("validate", validate.Range(min=0, max=max_value))
        super().__init__(strict=False, **kwargs)


_LOCATION_DESCRIPTION = ('a city ("Austin, TX"), ZIP code ("78704"), neighborhood ("Zilker, Austin, TX"), '
                         'county, the site slug ("Austin_TX") or a realtor.com search page link')


def _offset_cap(cap, name="page"):
    def check(self, data, **kwargs):
        page, limit = data.get("page") or 1, data.get("limit") or 1
        if (page - 1) * limit + limit > cap:
            raise ValidationError(f"page x limit must stay within the site's first {cap:,} results.", name)
    return validates_schema(check)


# ---- listings ---------------------------------------------------------------------------

class _SearchFilters(BaseSchema):
    property_types = CommaListField(allowed=list(refs.PROPERTY_TYPES), upper=False, max_items=len(refs.PROPERTY_TYPES),
                                    metadata={"description": "comma list of " + ", ".join(refs.PROPERTY_TYPES) +
                                              " (default: all)"})
    min_price = NonNegativeNumber(metadata={"description": "minimum list price / monthly rent in USD"})
    max_price = NonNegativeNumber(metadata={"description": "maximum list price / monthly rent in USD"})
    min_beds = _NonNegativeInt(max_value=20, metadata={"description": "minimum bedrooms (0 = studio)"})
    max_beds = PositiveInt(max_value=20, metadata={"description": "maximum bedrooms"})
    min_baths = NonNegativeNumber(metadata={"description": "minimum bathrooms (1, 1.5, 2, ...)"})
    max_baths = NonNegativeNumber(metadata={"description": "maximum bathrooms"})
    min_sqft = PositiveInt(metadata={"description": "minimum interior square feet"})
    max_sqft = PositiveInt(metadata={"description": "maximum interior square feet"})
    min_lot_sqft = PositiveInt(metadata={"description": "minimum lot size in square feet (1 acre = 43560)"})
    max_lot_sqft = PositiveInt(metadata={"description": "maximum lot size in square feet"})
    min_year_built = PositiveInt(max_value=2100, metadata={"description": "earliest year built"})
    max_year_built = PositiveInt(max_value=2100, metadata={"description": "latest year built"})
    max_hoa = NonNegativeNumber(metadata={"description": "maximum HOA fee per month in USD (0 = no HOA)"})
    listed_within_days = PositiveInt(max_value=3650, metadata={"description": "only homes listed in the last N days"})
    include_pending = Flag(metadata={"description": "true also returns pending / contingent homes, false hides them "
                                                    "(default: the site's own mix)"})
    foreclosure = Flag(metadata={"description": "true = foreclosures only, false = none"})
    new_construction = Flag(metadata={"description": "true = new construction only, false = none"})
    keywords = CommaListField(upper=False, max_items=10, metadata={
        "description": "comma list of listing keywords (pool, garage, view, ...)"})
    cats = Flag(metadata={"description": "rentals: true = cats allowed"})
    dogs = Flag(metadata={"description": "rentals: true = dogs allowed"})
    sort = ChoiceField(list(refs.SEARCH_SORTS), load_default="relevant", metadata={
        "description": "relevant (default, the site's order), newest, price_low, price_high, sold_date, photo_count, "
                       "beds, baths, sqft, lot_size, last_updated, year_built, price_reduced"})
    limit = LimitField(default=SEARCH_PAGE_SIZE, max_size=SEARCH_MAX_LIMIT,
                       metadata={"description": f"homes per page (default {SEARCH_PAGE_SIZE}, max {SEARCH_MAX_LIMIT})"})
    page = PageField(max_page=SEARCH_OFFSET_CAP, metadata={"description": "page number"})

    @validates_schema
    def _ranges(self, data, **kwargs):
        for low, high in (("min_price", "max_price"), ("min_beds", "max_beds"), ("min_baths", "max_baths"),
                          ("min_sqft", "max_sqft"), ("min_lot_sqft", "max_lot_sqft"),
                          ("min_year_built", "max_year_built")):
            if data.get(low) is not None and data.get(high) is not None and data[low] > data[high]:
                raise ValidationError(f"{low} must not exceed {high}.", high)

    _cap = _offset_cap(SEARCH_OFFSET_CAP)


_STATUS_DESCRIPTION = "for_sale (default), for_rent, sold, off_market, ready_to_build"


class SearchSchema(_SearchFilters):
    location = LocationRefField(metadata={"description": _LOCATION_DESCRIPTION})
    status = ChoiceField(list(refs.SEARCH_STATUS), load_default="for_sale", metadata={"description": _STATUS_DESCRIPTION})
    sold_within_days = PositiveInt(max_value=3650, metadata={
        "description": "status=sold: only sales closed in the last N days"})


class SearchNearbySchema(_SearchFilters):
    latitude = fields.Float(required=True, validate=validate.Range(min=-90, max=90),
                            metadata={"description": "center latitude"})
    longitude = fields.Float(required=True, validate=validate.Range(min=-180, max=180),
                             metadata={"description": "center longitude"})
    radius = NonNegativeNumber(load_default=2, validate=validate.Range(min=0.1, max=50),
                               metadata={"description": "radius in miles (default 2, max 50)"})
    status = ChoiceField(list(refs.SEARCH_STATUS), load_default="for_sale", metadata={"description": _STATUS_DESCRIPTION})
    sold_within_days = PositiveInt(max_value=3650, metadata={
        "description": "status=sold: only sales closed in the last N days"})


class PolygonField(StrippedString):
    """'lng lat, lng lat, ...' (3 to 60 points, closed automatically) -> [[lng, lat], ...]."""

    def _deserialize(self, value, attr, data, **kwargs):
        value = super()._deserialize(value, attr, data, **kwargs)
        if value is None:
            return None
        points = []
        for pair in (p.strip() for p in value.replace(";", ",").split(",") if p.strip()):
            parts = pair.split()
            if len(parts) != 2:
                raise ValidationError("A polygon is 'lng lat, lng lat, ...' (at least 3 points).")
            try:
                lng, lat = float(parts[0]), float(parts[1])
            except ValueError:
                raise ValidationError("Polygon points must be numbers: 'lng lat, lng lat, ...'.")
            if not (-180 <= lng <= 180 and -90 <= lat <= 90):
                raise ValidationError("Polygon points must be 'lng lat' with lng in -180..180 and lat in -90..90.")
            points.append([lng, lat])
        if len(points) < 3:
            raise ValidationError("A polygon needs at least 3 points ('lng lat, lng lat, lng lat').")
        if len(points) > MAX_POLYGON_POINTS:
            raise ValidationError(f"At most {MAX_POLYGON_POINTS} polygon points.")
        if points[0] != points[-1]:
            points.append(list(points[0]))
        return points


class SearchPolygonSchema(_SearchFilters):
    polygon = PolygonField(required=True, metadata={
        "description": "the area as 'lng lat, lng lat, ...' (3 to 60 points; closed automatically)"})
    status = ChoiceField(list(refs.SEARCH_STATUS), load_default="for_sale", metadata={"description": _STATUS_DESCRIPTION})
    sold_within_days = PositiveInt(max_value=3650, metadata={
        "description": "status=sold: only sales closed in the last N days"})


_PROPERTY_DESCRIPTION = ("realtor.com property id (8102930727), the permalink tail (M81029-30727) or the "
                         "property's realtor.com link")


class PropertySchema(BaseSchema):
    property = PropertyRefField(metadata={"description": _PROPERTY_DESCRIPTION})


class PropertySchoolsSchema(PropertySchema):
    radius = NonNegativeNumber(load_default=5, validate=validate.Range(min=0.5, max=25),
                               metadata={"description": "nearby-school radius in miles (default 5, max 25)"})


class PropertySimilarSchema(PropertySchema):
    status = ChoiceField(list(refs.SIMILAR_STATUS), load_default="for_sale",
                         metadata={"description": "for_sale (default), for_rent or sold"})


class PropertyListField(CommaListField):
    """Comma list of property ids / links, each resolved like `property`."""

    def __init__(self, **kwargs):
        kwargs["load_default"] = missing if kwargs.get("required") else None
        super().__init__(**kwargs)

    def _deserialize(self, value, attr, data, **kwargs):
        items = super()._deserialize(value, attr, data, **kwargs) or []
        out = []
        for item in items:
            try:
                resolved = refs.resolve_property(item)
            except ValueError as e:
                raise ValidationError(f"{item!r}: {e}")
            if resolved not in out:
                out.append(resolved)
        if not out:
            raise ValidationError("Must not be empty.")
        return out


class PropertiesBatchSchema(BaseSchema):
    properties = PropertyListField(required=True, upper=False, max_items=MAX_BATCH, metadata={
        "description": f"comma list of up to {MAX_BATCH} property ids, permalink tails or realtor.com links"})


class ByMlsSchema(BaseSchema):
    mls_id = QueryField(max_length=40, metadata={"description": "the MLS listing number (3401964)"})
    mls_source = StrippedString(load_default=None, validate=validate.Length(max=20), metadata={
        "description": "the MLS id to search in (AUTX); default: every MLS"})


# ---- communities ---------------------------------------------------------------------------

class CommunitiesSearchSchema(BaseSchema):
    location = LocationRefField(metadata={"description": _LOCATION_DESCRIPTION})
    limit = LimitField(default=SEARCH_PAGE_SIZE, max_size=SEARCH_MAX_LIMIT,
                       metadata={"description": f"communities per page (default {SEARCH_PAGE_SIZE}, max {SEARCH_MAX_LIMIT})"})
    page = PageField(max_page=SEARCH_OFFSET_CAP, metadata={"description": "page number"})
    _cap = _offset_cap(SEARCH_OFFSET_CAP)


# ---- locations -----------------------------------------------------------------------------

class LocationsSearchSchema(BaseSchema):
    query = QueryField(metadata={"description": "place name, ZIP code, neighborhood, street, school or address to look up"})


# ---- agents -------------------------------------------------------------------------------

class AgentsSearchSchema(BaseSchema):
    location = LocationRefField(required=False, load_default=None, metadata={
        "description": "a city (\"Austin, TX\") or ZIP code; a realtor.com agents directory link works too"})
    name = StrippedString(load_default=None, validate=validate.Length(min=2, max=100),
                          metadata={"description": "agent name to search for (with or without a location)"})
    agent_type = ChoiceField(list(refs.AGENT_TYPES), metadata={"description": "buyer or seller agents only"})
    language = StrippedString(load_default=None, validate=validate.Length(min=2, max=40),
                              metadata={"description": "agents speaking this language (spanish, mandarin, ...)"})
    min_price = NonNegativeNumber(metadata={"description": "agents working deals above this price (USD)"})
    max_price = NonNegativeNumber(metadata={"description": "agents working deals below this price (USD)"})
    sort = ChoiceField(list(refs.AGENT_SORTS), load_default="relevant", metadata={
        "description": "relevant (default), recent_activity, most_sales, ratings, recommendations"})
    limit = LimitField(default=AGENTS_PAGE_SIZE, max_size=AGENTS_MAX_LIMIT,
                       metadata={"description": f"agents per page (default {AGENTS_PAGE_SIZE}, max {AGENTS_MAX_LIMIT})"})
    page = PageField(max_page=AGENTS_OFFSET_CAP, metadata={"description": "page number"})

    @validates_schema
    def _needs_a_subject(self, data, **kwargs):
        if not data.get("location") and not data.get("name"):
            raise ValidationError("Give a location (city or ZIP) and/or an agent name.", "location")
        if data.get("min_price") is not None and data.get("max_price") is not None \
                and data["min_price"] > data["max_price"]:
            raise ValidationError("min_price must not exceed max_price.", "max_price")

    _cap = _offset_cap(AGENTS_OFFSET_CAP)


_AGENT_DESCRIPTION = "agent id (184731) or the agent's realtor.com profile link"


class AgentSchema(BaseSchema):
    agent = AgentRefField(metadata={"description": _AGENT_DESCRIPTION})


class AgentListingsSchema(AgentSchema):
    status = ChoiceField(["all", "for_sale", "for_rent"], load_default="all",
                         metadata={"description": "all (default), for_sale or for_rent"})
    limit = LimitField(default=SEARCH_PAGE_SIZE, max_size=SEARCH_MAX_LIMIT,
                       metadata={"description": f"listings per page (default {SEARCH_PAGE_SIZE}, max {SEARCH_MAX_LIMIT})"})
    page = PageField(max_page=SEARCH_OFFSET_CAP, metadata={"description": "page number"})
    _cap = _offset_cap(SEARCH_OFFSET_CAP)


class AgentSoldSchema(AgentSchema):
    limit = LimitField(default=SEARCH_PAGE_SIZE, max_size=SEARCH_MAX_LIMIT,
                       metadata={"description": f"sales per page (default {SEARCH_PAGE_SIZE}, max {SEARCH_MAX_LIMIT})"})
    page = PageField(max_page=SEARCH_OFFSET_CAP, metadata={"description": "page number"})
    _cap = _offset_cap(SEARCH_OFFSET_CAP)


# ---- markets / mortgage / schools ------------------------------------------------------------

class MarketSchema(BaseSchema):
    location = LocationRefField(metadata={"description": _LOCATION_DESCRIPTION})


class MortgageRatesSchema(BaseSchema):
    state = ChoiceField(sorted(refs.US_STATES), required=True, load_default=missing, metadata={
        "description": "two-letter US state code (TX, CA, ...)"})
    rate_type = ChoiceField(list(refs.MORTGAGE_RATE_TYPES), load_default="purchase",
                            metadata={"description": "purchase (default) or refinance"})


class SchoolsSearchSchema(BaseSchema):
    location = LocationRefField(metadata={"description": "a city (\"Austin, TX\") or ZIP code"})
    limit = LimitField(default=SEARCH_PAGE_SIZE, max_size=SEARCH_MAX_LIMIT,
                       metadata={"description": f"schools per page (default {SEARCH_PAGE_SIZE}, max {SEARCH_MAX_LIMIT})"})
    page = PageField(max_page=SEARCH_OFFSET_CAP, metadata={"description": "page number"})
    _cap = _offset_cap(SEARCH_OFFSET_CAP)
