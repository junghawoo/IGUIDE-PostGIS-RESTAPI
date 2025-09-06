IMAGE_REPO ?= ghcr.io/iguide-postgis/geoapi
TAG ?= latest
NAMESPACE ?= geo-risk-largest

.PHONY: build push template install uninstall pv-apply pv-delete watch-pvc logs pf api-test

build:
	docker build -t $(IMAGE_REPO):$(TAG) ./app

push:
	docker push $(IMAGE_REPO):$(TAG)

template:
	helm template geo-risk-largest ./chart/geo-risk-largest | tee /dev/tty >/dev/null

install:
	helm upgrade --install geo-risk-largest ./chart/geo-risk-largest \
	  --set image.repository=$(IMAGE_REPO) --set image.tag=$(TAG) --set ingress.host='api-largest.local' \
	  -f geodata-values.local.yaml

uninstall:
	helm uninstall geo-risk-largest || true

pv-apply:
	kubectl apply -f ops/geodata-pv.docker-desktop.yaml

pv-delete:
	-@kubectl delete -f ops/geodata-pv.docker-desktop.yaml

watch-pvc:
	kubectl -n $(NAMESPACE) get pvc geodata -w

logs:
	kubectl -n $(NAMESPACE) logs job/geodata-import-largest -f

pf:
	kubectl -n $(NAMESPACE) port-forward deploy/geoapi 8080:8080

api-test:
	curl 'http://localhost:8080/healthz' && echo && \
	curl 'http://localhost:8080/risk/summary?damnumber=UT00644&targets=power_plants,railroads&clip=true' && echo
