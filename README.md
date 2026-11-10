# 🏡 Realtor Com Scraper

Realtor Com Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Realtor.com data for free.

## ✨ What Can I Get?

- 🏡 **Full details on homes in all 50 states** — price, photos, features, agent emails & phones, MLS, price & tax history
- 🔍 **For-sale, rental & sold search with 20+ filters** — any city, ZIP, neighborhood, radius or map polygon, up to 10,000 homes per search
- 💰 **3 home value estimates plus a 12-month forecast** — schools, climate risk, views & saves, neighborhoods and similar homes
- 🤝 **Agents, reviews & local markets** — agent profiles, every review, sold deals, median prices, market hotness & daily mortgage rates

## 🎥 Example: A Full Realtor.com Home

```json
{
  "property_id": "2500043274",
  "link": "https://www.realtor.com/realestateandhomes-detail/1885-Carla-Rdg_Beverly-Hills_CA_90210_M25000-43274",
  "status": "for_sale",
  "price": 14995000,
  "price_per_sqft": 2307,
  "beds": 5,
  "baths": 7,
  "sqft": 6500,
  "lot_sqft": 19702,
  "year_built": 1970,
  "style": "Mid-Century",
  "address": { "line": "1885 Carla Rdg", "city": "Beverly Hills", "state_code": "CA", "postal_code": "90210", "latitude": 34.109297, "longitude": -118.393952 },
  "description": "In Trousdale Estates, there is Carla Ridge and then there is the Carla Ridge Rim. For those who know Trousdale, no explanation is necessary...",
  "photo_count": 45,
  "tags": ["swimming_pool", "spa_or_hot_tub", "hill_or_mountain_view", "detached_guest_house"],
  "advertisers": [
    { "id": "756313", "name": "Josh Flagg", "type": "seller", "email": "josh@joshflagg.com", "license": "01470467", "office": { "name": "COMPASS" } }
  ],
  "mls": { "id": "WECA", "name": "TheMLSCLAW", "listing_id": "26985261" },
  "last_sold_price": 6450000,
  "last_sold_date": "2017-02-13",
  "estimate": 9273190,
  "estimate_source": "Quantarium",
  "mortgage": { "monthly_payment": 99650, "loan_amount": 11996000, "down_payment": 2999000 },
  "currency": "USD"
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Realtor.com Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/realtor-com-scraper
cd realtor-com-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/properties/details?property=2500043274"
```

```json
{
  "property_id": "2500043274",
  "link": "https://www.realtor.com/realestateandhomes-detail/1885-Carla-Rdg_Beverly-Hills_CA_90210_M25000-43274",
  "status": "for_sale",
  "price": 14995000,
  "beds": 5,
  "baths": 7,
  "sqft": 6500,
  "year_built": 1970,
  "style": "Mid-Century",
  "address": { "line": "1885 Carla Rdg", "city": "Beverly Hills", "state_code": "CA", "postal_code": "90210" },
  "photo_count": 45,
  "advertisers": [
    { "id": "756313", "name": "Josh Flagg", "type": "seller", "email": "josh@joshflagg.com", "office": { "name": "COMPASS" } }
  ],
  "mls": { "id": "WECA", "listing_id": "26985261" },
  "estimate": 9273190,
  "currency": "USD"
}
```

All 25 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

25 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| Property Details | `/properties/details` | Everything about one home: price, photos, features, agent contacts, MLS |
| Search Locations | `/locations/search` | Cities, ZIPs, neighborhoods, schools and addresses with their slugs |
| Search Properties · Nearby · Polygon | `/properties/search` · `/properties/search-nearby` · `/properties/search-polygon` | Homes for sale, for rent or sold with 20+ filters |
| Property by MLS Number | `/properties/by-mls` | Any listing by its MLS number |
| Properties Batch | `/properties/batch` | Up to 20 homes in one call |
| Price & Tax History | `/properties/history` | Every listing, price change and sale, plus yearly property taxes |
| Home Value Estimates | `/properties/estimates` | 3 estimates with ranges, a 12-month forecast and value history |
| Property Schools | `/properties/schools` | Assigned and nearby schools with ratings, grades and distance |
| Climate Risk | `/properties/environment` | Flood, wildfire, heat, wind, air and noise risk for any home |
| Property Popularity | `/properties/popularity` | Views, saves, clicks, shares and leads over 30 days |
| Property Neighborhoods | `/properties/neighborhoods` | The home's neighborhoods with GeoJSON boundaries |
| Similar Homes | `/properties/similar` | Comparable homes for sale, for rent or sold |
| New Home Communities | `/communities/search` | New-construction communities with builder and price range |
| Search Agents | `/agents/search` | Agents in any city or ZIP with ratings, sales and brokerage |
| Agent Details | `/agents/details` | Bio, phones, office, license, MLS IDs and areas served |
| Agent Reviews · Recommendations | `/agents/reviews` · `/agents/recommendations` | Every review with 4 sub-ratings, plus every testimonial |
| Agent Listings · Sold Homes | `/agents/listings` · `/agents/sold` | An agent's active listings and every closed sale |
| Market Stats · Nearby Markets | `/markets/stats` · `/markets/nearby` | Median list price, rent, days on market and market hotness |
| Search Schools | `/schools/search` | Every school in a city or ZIP with ratings |
| Mortgage Rates | `/mortgage/rates` | Daily fixed, ARM, FHA, VA and jumbo rates for any state |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-realtor-com-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-realtor-com-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-realtor-com-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/properties/search",
    params={"location": "Beverly Hills, CA", "min_price": 5000000},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Realtor Com Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://www.omkar.cloud/l/realtor-com-scraper-github-whatsapp)

[![Ask Us by Email about Realtor Com Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Realtor%20Com%20Scraper%20API&body=I%20need%20help%20using%20the%20Realtor%20Com%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**AliExpress Scraper**](https://www.omkar.cloud/tools/aliexpress-scraper-api) — live product details, SKU variants, stock & shipping
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities
- [**Etsy Scraper**](https://www.omkar.cloud/tools/etsy-scraper) — Etsy products: prices, discounts, shops & variations

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/realtor-com-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/realtor-com-scraper)
