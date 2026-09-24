# template-fastapi's implementation of template-base's release contract
# (docs/TEMPLATE.md, "Release: a Makefile contract"). release.yml sets
# RELEASE_VERSION / RELEASE_TAG / RELEASE_ARCH / OCI_* -- see there.

.PHONY: release-arches build sbom release-assets publish release-check finalize

ARCHES := amd64 arm64
REPO := $(or $(GITHUB_REPOSITORY),craftainer/template-fastapi)
OWNER := $(firstword $(subst /, ,$(REPO)))
IMAGE := $(notdir $(REPO))
ASSET := dist/$(IMAGE)-$(RELEASE_VERSION)-$(RELEASE_ARCH)
RELEASE_URL := https://github.com/$(REPO)/releases/download/$(RELEASE_TAG)
OCI_NAME := $(shell printf '%s' '$(or $(OCI_IMAGE_NAME),$(REPO))' | tr '[:upper:]' '[:lower:]')

# renovate: datasource=docker depName=anchore/syft
SYFT_VERSION := v1.52.0

# Only set in CI, by crazy-max/ghaction-github-runtime in release.yml.
ifdef ACTIONS_RUNTIME_TOKEN
CACHE := --cache-from type=gha,scope=$(RELEASE_ARCH) --cache-to type=gha,mode=max,scope=$(RELEASE_ARCH)
endif

# Same label set docker/metadata-action produced in the old release.yml.
# `created` is the commit time so build and publish produce identical
# labels (and therefore the same image) in separate make invocations.
LABELS := \
	--label org.opencontainers.image.title=$(IMAGE) \
	--label org.opencontainers.image.source=https://github.com/$(REPO) \
	--label org.opencontainers.image.url=https://github.com/$(REPO) \
	--label org.opencontainers.image.version=$(RELEASE_VERSION) \
	--label org.opencontainers.image.revision=$(shell git rev-parse HEAD) \
	--label org.opencontainers.image.created=$(shell git log -1 --format=%cI) \
	--label org.opencontainers.image.licenses=GPL-3.0 \
	--label io.github.$(OWNER).sbom=$(RELEASE_URL)/$(IMAGE)-$(RELEASE_VERSION)-$(RELEASE_ARCH).spdx.json \
	--label io.github.$(OWNER).coverage-report=$(RELEASE_URL)/coverage.xml

BUILD := docker buildx build -f app.Dockerfile --target runner \
	--platform linux/$(RELEASE_ARCH) $(LABELS) $(CACHE)

release-arches:
	@python3 -c 'import json,sys; print(json.dumps(sys.argv[1:]))' $(ARCHES)

build:
	mkdir -p dist
	$(BUILD) --output type=oci,dest=$(ASSET).tar .

sbom:
	docker run --rm -v "$(CURDIR)/dist:/dist" anchore/syft:$(SYFT_VERSION) \
		oci-archive:/$(ASSET).tar -o spdx-json=/$(ASSET).spdx.json

release-assets:
	test -f $(ASSET).tar && test -f $(ASSET).spdx.json

publish:
ifeq ($(OCI_REGISTRY),)
	@echo "OCI_REGISTRY not set -- skipping publish."
else
	@printf '%s' "$$OCI_REGISTRY_PASSWORD" | docker login "$(OCI_REGISTRY)" -u "$$OCI_REGISTRY_USERNAME" --password-stdin
	$(BUILD) --push -t $(OCI_REGISTRY)/$(OCI_NAME):$(RELEASE_VERSION)-$(RELEASE_ARCH) .
endif

release-check:
	mkdir -p dist
	uv run pytest --cov-report=xml:dist/coverage.xml

finalize:
ifeq ($(OCI_REGISTRY),)
	@echo "OCI_REGISTRY not set -- no manifest list to create."
else
	@printf '%s' "$$OCI_REGISTRY_PASSWORD" | docker login "$(OCI_REGISTRY)" -u "$$OCI_REGISTRY_USERNAME" --password-stdin
	docker buildx imagetools create --tag $(OCI_REGISTRY)/$(OCI_NAME):$(RELEASE_VERSION) \
		$(foreach a,$(ARCHES),$(OCI_REGISTRY)/$(OCI_NAME):$(RELEASE_VERSION)-$(a))
endif
