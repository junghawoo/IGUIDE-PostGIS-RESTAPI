# Geo-Risk — Largest Scenario (Kubernetes + Helm)

This package deploys:
- PostGIS with database **geodb_largest**
- Import Job that loads 12 selected layers from a FileGDB
- FastAPI with endpoints that use the **largest inundation zone per damnumber**
- Ingress, HPA, NetworkPolicy
- A separate PVC `geodata` to mount your `.gdb` directory for the import Job

## Prepare data
Mount your FileGDB at the path `/data/Utah Inundation Profiles/Utah Inundation Profiles.gdb` via the `geodata` PVC
(see `templates/geodata-pvc.yaml`). You can bind that PVC to a hostPath, NFS, or cloud disk.

## Build & push the API image

This builds and push the built image to the repo.
Users/researchers do not need to follow these steps.
```bash
export IMAGE_REPO=ghcr.io/iguide-postgis/geoapi
docker build -t $IMAGE_REPO:latest ./app
docker push $IMAGE_REPO:latest
```

## Create the PV that points to your Mac folder (this is the “teaching” step):

```bash
kubectl apply -f geodata-pv.yaml

# Local dev (Docker Desktop on macOS)
make pv-apply                 # 0) create hostPath PV that points to your Mac folder
helm upgrade --install geo-risk-largest ./chart/geo-risk-largest \
  -f geodata-values.yaml \
  --set image.repository=ghcr.io/yourorg/geoapi \
  --set image.tag=latest \
  --set postgres.existingSecret=pg-secret \
  --set ingress.host='api-largest.example.org'

make watch-pvc                # wait until PVC 'geodata' = Bound (to geodata-pv)
kubectl -n geo-risk-largest logs job/geodata-import-largest -f
```

## Install
```bash
helm upgrade --install geo-risk-largest ./chart/geo-risk-largest   --set image.repository="$IMAGE_REPO"   --set image.tag=latest   --set postgres.password='supersecret'   --set ingress.host='api-largest.example.org'
```
or use the secret:


## Precreate a Secret and reference it (recommended)
Keep values.yaml with placeholders; don’t put any secrets in git.

```bash

# Create the secret in the cluster (not in git)
kubectl -n geo-risk-largest create secret generic pg-secret \
  --from-literal=POSTGRES_PASSWORD='really-strong-password' \
  --from-literal=POSTGRES_USER='geo' \
  --from-literal=POSTGRES_DB='geodb_largest'
```
and then deploy telling the chart to use that secret:
```bash 
helm upgrade --install geo-risk-largest ./chart/geo-risk-largest \
  -f geodata-values.yaml \
  --set postgres.existingSecret=pg-secret
```
## Import job & precomputed cache

This chart runs a post-install/upgrade Job `geodata-import-largest` that:
- Mounts your `geodata` PVC at `/data`
- Imports layers from the FileGDB at `importer.gdbPath`
- Builds `gis.inundation_zones_largest` and creates/fills `gis.risk_metrics_cache` with the columns the API expects

See `vm-values.yaml` for a working NodePort config (30080).  
`ops/geodata-pv-pvc.yaml` contains a hostPath example for `/media/volume/aging-dams-data/geodata`.


# Upgrade and keep hooks
```bash
helm upgrade --install geo-risk-largest ./chart/geo-risk-largest \
  -n geo-risk-largest -f geodata-values.local.yaml \
  --set image.repository=geoapi \
  --set image.tag=devfix \
  --set image.pullPolicy=IfNotPresent \
  --set ingress.host='api-largest.local' \
  --wait --timeout 30m
```
# If it fails, get logs right away:
```bash
kubectl -n geo-risk-largest get jobs,pods | grep geodata-import-largest
kubectl -n geo-risk-largest logs job/$(kubectl -n geo-risk-largest get jobs -o name | grep geodata-import-largest | tail -1 | cut -d/ -f2) -f
```

## Run the import
```bash
kubectl -n geo-risk-largest logs job/geodata-import-largest -f
```


## Deploy after fix
1. Rebuild & roll your deployment:
   ```bash
   docker build -t geoapi:devfix app
   kubectl -n geo-risk-largest set image deploy/geoapi api=geoapi:devfix
   kubectl -n geo-risk-largest rollout status deploy/geoapi
   ```
2. (optional) Port-forward for localhost testing:
   ```bash
   kubectl -n geo-risk-largest port-forward svc/geoapi 8080:80
   ```



## Importing data + precomputing metrics

The chart includes a post-install/upgrade **Job** (`geodata-import-largest`) that:

- mounts your `geodata` PVC at `/data`
- imports layers from the FileGDB at `importer.gdbPath`
- creates the `gis.inundation_zones_largest` view
- builds and fills `gis.risk_metrics_cache` with all columns the API expects

### Settings

```yaml
importer:
  enabled: true
  image: ghcr.io/osgeo/gdal:ubuntu-small-3.10.1   # change if needed
  gdbPath: "/data/Utah Inundation Profiles/Utah Inundation Profiles.gdb"
```

If your cluster cannot pull from ghcr.io, point importer.image to docker.io/osgeo/gdal:ubuntu-small-3.10.1 and (if needed) create the registry secret and attach it to the namespace’s default ServiceAccount:

```bash
kubectl -n <ns> create secret docker-registry ghcr-cred \
  --docker-server=ghcr.io \
  --docker-username="$GHCR_USER" \
  --docker-password="$GHCR_PAT"

kubectl -n <ns> patch serviceaccount default \
  -p '{"imagePullSecrets":[{"name":"ghcr-cred"}]}'
```
```yaml

---

## How to test quickly

```bash
# Rerun the import job
kubectl -n geo-risk-largest delete job geodata-import-largest --ignore-not-found
helm upgrade --install geo-risk-largest ./chart/geo-risk-largest -n geo-risk-largest --wait

# Watch logs
kubectl -n geo-risk-largest logs -f job/geodata-import-largest
```










## Testing the GeoAPI from the Command Line
```bash
kubectl -n geo-risk-largest port-forward deploy/geoapi 8080:8080
curl 'http://localhost:8080/healthz'
curl 'http://localhost:8080/risk/summary?damnumber=UT00644&targets=power_plants,railroads&clip=true'
curl -sS 'http://localhost:8080/risk/summary/top?target=railroads&n=10'
curl 'http://localhost:8080/risk/features/power_plants.geojson?damnumber=UT00644&clip=true&limit=200'
curl -sS 'http://localhost:8080/risk/summary/top?target=railroads&n=20' | jq .

```

## Testing the GeoAPI in Python
```bash
python clients/geoapi_client.py
```


## Testing the GeoAPI in a Jupyter Notebook
Run [GeoRisk API Client Jupyter notebook](./clients/GeoRisk_API_Client.ipynb)


## Scenarios
This chart ships only the **largest** scenario DB. The API accepts `?scenario=` to support PMF/Rainy/Sunny later by setting env vars `DB_NAME_PMF` etc., or install one Helm release per scenario for full isolation.


## Notes
- PostGIS image defaults to `ghcr.io/iguide-postgis/postgis:16-3.4` — override via `values.yaml` or `--set`.
- PVC template supports `storageClassName`, optional `volumeName`, and optional label selector (`matchLabels`).


