LAYER_MAP = {
    "svi_tracts": {"table": "gis.svi_tracts", "geom_type": "POLYGON", "id_col": "objectid"},
    "aviation": {"table": "gis.aviation", "geom_type": "POLYGON", "id_col": "objectid"},
    "gap_status": {"table": "gis.gap_status", "geom_type": "POLYGON", "id_col": "objectid"},
    "hazardous_waste": {"table": "gis.hazardous_waste", "geom_type": "POINT", "id_col": "objectid"},
    "hospitals": {"table": "gis.hospitals", "geom_type": "POLYGON", "id_col": "objectid"},
    "ng_pipelines": {"table": "gis.ng_pipelines", "geom_type": "LINESTRING", "id_col": "objectid"},
    "power_plants": {"table": "gis.power_plants", "geom_type": "POINT", "id_col": "objectid"},
    "railroads": {"table": "gis.railroads", "geom_type": "LINESTRING", "id_col": "objectid"},
    "transportation": {"table": "gis.transportation", "geom_type": "LINESTRING", "id_col": "objectid"},
    "wwtp": {"table": "gis.wwtp", "geom_type": "POINT", "id_col": "objectid"}
}
INUNDATION_LARGEST_VIEW = "gis.inundation_zones_largest"
