# Geo-Risk — Largest Scenario (Kubernetes + Helm)

This deploys PostGIS + import Job + FastAPI for geospatial risk queries.



## Prepare data
Mount your FileGDB at the path `/data/Utah Inundation Profiles.gdb` via the `geodata` PVC
(see `templates/geodata-pvc.yaml`). You can bind that PVC to a hostPath, NFS, or cloud disk.

## Build & push the API image
```bash
export IMAGE_REPO=ghcr.io/iguide-postgis/geoapi
docker build -t $IMAGE_REPO:latest ./app
docker push $IMAGE_REPO:latest
```



## Local Dev (macOS Docker Desktop)

1) Create a **PV** that points to your Mac folder (parent of the `.gdb`):
```bash
make pv-apply
```
(Uses `ops/geodata-pv.docker-desktop.yaml` with your hostPath.)

2) Create DB secret (only once):
```bash
kubectl create ns geo-risk-largest || true
kubectl -n geo-risk-largest create secret generic pg-secret \
  --from-literal=POSTGRES_PASSWORD='your-db-pass' \
  --from-literal=POSTGRES_USER='geo' \
  --from-literal=POSTGRES_DB='geodb_largest'
```

3) Install Helm chart (uses local overrides):
```bash
make install
```

4) Ensure **PVC geodata** becomes **Bound**:
```bash
make watch-pvc
```

5) Watch the import job:
```bash
make logs
```

6) Port-forward & test:
```bash
make pf
make api-test
```

### minikube
1) Bridge your Mac folder into the VM:
```bash
minikube mount "/Users/junghawoo/.../Utah Inundation Profiles:/mnt/geodata"
```
2) Apply PV:
```bash
kubectl apply -f ops/geodata-pv.minikube.yaml
```
3) Same Helm install as above.

## Notes
- PostGIS image defaults to `ghcr.io/iguide-postgis/postgis:16-3.4` — override via `values.yaml` or `--set`.
- PVC template supports `storageClassName`, optional `volumeName`, and optional label selector (`matchLabels`).
