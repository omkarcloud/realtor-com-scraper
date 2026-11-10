"""realtor.com transport: plain curl_cffi with browser-impersonated TLS
against the site's own GraphQL gateway. No browser, no cookies, no token.

ONE upstream surface serves every endpoint:

  POST https://www.realtor.com/frontdoor/graphql   {operationName, query, variables}

The gateway is cookie-free and answers plain curl_cffi `chrome` from any
exit (a home connection, datacenter and residential proxies, 2026-11-07). Its two
hard requirements, found the hard way: the `rdc-client-name` +
`rdc-client-version` headers (else 400 "missing client identification
headers") and `operationName` in the body (else 400 "Required parameter is
missing", which looks like a dead endpoint). Introspection is off; the
query texts below were recovered from the site's public JS chunks and
validated one field at a time (a wrong field fails the whole query with
"Cannot query field X on type Y", so the selections are frozen here).

Every HTML page of the site (search, detail, rentals, agents, market,
mortgage) is Kasada: HTTP 429 + the KPSDK bootstrap on every exit and every
curl TLS profile (chrome / chrome131 / safari17_0 / edge101). None is
fetched; the only data with no GraphQL twin is the market page's
month-over-month trend table, which this scraper does not sell.

Roots used (realtor_com/api.py says which endpoint rides which):
  search_suggestions, home_search, home (+ related_homes, location.
  neighborhoods), home_popularity, community_search, search_agents,
  agent_branding, agent_branding_reviews, agent_branding_recommendations,
  closings_search, geo (geo_statistics, recommended),
  customer_nearby_locations, mortgage_rate_trends, school_search.

Egress: the pod's own IP by default (config.realtor_com_proxy(), knob
REALTOR_COM_EXIT); a block moves the thread to a sticky datacenter exit for
config.REALTOR_COM_BLOCK_HOLD_S. A retryable failure drops the thread's
session so the retry rides a fresh exit.

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  RealtorUpstreamError  transport failure / 5xx / unreadable body  — retryable
  RealtorBlocked        403 / 429 / Kasada page where JSON was due   — retryable
  RealtorBadRequest     the gateway rejected the query's values      — never retried
  RealtorNotFound       unknown property / agent / location          — never retried
"""
import json
import os
import sys
import threading
import time

# Allow direct execution (python realtor_com/fetch.py): flat imports resolve
# like under the server. Idempotent when imported normally.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
import egress
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError
from realtor_com.refs import SITE

GRAPHQL_URL = SITE + "/frontdoor/graphql"
IMPERSONATE = "chrome"
TIMEOUT = 40          # a 200-card search page is ~1 MB and 1-2 s

# rdc-client-name / rdc-client-version pairs the site itself sends; any pair
# serves any query, the names only tag the caller (2026-11-07).
CLIENT_SEARCH = ("RDC_WEB_SRP_FS_PAGE", "3.0.2515")
CLIENT_DETAILS = ("RDC_WEB_DETAILS_PAGE", "2.1389.0")
CLIENT_AGENTS = ("agent-branding-profile", "0.0.916")
CLIENT_DEFAULT = ("default-client", "1.0.0")

BASE_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": egress.site_accept_language("realtor-com"),
    "content-type": "application/json",
    "origin": SITE,
    "referer": SITE + "/",
}

_KASADA_MARKERS = ("x-kpsdk", "ips.js", "kpsdk", "<html")


class RealtorUpstreamError(UpstreamError):
    """Transport failure, 5xx or an unreadable body — retryable."""


class RealtorBlocked(RealtorUpstreamError, Blocked):
    """403 / 429 or the Kasada page where JSON was expected — retryable on a fresh exit."""


class RealtorBadRequest(BadRequest):
    """The gateway rejected the query's values — never retried."""


class RealtorNotFound(NotFound):
    """Property / agent / location does not exist — never retried."""


# ---- sessions ------------------------------------------------------------------
# One curl session per cheroot worker thread (a curl handle must not be
# shared across threads). A thread that was blocked rides a sticky
# datacenter exit for config.REALTOR_COM_BLOCK_HOLD_S, then returns to the
# knob's tier.
_local = threading.local()


def _proxy_for_thread():
    blocked_until = getattr(_local, "blocked_until", 0.0)
    if blocked_until > time.monotonic():
        return config.realtor_com_cooldown_proxy()
    return config.realtor_com_proxy()


def _session():
    sess = getattr(_local, "session", None)
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        proxy = _proxy_for_thread()
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
            sess.headers["accept-language"] = egress.accept_language(proxy)
        _local.session = sess
    return sess


def _drop_session():
    """Close the thread's session so a poisoned keep-alive / exit dies."""
    sess = getattr(_local, "session", None)
    _local.session = None
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _note_block():
    _local.blocked_until = time.monotonic() + config.REALTOR_COM_BLOCK_HOLD_S


def _retrying(fn):
    """Run fn() under the shared retry policy (RealtorUpstreamError only;
    NotFound / BadRequest surface immediately)."""
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except RealtorUpstreamError as e:
            last = e
            _drop_session()
            if attempt < config.MAX_RETRIES:
                time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


# ---- the one call ----------------------------------------------------------------

def graphql(operation, query, variables=None, client=CLIENT_SEARCH, label=None):
    """POST one operation; return the parsed JSON body ({data, errors})."""
    label = label or operation
    payload = json.dumps({"operationName": operation, "query": query, "variables": variables or {}})
    headers = {**BASE_HEADERS, "rdc-client-name": client[0], "rdc-client-version": client[1]}

    def once():
        try:
            sess = _session()
            # the session's Accept-Language follows its exit; request headers win in curl_cffi
            lang = sess.headers.get("accept-language")
            resp = sess.post(GRAPHQL_URL, data=payload, headers={**headers, "accept-language": lang} if lang else headers,
                             timeout=TIMEOUT)
        except Exception as e:
            raise RealtorUpstreamError(f"{label}: request failed: {type(e).__name__}: {e}")
        status = resp.status_code
        text = resp.text or ""
        if status in (401, 403, 429):
            _note_block()
            raise RealtorBlocked(f"{label}: HTTP {status}")
        try:
            body = resp.json()
        except Exception:
            head = text[:2000].lower()
            if any(m in head for m in _KASADA_MARKERS):
                _note_block()
                raise RealtorBlocked(f"{label}: challenge page where JSON was expected (HTTP {status})")
            raise RealtorUpstreamError(f"{label}: non-JSON body (HTTP {status}): {text[:120]}")
        if status == 400:
            raise RealtorBadRequest(f"{label}: {_first_error(body) or text[:200]}")
        if status != 200:
            raise RealtorUpstreamError(f"{label}: HTTP {status}: {text[:120]}")
        if not isinstance(body, dict):
            raise RealtorUpstreamError(f"{label}: unexpected body shape")
        return body
    return _retrying(once)


def _first_error(body):
    errors = (body or {}).get("errors") if isinstance(body, dict) else None
    if errors and isinstance(errors, list) and isinstance(errors[0], dict):
        return errors[0].get("message")
    return None


_NOT_FOUND_WORDS = ("not found", "does not exist", "no agent", "unknown")
_BAD_INPUT_WORDS = ("invalid input value", "is not defined by type", "cannot query field",
                    "must be", "expected type", "required type", "is not allowed", "failed custom validation")


def root(body, name, label=None):
    """body -> data[name]. A null root with an error: 'not found' messages
    become NotFound, validation messages BadRequest, the rest UpstreamError.
    A present root with partial errors is returned as is."""
    label = label or name
    data = body.get("data") if isinstance(body, dict) else None
    value = data.get(name) if isinstance(data, dict) else None
    if value is not None:
        return value
    message = _first_error(body) or ""
    low = message.lower()
    if any(w in low for w in _NOT_FOUND_WORDS):
        raise RealtorNotFound(f"{label}: {message}")
    if any(w in low for w in _BAD_INPUT_WORDS):
        raise RealtorBadRequest(f"{label}: {message}")
    if message:
        raise RealtorUpstreamError(f"{label}: {message}")
    return None


# ---- query texts -------------------------------------------------------------------
# Frozen selections; every field was validated against the gateway on
# 2026-11-07 (a wrong field name fails the whole query).

SUGGESTIONS_QUERY = """
query SearchSuggestions($searchInput: SearchSuggestionsInput!) {
  search_suggestions(search_input: $searchInput) {
    geo_results { type text geo { _id mpr_id area_type city state_code postal_code county slug_id geo_id
      city_slug_id centroid { lat lon } street line school school_district neighborhood } }
    typeahead_results { display_string url geo { _id area_type slug_id } }
    has_results
  }
}
"""

SEARCH_CARD = """
  property_id listing_id permalink href status mls_status list_date last_update_date last_status_change_date
  pending_date list_price list_price_min list_price_max price_per_sqft last_sold_price last_sold_date tags
  flags { is_coming_soon is_contingent is_garage_present is_new_construction is_pending is_short_sale
    is_foreclosure is_senior_community is_for_rent is_deal_available is_price_reduced is_new_listing
    is_subdivision is_plan }
  description { type sub_type name beds baths baths_full baths_half baths_consolidated sqft lot_sqft year_built
    garage stories }
  location { address { line unit city state_code postal_code coordinate { lat lon } }
    county { name fips_code } neighborhoods { name } }
  hoa { fee }
  source { id type name listing_id agents { agent_name agent_id office_name office_id } }
  primary_photo(https: true) { href }
  photos(https: true) { href }
  open_houses { start_date end_date description methods }
  virtual_tours { href type }
  advertisers { type name fulfillment_id email nrds_id state_license phones { number type primary ext }
    office { name email fulfillment_id href phones { number type } } broker { name fulfillment_id }
    builder { name fulfillment_id } }
  current_estimates { estimate estimate_high estimate_low date isbest_homevalue source { type name } }
  pet_policy { cats dogs dogs_small dogs_large }
  units { list_price availability { date } description { beds baths baths_consolidated sqft } }
  tax_record { apn tax_parcel_id }
"""

SEARCH_QUERY = """
query ConsumerSearchQuery($query: HomeSearchCriteria!, $limit: Int, $offset: Int, $sort: [SearchAPISort],
                          $bucket: SearchAPIBucket) {
  home_search(query: $query, limit: $limit, offset: $offset, sort: $sort, bucket: $bucket) {
    count total
    results { %s }
  }
}
""" % SEARCH_CARD

HOME_QUERY = """
query GetHomeDetails($property_id: ID!) {
  home(property_id: $property_id) {
    property_id listing_id href permalink status mls_status list_date list_price list_price_min list_price_max
    price_per_sqft last_sold_price last_sold_date last_status_change_date last_update_date
    last_price_change_amount last_price_change_date pending_date tags days_on_market photo_count
    description { name type sub_type beds baths baths_full baths_half baths_consolidated beds_min beds_max
      baths_min baths_max sqft sqft_min sqft_max lot_sqft year_built garage stories text }
    details { category text parent_category }
    flags { is_coming_soon is_contingent is_garage_present is_new_construction is_pending is_short_sale
      is_foreclosure is_senior_community is_for_rent is_deal_available is_price_reduced is_new_listing
      is_subdivision is_plan }
    location { address { line unit city state_code state postal_code coordinate { lat lon } }
      county { name fips_code } neighborhoods { id name level geo_type city state_code slug_id centroid { lat lon } }
      parcel { parcel_id } street_view_url }
    hoa { fee }
    source { id type name listing_id disclaimer { text href } agents { agent_name agent_id office_name office_id }
      raw { status style tax_amount } }
    primary_photo(https: true) { href }
    photos(https: true) { href title tags { label probability } }
    virtual_tours { href type }
    matterport { videos { href } }
    advertisers { fulfillment_id name email type href slogan state_license nrds_id mls_set
      phones { number type primary ext } photo { href }
      office { name email href phones { number type } address { line city state_code postal_code } }
      broker { name } builder { name } }
    consumer_advertisers { type name href agent_id office_id phone }
    property_history { date event_name price price_change price_sqft price_change_percentage days_after_listed
      source_name source_listing_id
      listing { listing_id status list_price list_date last_status_change_date last_update_date
        photos(https: true) { href } description { sqft } } }
    tax_history { year tax assessment { building land total } market { building land total } }
    tax_record { apn tax_parcel_id }
    estimates { current_values { estimate estimate_high estimate_low date isbest_homevalue source { type name } }
      forecast_values { source { type name } estimates { estimate date } }
      historical_values { source { type name } estimates { estimate date } } }
    schools { schools { id name rating distance_in_miles education_levels funding_type student_count grades
      parent_rating assigned coordinate { lat lon } district { id name } } }
    nearby_schools(radius: %s, limit_per_level: %s) { schools { id name rating distance_in_miles education_levels
      funding_type student_count grades parent_rating assigned coordinate { lat lon } district { id name } } }
    local { noise { score noise_categories { type text } }
      flood { fema_zone flood_factor_score flood_factor_severity flood_trend flood_insurance_text }
      wildfire { fire_factor_score fire_factor_severity }
      heat { heat_factor_score heat_factor_severity }
      wind { wind_factor_score }
      air { air_factor_score } }
    popularity { periods { last_n_days views_total saves_total clicks_total shares_total leads_total } }
    open_houses { start_date end_date description methods }
    mortgage { estimate { monthly_payment total_payment loan_amount down_payment
      monthly_payment_details { type amount display_name } } rates_url property_tax_rate insurance_rate }
    monthly_fees { description display_amount }
    one_time_fees { description display_amount }
    pet_policy { cats dogs dogs_small dogs_large }
    units { list_price availability { date } description { beds baths baths_consolidated sqft }
      photos(https: true) { href } }
    terms { text category }
    community { href description { name text }
      advertisers { name type href phones { number type } office { name } } }
  }
}
"""
NEARBY_SCHOOLS_RADIUS = 5.0
NEARBY_SCHOOLS_PER_LEVEL = 5

NEIGHBORHOODS_QUERY = """
query GetNeighborhoodData($propertyId: ID!) {
  home(property_id: $propertyId) {
    property_id
    location { neighborhoods { id name level geo_type city state_code slug_id centroid { lat lon } boundary } }
  }
}
"""

# RelatedHome is a slimmer type than SearchHome (no mls_status / tags / hoa /
# county / agent contacts / estimate ranges, 2026-11-07): its own selection.
RELATED_CARD = """
  property_id listing_id permalink href status list_date last_update_date last_status_change_date
  list_price list_price_min list_price_max price_per_sqft last_sold_price last_sold_date
  flags { is_coming_soon is_contingent is_garage_present is_new_construction is_pending is_short_sale
    is_foreclosure is_senior_community is_for_rent is_deal_available is_price_reduced is_new_listing
    is_subdivision is_plan }
  description { type sub_type name beds baths baths_full baths_half baths_consolidated sqft lot_sqft year_built }
  location { address { line unit city state_code postal_code coordinate { lat lon } } neighborhoods { name } }
  source { id type name agents { agent_name } }
  primary_photo(https: true) { href }
  photos(https: true) { href }
  open_houses { start_date end_date description methods }
  virtual_tours { href type }
  advertisers { name office { name } }
  current_estimates { estimate isbest_homevalue }
  units { list_price }
"""

# RelatedHomeType / status are enums: inlined, never passed as JSON strings
# (the gateway rejects them in variables, 2026-11-07).
SIMILAR_QUERY = """
query SimilarHomesData($propertyId: ID!) {
  home(property_id: $propertyId) {
    property_id
    related_homes(query: { type: similar_homes, status: %s }) { results { %s } }
  }
}
"""

NEARBY_SCHOOLS_QUERY = """
query GetNearbySchools($propertyId: ID!) {
  home(property_id: $propertyId) {
    property_id
    nearby_schools(radius: %s, limit_per_level: %s) { schools { id name rating distance_in_miles education_levels
      funding_type student_count grades parent_rating assigned coordinate { lat lon } district { id name } } }
  }
}
"""

COMMUNITY_CARD = """
  property_id href status list_price_min list_price_max photo_count
  description { name text beds_min beds_max baths_min baths_max sqft_min sqft_max type }
  location { address { line city state_code postal_code coordinate { lat lon } } }
  primary_photo(https: true) { href } photos(https: true) { href }
  advertisers { name type href phones { number type } builder { name href } }
  flags { is_new_construction }
"""

COMMUNITIES_QUERY = """
query CommunitySearch($query: CommunitySearchCriteria!, $limit: Int, $offset: Int) {
  community_search(query: $query, limit: $limit, offset: $offset) { count total results { %s } }
}
""" % COMMUNITY_CARD

AGENT_CARD = """
  agents { id fulfillment_id fullname is_paid is_realtor display_ratings has_rps avatar { url initials }
    broker { name fulfillment_id } office { name }
    ratings_reviews { average_rating recommendations_count reviews_count combined_testimonials_and_reviews_count }
    listing_stats { combined_annual { min max } for_sale { count last_listing_date min max }
      recently_sold_annual { count }
      recently_sold_listing_details { listings { baths beds city photo state_code } show_additional } }
    experience { first_year } services { buyer seller } sorting_weight }
  matching_rows
"""

# agent_type is an enum list: inlined by fetch_agents (JSON strings in the
# variables are refused, 2026-11-07).
AGENTS_QUERY = """
query SearchAgents($searchAgentInput: SearchAgentInput) {
  search_agents(search_agent_input: $searchAgentInput) { %s }
}
""" % AGENT_CARD

AGENT_BRANDING_QUERY = """
query AgentBrandingProfile($agentBrandingInput: AgentBrandingInput) {
  agent_branding(agent_branding_input: $agentBrandingInput) {
    branding { fulfillment_id id is_paid is_realtor designations display_ratings has_rps endorsements
      avatar { initials url } bio fullname website intent_type broker { name website fulfillment_id }
      languages specializations { name } experience { first_year first_month label }
      ratings_reviews { average_rating reviews_count recommendations_count combined_testimonials_and_reviews_count }
      served_areas { name state_code }
      listing_stats { combined_annual { max min } for_sale { count last_listing_date min max }
        recently_sold { count last_sold_date min max } recently_sold_annual { count }
        recently_sold_listing_details { listings { baths beds city photo state_code } show_additional } }
      mls { mls_set agent_id id primary license_number inactivation_date status }
      office { name phones { type value } website
        address { address_formatted_line_1 address_formatted_line_2 city postal_code state_code } }
      phones { type value } license_number license_state is_empty_profile
      social_media { facebook { href } instagram { href } linkedin { href } tiktok { href } x { href } youtube { href } }
      about_video { id source url } services { buyer seller }
      questions_and_answers { question_text answer_text } }
  }
}
"""

AGENT_REVIEWS_QUERY = """
query AgentBrandingReviews($agentBrandingReviewsInput: AgentBrandingReviewsInput) {
  agent_branding_reviews(agent_branding_review_input: $agentBrandingReviewsInput) {
    reviews { id source_id responsiveness market_expertise comment display_name location year negotiation_skills
      rating professionalism_communication describe_yourself started_timestamp review_date_display
      reply { message reply_date } }
  }
}
"""

AGENT_RECOMMENDATIONS_QUERY = """
query AgentBrandingRecommendations($agentBrandingRecommendationsInput: AgentBrandingRecommendationsInput) {
  agent_branding_recommendations(agent_branding_recommendation_input: $agentBrandingRecommendationsInput) {
    recommendations { comment display_name last_updated started_timestamp source_id }
  }
}
"""

CLOSINGS_QUERY = """
query AgentBrandingClosingSearch($query: ClosingsSearchCriteria!, $limit: Int, $offset: Int, $sort: [SearchAPISort]) {
  closings_search(query: $query, offset: $offset, sort: $sort, limit: $limit) {
    count total
    results { property_id listing_id status href list_price
      description { sold_date sold_price baths_consolidated beds lot_sqft sqft stories }
      source { agents { id agent_id type } }
      location { street_view_url address { line city state_code postal_code coordinate { lat lon } } }
      primary_photo(https: true) { href } photos(https: true) { href }
      advertisers { fulfillment_id type }
      flags { is_new_construction is_foreclosure is_short_sale } }
  }
}
"""

HOUSING_MARKET = """
  housing_market { median_listing_price median_rent_price median_sold_price median_days_on_market
    median_price_per_sqft local_hotness_score national_hotness_score local_temperature national_temperature
    hot_market_badge hot_market_rank ratio_of_days_on_market_vs_typical_property_in_county
    ratio_of_ldp_views_vs_typical_property_in_county }
"""

MARKET_QUERY = """
query HousingMarketDetailsQuery($slugId: String) {
  geo(slug_id: $slugId) { slug_id state_code centroid { lat lon } geo_statistics { %s } }
}
""" % HOUSING_MARKET

NEARBY_QUERY = """
query NearbyLocations($slugId: String, $city: String, $stateCode: String, $limit: Int) {
  geo(slug_id: $slugId) { slug_id state_code centroid { lat lon }
    recommended(query: { geo_search_type: city, limit: $limit }) {
      geos { slug_id state_code centroid { lat lon } geo_statistics { %s } } } }
  customer_nearby_locations(customer_nearby_location_input: { city: $city, state_code: $stateCode }) {
    nearby_cities { city slug_id postal_code }
    nearby_zips { city slug_id postal_code }
  }
}
""" % HOUSING_MARKET

MORTGAGE_QUERY = """
query MortgageRateTrends($input: MortgageRateTrendsInput!) {
  mortgage_rate_trends(input: $input) {
    rate_trends { day year month thirty_year_fix thirty_year_fix_apr twenty_year_fix fifteen_year_fix
      fifteen_year_fix_apr ten_year_fix five_one_arm five_one_arm_apr seven_one_arm thirty_year_fix_fha
      thirty_year_fix_va thirty_year_fix_jumbo }
  }
}
"""

SCHOOLS_QUERY = """
query SchoolSearch($query: SchoolSearchCriteria!, $limit: Int, $offset: Int) {
  school_search(query: $query, limit: $limit, offset: $offset) {
    total
    schools { id name rating funding_type education_levels student_count grades parent_rating
      coordinate { lat lon } district { id name } location { city } }
  }
}
"""


# ---- fetchers (raw dicts; parsers.py shapes them) -------------------------------------

def fetch_suggestions(term):
    body = graphql("SearchSuggestions", SUGGESTIONS_QUERY, {"searchInput": {"search_term": term}},
                   client=CLIENT_SEARCH, label="suggestions")
    return root(body, "search_suggestions") or {}


def fetch_search(criteria, limit, offset, sort=None, site_order=True):
    """home_search for a HomeSearchCriteria dict. `sort` is a list of
    {field, direction}; without one `bucket` asks for the site's own order."""
    variables = {"query": criteria, "limit": limit, "offset": offset}
    if sort:
        variables["sort"] = sort
    elif site_order:
        variables["bucket"] = {"sort": "fractal_v1.1.3_fr"}
    body = graphql("ConsumerSearchQuery", SEARCH_QUERY, variables, client=CLIENT_SEARCH, label="search")
    return root(body, "home_search") or {}


def home_query(radius=NEARBY_SCHOOLS_RADIUS, per_level=NEARBY_SCHOOLS_PER_LEVEL):
    return HOME_QUERY % (float(radius), int(per_level))


def _home_root(body, property_id):
    """data.home, or NotFound with one plain message (the gateway's own is
    'Home not found.' with a HOME_NOT_FOUND code)."""
    try:
        home = root(body, "home", label=f"property {property_id}")
    except RealtorNotFound:
        home = None
    if home is None:
        raise RealtorNotFound(f"No realtor.com property with id {property_id}")
    return home


def fetch_home(property_id, radius=NEARBY_SCHOOLS_RADIUS, per_level=NEARBY_SCHOOLS_PER_LEVEL):
    body = graphql("GetHomeDetails", home_query(radius, per_level), {"property_id": str(property_id)},
                   client=CLIENT_DETAILS, label=f"property {property_id}")
    return _home_root(body, property_id)


def fetch_neighborhoods(property_id):
    body = graphql("GetNeighborhoodData", NEIGHBORHOODS_QUERY, {"propertyId": str(property_id)},
                   client=CLIENT_DETAILS, label=f"neighborhoods {property_id}")
    return _home_root(body, property_id)


def fetch_similar(property_id, status="for_sale"):
    query = SIMILAR_QUERY % (status, RELATED_CARD)
    body = graphql("SimilarHomesData", query, {"propertyId": str(property_id)},
                   client=CLIENT_DETAILS, label=f"similar {property_id}")
    return _home_root(body, property_id)


def fetch_nearby_schools(property_id, radius, per_level=NEARBY_SCHOOLS_PER_LEVEL):
    query = NEARBY_SCHOOLS_QUERY % (float(radius), int(per_level))
    body = graphql("GetNearbySchools", query, {"propertyId": str(property_id)},
                   client=CLIENT_DETAILS, label=f"schools {property_id}")
    return _home_root(body, property_id)


def fetch_communities(criteria, limit, offset):
    body = graphql("CommunitySearch", COMMUNITIES_QUERY, {"query": criteria, "limit": limit, "offset": offset},
                   client=CLIENT_SEARCH, label="communities")
    return root(body, "community_search") or {}


def fetch_agents(search_input, agent_type=None):
    """search_agents. `agent_type` ("BUYER" / "SELLER") is inlined as an enum."""
    if agent_type:
        args = ", ".join(f"{k}: {json.dumps(v)}" for k, v in search_input.items() if k != "sort")
        args += f", sort: {search_input['sort']}, agent_type: [{agent_type}]"
        text = "query SearchAgents { search_agents(search_agent_input: { %s }) { %s } }" % (args, AGENT_CARD)
        body = graphql("SearchAgents", text, {}, client=CLIENT_AGENTS, label="agents search")
    else:
        body = graphql("SearchAgents", AGENTS_QUERY, {"searchAgentInput": search_input},
                       client=CLIENT_AGENTS, label="agents search")
    return root(body, "search_agents") or {}


def fetch_agent_branding(agent):
    """agent_branding for a fulfillment id (digits) or a profile id (24 hex)."""
    key = "profile_id" if len(str(agent)) == 24 else "fulfillment_id"
    body = graphql("AgentBrandingProfile", AGENT_BRANDING_QUERY,
                   {"agentBrandingInput": {key: str(agent)}},
                   client=CLIENT_AGENTS, label=f"agent {agent}")
    result = root(body, "agent_branding", label=f"agent {agent}")
    branding = (result or {}).get("branding") if isinstance(result, dict) else None
    if not branding or not branding.get("fulfillment_id"):
        raise RealtorNotFound(f"No realtor.com agent with id {agent}")
    return branding


def fetch_agent_reviews(fulfillment_id):
    body = graphql("AgentBrandingReviews", AGENT_REVIEWS_QUERY,
                   {"agentBrandingReviewsInput": {"fulfillment_id": str(fulfillment_id)}},
                   client=CLIENT_AGENTS, label=f"agent reviews {fulfillment_id}")
    return root(body, "agent_branding_reviews") or {}


def fetch_agent_recommendations(fulfillment_id):
    body = graphql("AgentBrandingRecommendations", AGENT_RECOMMENDATIONS_QUERY,
                   {"agentBrandingRecommendationsInput": {"fulfillment_id": str(fulfillment_id)}},
                   client=CLIENT_AGENTS, label=f"agent recommendations {fulfillment_id}")
    return root(body, "agent_branding_recommendations") or {}


def fetch_closings(mls_agents, limit, offset):
    """closings_search for [{agent_id, id}] (the agent's MLS memberships)."""
    body = graphql("AgentBrandingClosingSearch", CLOSINGS_QUERY,
                   {"query": {"agents": mls_agents}, "limit": limit, "offset": offset,
                    "sort": [{"field": "sold_date", "direction": "desc"}]},
                   client=CLIENT_AGENTS, label="agent closings")
    return root(body, "closings_search") or {}


def fetch_market(slug_id):
    body = graphql("HousingMarketDetailsQuery", MARKET_QUERY, {"slugId": slug_id},
                   client=CLIENT_DETAILS, label=f"market {slug_id}")
    return root(body, "geo", label=f"market {slug_id}")


def fetch_nearby(slug_id, city, state_code, limit=12):
    body = graphql("NearbyLocations", NEARBY_QUERY,
                   {"slugId": slug_id, "city": city, "stateCode": state_code, "limit": limit},
                   client=CLIENT_DETAILS, label=f"nearby {slug_id}")
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, dict) or (data.get("geo") is None and data.get("customer_nearby_locations") is None):
        root(body, "geo", label=f"nearby {slug_id}")   # raises with the gateway's message
        return {}
    return data


def fetch_mortgage_trends(state, rate_type):
    body = graphql("MortgageRateTrends", MORTGAGE_QUERY,
                   {"input": {"include_all_data": True, "state": state, "rate_type": rate_type}},
                   client=CLIENT_DEFAULT, label=f"mortgage {state}")
    return root(body, "mortgage_rate_trends") or {}


def fetch_schools(criteria, limit, offset):
    body = graphql("SchoolSearch", SCHOOLS_QUERY, {"query": criteria, "limit": limit, "offset": offset},
                   client=CLIENT_SEARCH, label="schools")
    return root(body, "school_search") or {}
