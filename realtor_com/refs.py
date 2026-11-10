"""Reference resolvers + the vocabulary tables the /realtor-com/* schemas,
parsers and api share. Pure functions, no I/O.

ONE param per input (tripadvisor QueryOrIdField convention):

  property   a realtor.com property id ("8102930727"), the permalink tail
             ("M81029-30727" / "Q717000097677"), a full permalink
             ("1704-Shelbourne-Dr_Austin_TX_78752_M81029-30727") or the
             property / rental / community page link
  agent      a fulfillment id ("184731") or the agent profile link
             (/realestateagents/Knolly-Williams_Austin_TX_184731_446999691)
  location   free text ("Austin, TX", "78704", "Zilker, Austin, TX"), the
             site's own slug ("Austin_TX", "Zilker_Austin_TX") or a
             realtor.com search / apartments / agents / market page link

Identity (captured 2026-11-07):
  * property_id is the permalink tail with the letter and the dash removed:
    "M81029-30727" -> "8102930727"; new-construction communities carry a
    "Q<id>" tail ("Q717000097677"). Rentals share the id under
    /rentals/details/<permalink>. A listing_id is separate and changes when
    the home is re-listed.
  * an agent's fulfillment_id is the second-to-last "_" token of the agent
    URL (the last one is the profile number).
  * search_location.location of home_search accepts the free-text forms and
    the "City_ST" slug alike; geo(slug_id:) and the agent directory need
    the slug / "ST_City" forms, which api.py derives from the site's own
    search_suggestions.
"""
import re
from urllib.parse import unquote, urlparse

SITE = "https://www.realtor.com"
HOST = "realtor.com"

_PROPERTY_ID_RE = re.compile(r"^\d{6,15}$")
_PERMALINK_TAIL_RE = re.compile(r"(?:^|_)([MQ])(\d{5})-?(\d{5,10})$", re.I)
_LINK_TAIL_RE = re.compile(r"_([MQ])(\d{5})-?(\d{5,10})(?:[/?#]|$)", re.I)
_AGENT_LINK_RE = re.compile(r"/realestateagents/([^/?#]+)", re.I)
_AGENT_ID_RE = re.compile(r"^\d{1,12}$")
_PROFILE_ID_RE = re.compile(r"^[0-9a-f]{24}$", re.I)
_ZIP_RE = re.compile(r"^\d{5}$")
_LOCATION_PATHS = ("/realestateandhomes-search/", "/apartments/", "/realestateagents/",
                   "/realestateandhomes-detail/", "/local/", "/soldhomeprices/", "/newhomes/")

# home_search `status` values (enum; pending / contingent are flags, not statuses)
SEARCH_STATUS = ("for_sale", "for_rent", "sold", "off_market", "ready_to_build")
SIMILAR_STATUS = ("for_sale", "for_rent", "sold")

# home_search `type` strings (all 13 accepted together on 2026-11-07)
PROPERTY_TYPES = (
    "single_family", "condos", "townhomes", "multi_family", "duplex_triplex", "mobile",
    "land", "farm", "apartment", "coop", "condop", "condo_townhome_rowhome_coop", "condo_townhome",
)

# our sort word -> (SearchAPISort field, direction); "relevant" = the site's order
SEARCH_SORTS = {
    "relevant": None,
    "newest": ("list_date", "desc"),
    "price_low": ("list_price", "asc"),
    "price_high": ("list_price", "desc"),
    "sold_date": ("sold_date", "desc"),
    "photo_count": ("photo_count", "desc"),
    "beds": ("beds", "desc"),
    "baths": ("baths", "desc"),
    "sqft": ("sqft", "desc"),
    "lot_size": ("lot_sqft", "desc"),
    "last_updated": ("last_update_date", "desc"),
    "year_built": ("year_built", "desc"),
    "price_reduced": ("price_reduced_date", "desc"),
}

# agents/search sort -> SearchAgentInput.sort enum
AGENT_SORTS = {
    "relevant": "RELEVANT_AGENTS",
    "recent_activity": "MOST_RECENT_ACTIVITY",
    "most_sales": "MOST_SALES",
    "ratings": "RATINGS_REVIEWS",
    "recommendations": "TESTIMONIALS_RECOMMENDATIONS",
}
AGENT_TYPES = {"buyer": "BUYER", "seller": "SELLER"}
MORTGAGE_RATE_TYPES = {"purchase": "PURCHASE", "refinance": "REFINANCE"}

US_STATES = frozenset("""
AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR
PA RI SC SD TN TX UT VT VA WA WV WI WY
""".split())


def _is_link(value):
    return value.startswith(("http://", "https://", "//", "www.realtor.com", "realtor.com"))


def _parse_link(value):
    """A realtor.com link -> its unquoted path, or raise ValueError."""
    url = value
    if url.startswith("//"):
        url = "https:" + url
    elif not url.startswith(("http://", "https://")):
        url = "https://" + url
    parts = urlparse(url)
    host = (parts.hostname or "").lower()
    if not (host == HOST or host.endswith("." + HOST)):
        raise ValueError("Must be a realtor.com link.")
    return unquote(parts.path or "/")


# ---- properties ------------------------------------------------------------------

def _id_from_tail(letter, head, tail):
    return head + tail


def resolve_property(value):
    """property id / permalink tail / permalink / page link -> the property_id."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Must not be empty.")
    if _PROPERTY_ID_RE.match(value):
        return value
    if _is_link(value):
        path = _parse_link(value)
        match = _LINK_TAIL_RE.search(path)
        if not match:
            raise ValueError("Must be a realtor.com property link "
                             "(https://www.realtor.com/realestateandhomes-detail/<address>_M12345-67890).")
        return _id_from_tail(*match.groups())
    match = _PERMALINK_TAIL_RE.search(value)
    if match and "/" not in value:
        return _id_from_tail(*match.groups())
    raise ValueError("Must be a realtor.com property id (8102930727), the permalink tail "
                     "(M81029-30727) or the property's realtor.com link.")


def property_link(record):
    """The canonical page link for a parsed record (status decides the section)."""
    permalink = (record or {}).get("permalink")
    if not permalink:
        return None
    if (record or {}).get("status") == "for_rent":
        return f"{SITE}/rentals/details/{permalink}"
    return f"{SITE}/realestateandhomes-detail/{permalink}"


# ---- agents ----------------------------------------------------------------------

def resolve_agent(value):
    """fulfillment id or an agent profile link -> the fulfillment id."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Must not be empty.")
    if _AGENT_ID_RE.match(value):
        return value
    if _PROFILE_ID_RE.match(value):
        return value.lower()
    if _is_link(value) or "/realestateagents/" in value:
        path = _parse_link(value) if _is_link(value) else value
        match = _AGENT_LINK_RE.search(path)
        slug = match.group(1) if match else ""
        tokens = slug.split("_")
        # <Name>_<City>_<ST>_<fulfillment_id>_<profile#> ; older links end at the id;
        # the profile's own 24-hex id also names an agent
        if len(tokens) == 1 and _PROFILE_ID_RE.match(slug):
            return slug.lower()
        digits = [t for t in tokens if t.isdigit()]
        if len(digits) >= 2 and tokens[-1].isdigit() and tokens[-2].isdigit():
            return tokens[-2]
        if len(digits) == 1 and tokens[-1].isdigit() and len(tokens) > 1:
            return tokens[-1]
        raise ValueError("Must be a realtor.com agent profile link "
                         "(https://www.realtor.com/realestateagents/<Name>_<City>_<ST>_<id>_<profile>).")
    raise ValueError("Must be an agent id (184731) or the agent's realtor.com profile link.")


def agent_link(agent):
    """The agent's profile link from a search / branding record (fullname,
    served city / state, fulfillment_id, id)."""
    fid = (agent or {}).get("fulfillment_id")
    if not fid:
        return None
    name = "-".join(((agent.get("name") or agent.get("fullname") or "agent").split()))
    city = "-".join((agent.get("city") or "").split()) if agent.get("city") else None
    state = agent.get("state_code")
    parts = [name] + ([city] if city else []) + ([state] if state else []) + [str(fid)]
    if agent.get("profile_id"):
        parts.append(str(agent["profile_id"]))
    return f"{SITE}/realestateagents/{'_'.join(parts)}"


# ---- locations -------------------------------------------------------------------

def slug_to_text(slug):
    """'Zilker_Austin_TX' -> 'Zilker, Austin, TX'; '78704' stays; hyphens are
    the site's spaces ('San-Antonio_TX' -> 'San Antonio, TX')."""
    if _ZIP_RE.match(slug):
        return slug
    return ", ".join(part.replace("-", " ") for part in slug.split("_") if part)


def resolve_location(value):
    """Free text / site slug / realtor.com page link -> the location text
    home_search's search_location and search_suggestions accept."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Must not be empty.")
    if _is_link(value):
        path = _parse_link(value).rstrip("/")
        for prefix in _LOCATION_PATHS:
            if path.startswith(prefix):
                rest = path[len(prefix):]
                if prefix == "/local/":
                    # /local/market/texas/travis-county/austin[/78752]
                    segments = [s for s in rest.split("/") if s]
                    if len(segments) >= 2 and segments[0] in ("market", "housing-market"):
                        segments = segments[1:]
                    if segments and _ZIP_RE.match(segments[-1]):
                        return segments[-1]
                    if len(segments) >= 3:
                        return f"{segments[-1].replace('-', ' ').title()}, {segments[0].replace('-', ' ').title()}"
                    raise ValueError("Must be a realtor.com market link (/local/market/<state>/<county>/<city>).")
                slug = rest.split("/")[0]
                if prefix == "/realestateandhomes-detail/":
                    raise ValueError("That is a property link; give a city, ZIP, neighborhood or search link.")
                if not slug or slug.lower() in ("pg-1",):
                    break
                if prefix == "/realestateagents/" and (slug.split("_")[-1].isdigit() or _PROFILE_ID_RE.match(slug)):
                    raise ValueError("That is an agent profile link; give a city / ZIP agents directory link.")
                return slug_to_text(slug)
        raise ValueError("Must be a realtor.com search link (https://www.realtor.com/realestateandhomes-search/"
                         "Austin_TX), a place name or a ZIP code.")
    if "_" in value and " " not in value and "," not in value:
        return slug_to_text(value)
    return value


def location_slug(text):
    """'Austin, TX' -> 'Austin_TX' (the site's slug form; ZIPs unchanged)."""
    if _ZIP_RE.match(text):
        return text
    return "_".join("-".join(part.split()) for part in text.split(",") if part.strip())


def is_zip(text):
    return bool(_ZIP_RE.match((text or "").strip()))
