
import os, requests, pprint

BASE = os.getenv("GEOAPI_BASE", "http://localhost:8080")

def get(path, **params):
    r = requests.get(BASE + path, params=params, timeout=60)
    try:
        r.raise_for_status()
    except Exception:
        print("URL:", r.url)
        print("Status:", r.status_code)
        print(r.text[:500])
        raise
    try:
        return r.json()
    except Exception:
        print(r.text[:500])
        raise

if __name__ == "__main__":
    print(get("/healthz"))
    print(get("/risk/targets"))
    # sample summary
    print(get("/risk/summary", damnumber="UT00259", targets="power_plants,railroads", clip=False))
    # top-N
    print(get("/risk/summary/top", target="railroads", n=10))
    # features (first 5)
    fc = get("/risk/features/railroads.geojson", damnumber="UT00259", clip=False, limit=5)
    print("features:", len(fc.get("features", [])))
