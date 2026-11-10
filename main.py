"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. Params go through the same schemas the API uses, so defaults
are filled in and a property id or a realtor.com link both work.
"""
import json
import os

from realtor_com import api, schemas

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


def run(schema_cls, fn, **params):
    return fn(**schema_cls().load(params))


if __name__ == "__main__":
    # a property id or any realtor.com home link — price, photos, features, agent contacts, MLS, mortgage
    save("property_1885_carla_ridge.json",
         run(schemas.PropertySchema, api.property_details, property="2500043274"))

    # 50 homes per page — for sale, for rent or sold, with price, beds, size and 20+ more filters
    save("search_beverly_hills.json",
         run(schemas.SearchSchema, api.properties_search, location="Beverly Hills, CA"))

    # an agent id or profile link — bio, phones, office, license, MLS ids, areas served, sales
    save("agent_jason_oppenheim.json",
         run(schemas.AgentSchema, api.agent_details, agent="1170840"))
