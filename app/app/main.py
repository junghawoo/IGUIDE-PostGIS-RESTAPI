import os
from typing import Dict, List, Tuple

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse
from starlette.middleware.gzip import GZipMiddleware
import psycopg
from psycopg.rows import dict_row
from psycopg import sql

app = FastAPI(title="Geo Risk API", version="0.4.1")
app.add_middleware(GZipMiddleware, minimum_size=1024)  # gzip responses ≥1KB

# ---- DB config ----
DB_HOST = os.getenv("DB_HOST", os.getenv("PGHOST", "postgres"))
DB_PORT = int(os.getenv("DB_PORT", os.getenv("PGPORT", "5432")))
DB_NAME = os.getenv("POSTGRES_DB", os.getenv("PGDATABASE", "geodb_largest"))
DB_USER = os.getenv("POSTGRES_USER", os.getenv("PGUSER", "geo-iguide"))
DB_PASS = os.getenv("POSTGRES_PASSWORD", os.getenv("PGPASSWORD", "postgres-iguide"))

DB_SCHEMA = os.getenv("DB_SCHEMA", "gis")
# expects: damnumber, dam_name, geom
ZONE_TABLE = os.getenv("DB_ZONE_TABLE", "inundation_zones_largest")
# ---- Metrics cache config ----
METRICS_CACHE_ENABLED = os.getenv("METRICS_CACHE", "true").lower() in {"1", "true", "yes"}
METRICS_CACHE_TABLE   = os.getenv("METRICS_CACHE_TABLE", "risk_metrics_cache")


from typing import Optional

def _cache_exists(cur) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema=%s AND table_name=%s
        """,
        (DB_SCHEMA, METRICS_CACHE_TABLE),
    )
    return cur.fetchone() is not None

def _cache_measure_srid(cur) -> int | None:
    q = sql.SQL("SELECT measure_srid FROM {}.{} LIMIT 1").format(
        sql.Identifier(DB_SCHEMA), sql.Identifier(METRICS_CACHE_TABLE)
    )
    cur.execute(q)
    r = cur.fetchone()  # dict_row
    return None if not r or r["measure_srid"] is None else int(r["measure_srid"])


def _metric_columns_for_targets(target_list: List[str]) -> List[str]:
    cols = []
    for t in target_list:
        gt = TARGET_GEOMTYPE[t]
        if gt == "point":
            cols.append(f"{t}_count")
        elif gt == "line":
            cols.append(f"{t}_length_m")
        elif gt == "polygon":
            cols.append(f"{t}_area_m2")
    return cols

def get_conn():
    return psycopg.connect(
        host=DB_HOST, port=DB_PORT, dbname=DB_NAME, user=DB_USER, password=DB_PASS
    )

# Allowed vulnerability targets (slug -> base table name in schema)
BASE_TARGETS: Dict[str, str] = {
    "power_plants": "power_plants",
    "railroads": "railroads",
    "transportation": "transportation",
    "aviation": "aviation",
    "hospitals": "hospitals",
    "hazardous_waste": "hazardous_waste",
    "ng_pipelines": "ng_pipelines",
    "wwtp": "wwtp",
    "svi_tracts": "svi_tracts",
    "gap_status": "gap_status",
}

def fq(schema: str, table: str) -> sql.Composed:
    return sql.SQL("{}.{}").format(sql.Identifier(schema), sql.Identifier(table))

@app.get("/healthz", response_class=JSONResponse)
def healthz():
    return {"status": "ok"}

@app.get("/risk/targets", response_class=JSONResponse)
def list_targets():
    return {"targets": sorted(BASE_TARGETS.keys())}

def _ensure_zone_exists(cur, damnumber: str | None = None, dam_name: str | None = None) -> None:
    if damnumber:
        cur.execute(
            sql.SQL("SELECT 1 FROM {} WHERE damnumber = %s LIMIT 1").format(
                fq(DB_SCHEMA, ZONE_TABLE)
            ),
            (damnumber,),
        )
    else:
        cur.execute(
            sql.SQL("SELECT 1 FROM {} WHERE dam_name = %s LIMIT 1").format(
                fq(DB_SCHEMA, ZONE_TABLE)
            ),
            (dam_name,),
        )
    if cur.fetchone() is None:
        raise HTTPException(status_code=404, detail="Dam not found in inundation zones")

def _build_counts_sql(target_list: List[str]) -> sql.Composed:
    parts: List[sql.Composed] = []
    for t in target_list:
        tbl = BASE_TARGETS[t]
        parts.append(
            sql.SQL(
                "(SELECT COUNT(*) FROM {tbl} g JOIN base b ON ST_Intersects(g.geom, b.geom)) AS {alias}"
            ).format(
                tbl=fq(DB_SCHEMA, tbl),
                alias=sql.Identifier(t),
            )
        )
    return sql.SQL(", ").join(parts)

@app.get("/risk/summary", response_class=JSONResponse)
def risk_summary(
    damnumber: str | None = Query(default=None),
    dam_name: str | None = Query(default=None),
    targets: str = Query(..., description="Comma-separated targets"),
    clip: bool = Query(default=False, description="Counts ignore clipping; kept for symmetry"),
):
    """Counts per requested target within the largest zone of the specified dam."""
    target_list = [t.strip() for t in targets.split(",") if t.strip()]
    if not target_list:
        raise HTTPException(status_code=400, detail="No targets specified")
    for t in target_list:
        if t not in BASE_TARGETS:
            raise HTTPException(status_code=400, detail=f"Unknown target: {t}")
    if not damnumber and not dam_name:
        raise HTTPException(status_code=400, detail="Provide damnumber or dam_name")

    counts_sql = _build_counts_sql(target_list)

    query = sql.SQL("""
        WITH zone AS (
          SELECT damnumber, dam_name, geom
          FROM {zone_tbl}
          WHERE {dam_filter}
          LIMIT 1
        ),
        base AS (
          SELECT
            z.damnumber,
            COALESCE(z.dam_name, dn.dam_name) AS dam_name,
            z.geom
          FROM zone z
          LEFT JOIN {nid_tbl} dn
            ON dn.damnumber = z.damnumber
        )
        SELECT
          b.damnumber,
          b.dam_name,
          {counts_sql}
        FROM base b
    """).format(
        zone_tbl=fq(DB_SCHEMA, ZONE_TABLE),
        nid_tbl=fq(DB_SCHEMA, "dams_nid"),
        dam_filter=sql.SQL("damnumber = %s") if damnumber else sql.SQL("dam_name = %s"),
        counts_sql=counts_sql,
    )

    param = (damnumber,) if damnumber else (dam_name,)
    try:
        with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            _ensure_zone_exists(cur, damnumber=damnumber, dam_name=dam_name)
            cur.execute(query, param)
            row = cur.fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Dam not found")
            counts = {t: int(row[t]) for t in target_list}
            return {"damnumber": row["damnumber"], "dam_name": row["dam_name"], "counts": counts}
    except psycopg.Error as e:
        # Avoid AttributeError when e.pgerror is missing
        msg = getattr(e, "pgerror", None) or str(e)
        raise HTTPException(status_code=500, detail=f"DB error: {msg}")

def _parse_bbox(bbox: str) -> Tuple[float, float, float, float]:
    try:
        parts = [float(x) for x in bbox.split(",")]
        if len(parts) != 4:
            raise ValueError
        minx, miny, maxx, maxy = parts
        if minx >= maxx or miny >= maxy:
            raise ValueError
        return minx, miny, maxx, maxy
    except Exception:
        raise HTTPException(status_code=400, detail="bbox must be 'minx,miny,maxx,maxy' in EPSG:4326")

@app.get("/risk/features/{target}.geojson", response_class=JSONResponse)
def features_geojson(
    target: str,
    damnumber: str | None = Query(default=None),
    dam_name: str | None = Query(default=None),
    clip: bool = Query(default=True),
    limit: int = Query(default=500, ge=1, le=5000),
    offset: int = Query(default=0, ge=0),
    bbox: str | None = Query(default=None, description="minx,miny,maxx,maxy in EPSG:4326"),
    simplify_m: float | None = Query(default=None, ge=0, description="Simplify tolerance in meters"),
):
    """
    Return features intersecting a dam’s zone.
    - If clip=true, geometries are clipped to the zone.
    - Optional bbox further filters features via envelope in EPSG:4326.
    - Optional simplify_m simplifies output geometry (meters, via 3857 transform).
    """
    if target not in BASE_TARGETS:
        raise HTTPException(status_code=400, detail=f"Unknown target: {target}")
    if not damnumber and not dam_name:
        raise HTTPException(status_code=400, detail="Provide damnumber or dam_name")

    tbl = BASE_TARGETS[target]
    bbox_filter = sql.SQL("TRUE")
    if bbox:
        minx, miny, maxx, maxy = _parse_bbox(bbox)
        bbox_filter = sql.SQL(
            "g.geom && ST_MakeEnvelope(%s,%s,%s,%s,4326)"
        )

    # Geometry expressions
    g = sql.SQL("ST_MakeValid(g.geom)")
    z = sql.SQL("ST_MakeValid(z.geom)")
    geom_base = sql.SQL("ST_Intersection({g},{z})").format(g=g, z=z) if clip else g

    if simplify_m and simplify_m > 0:
        # simplify in meters in 3857, then back to 4326
        geom_out = sql.SQL(
            "ST_Transform(ST_SimplifyPreserveTopology(ST_Transform({geom}, 3857), %s), 4326)"
        ).format(geom=geom_base)
        simplify_param = (simplify_m,)
    else:
        geom_out = geom_base
        simplify_param = tuple()

    where_cond = sql.SQL("ST_Intersects({g},{z})").format(g=g, z=z)
    if clip:
        where_cond = sql.SQL("{w} AND NOT ST_IsEmpty(ST_Intersection({g},{z}))").format(
            w=where_cond, g=g, z=z
        )

    query = sql.SQL("""
        WITH zone AS (
          SELECT damnumber, dam_name, geom
          FROM {zone_tbl}
          WHERE {dam_filter}
          LIMIT 1
        ),
        base AS (
          SELECT
            z.damnumber,
            COALESCE(z.dam_name, dn.dam_name) AS dam_name,
            z.geom
          FROM zone z
          LEFT JOIN {nid_tbl} dn
            ON dn.damnumber = z.damnumber
        ),
        hits AS (
          SELECT
            {geom_out} AS geom_out,
            g.*
          FROM {target_tbl} g
          JOIN base z ON {where_cond}
          WHERE {bbox_filter}
          LIMIT %s OFFSET %s
        )
        SELECT json_build_object(
          'type','FeatureCollection',
          'features', COALESCE(json_agg(
            json_build_object(
              'type','Feature',
              'geometry', ST_AsGeoJSON(COALESCE(h.geom_out, h.geom))::json,
              'properties', to_jsonb(h) - 'geom' - 'geom_out'
            )
          ), '[]'::json)
        ) AS fc
        FROM hits h;
    """).format(
        zone_tbl=fq(DB_SCHEMA, ZONE_TABLE),
        nid_tbl=fq(DB_SCHEMA, "dams_nid"),
        dam_filter=sql.SQL("damnumber = %s") if damnumber else sql.SQL("dam_name = %s"),
        target_tbl=fq(DB_SCHEMA, tbl),
        geom_out=geom_out,
        where_cond=where_cond,
        bbox_filter=bbox_filter,
    )

    params: Tuple = ((damnumber,) if damnumber else (dam_name,))
    if bbox:
        params += (minx, miny, maxx, maxy)
    if simplify_param:
        params += simplify_param
    params += (limit, offset)

    try:
        with get_conn() as conn, conn.cursor() as cur:
            _ensure_zone_exists(cur, damnumber=damnumber, dam_name=dam_name)
        with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
            cur.execute(query, params)
            row = cur.fetchone()
            return JSONResponse(content=row["fc"])
    except psycopg.Error as e:
        msg = getattr(e, "pgerror", None) or str(e)
        raise HTTPException(status_code=500, detail=f"DB error: {msg}")

@app.get("/risk/summary/top", response_class=JSONResponse)
def risk_top(
    target: str = Query(..., description="One of /risk/targets"),
    n: int = Query(default=20, ge=1, le=500),
):
    """Top-N dams by count of a single target intersecting their largest zone."""
    if target not in BASE_TARGETS:
        raise HTTPException(status_code=400, detail=f"Unknown target: {target}")
    tbl = BASE_TARGETS[target]

    q = sql.SQL("""
      WITH counts AS (
        SELECT
          z.damnumber,
          COALESCE(z.dam_name, dn.dam_name) AS dam_name,
          COUNT(*)::int AS count
        FROM {zone_tbl} z
        LEFT JOIN {nid_tbl} dn ON dn.damnumber = z.damnumber
        JOIN {target_tbl} g ON ST_Intersects(g.geom, z.geom)
        GROUP BY
          z.damnumber,
          COALESCE(z.dam_name, dn.dam_name)
      )
      SELECT damnumber, dam_name, count
      FROM counts
      ORDER BY count DESC, damnumber
      LIMIT %s
    """).format(
        zone_tbl=fq(DB_SCHEMA, ZONE_TABLE),
        nid_tbl=fq(DB_SCHEMA, "dams_nid"),
        target_tbl=fq(DB_SCHEMA, tbl),
    )

    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(q, (n,))
        rows = cur.fetchall()
        return {"target": target, "top": rows}

@app.get("/risk/zone.geojson", response_class=JSONResponse)
def zone_geojson(damnumber: str | None = None, dam_name: str | None = None):
    if not damnumber and not dam_name:
        raise HTTPException(status_code=400, detail="Provide damnumber or dam_name")
    q = sql.SQL("""
      SELECT ST_AsGeoJSON(geom)::json AS g
      FROM {zone_tbl}
      WHERE {dam_filter}
      LIMIT 1
    """).format(
      zone_tbl=fq(DB_SCHEMA, ZONE_TABLE),
      dam_filter=sql.SQL("damnumber = %s") if damnumber else sql.SQL("dam_name = %s"),
    )
    p = (damnumber,) if damnumber else (dam_name,)
    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        cur.execute(q, p)
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Zone not found")
        return {
            "type": "FeatureCollection",
            "features": [{"type": "Feature", "geometry": row["g"], "properties": {}}]
        }


POINT = {"aviation", "hazardous_waste", "hospitals", "power_plants", "wwtp"}
LINE  = {"ng_pipelines", "railroads", "transportation"}
POLY  = {"gap_status", "svi_tracts"}

def _metrics_from_cache(cur, damnumber: str | None, target_list: list[str]) -> dict:
    # Build column list per target (count / length_m / area_m2)
    pairs: list[tuple[str, str]] = []
    for t in target_list:
        if t in POINT:
            pairs.append((f"{t}_count", t))
        elif t in LINE:
            pairs.append((f"{t}_length_m", t))
        elif t in POLY:
            pairs.append((f"{t}_area_m2", t))
        else:
            raise HTTPException(status_code=400, detail=f"Unknown target: {t}")

    cols_sql = sql.SQL(", ").join(
        sql.SQL("{} AS {}").format(sql.Identifier(col), sql.Identifier(alias))
        for col, alias in pairs
    ) if pairs else sql.SQL("")

    where_sql = sql.SQL("TRUE") if damnumber in (None, "", "all") else sql.SQL("damnumber = %s")
    params = tuple() if damnumber in (None, "", "all") else (damnumber,)

    q = sql.SQL("""
        SELECT damnumber, dam_name{comma}{cols}
        FROM {sch}.{tbl}
        WHERE {where}
    """).format(
        sch=sql.Identifier(DB_SCHEMA),
        tbl=sql.Identifier(METRICS_CACHE_TABLE),
        where=where_sql,
        comma=sql.SQL(", ") if cols_sql.as_string(cur.connection) else sql.SQL(""),
        cols=cols_sql,
    )

    cur.execute(q, params if params else None)
    rows = cur.fetchall()  # list[dict] (dict_row)
    if not rows:
        raise HTTPException(status_code=404, detail="No rows in cache for selection")

    # If a single damnumber was requested, return a single object; otherwise list.
    if damnumber not in (None, "", "all"):
        r = rows[0]
        out = {"damnumber": r["damnumber"], "dam_name": r["dam_name"], "metrics": {}}
        for _, alias in pairs:
            out["metrics"][alias] = r[alias]
        return out
    else:
        # Bulk: return an array of dam summaries (damnumber, dam_name, + requested metrics)
        items = []
        for r in rows:
            it = {"damnumber": r["damnumber"], "dam_name": r["dam_name"]}
            for _, alias in pairs:
                it[alias] = r[alias]
            items.append(it)
        return {"items": items}

@app.get("/risk/metrics", response_class=JSONResponse)
def risk_metrics(
    damnumber: str | None = Query(default=None, description="'UTxxxxx' or 'all'"),
    targets: str = Query(..., description="'all' or comma-separated targets"),
    precomputed: bool = Query(default=True, description="Use cached metrics when available"),
):
    target_list = (
        sorted(POINT | LINE | POLY) if targets.strip().lower() == "all"
        else [t.strip() for t in targets.split(",") if t.strip()]
    )
    for t in target_list:
        if t not in (POINT | LINE | POLY):
            raise HTTPException(status_code=400, detail=f"Unknown target: {t}")

    with get_conn() as conn, conn.cursor(row_factory=dict_row) as cur:
        if damnumber not in ("all", None, ""):
            _ensure_zone_exists(cur, damnumber=damnumber)

        if precomputed and METRICS_CACHE_ENABLED:
            return _metrics_from_cache(cur, damnumber, target_list)

        # ... (your on-the-fly computation branch stays as-is)
