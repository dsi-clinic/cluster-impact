SITE_IMAGE      := cluster-impact-site
COLLECTOR_IMAGE := cluster-impact-collector

DOCKER_ARGS := -v $(PWD):/site -v cluster_impact_bundle_cache:/usr/local/bundle
PORT        := -p 4000:4000
JEKYLL_CMD  := bundle exec jekyll serve --config _config.yml,_config_local.yml --livereload --host 0.0.0.0

# Container runtime: docker (OrbStack) locally, podman on the cluster.
CONTAINER ?= docker

.PHONY: help
help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- site

.PHONY: build
build: ## Build the Jekyll dev image
	$(CONTAINER) build -f Dockerfile . -t $(SITE_IMAGE)

.PHONY: serve
serve: build ## Serve the site at http://localhost:4000
	$(CONTAINER) run --rm $(DOCKER_ARGS) $(PORT) $(SITE_IMAGE) $(JEKYLL_CMD)

.PHONY: inter
inter: build ## Interactive shell in the site container
	$(CONTAINER) run --rm -it $(DOCKER_ARGS) $(SITE_IMAGE) /bin/bash

.PHONY: trace
trace: build ## Serve with --trace for build debugging
	$(CONTAINER) run --rm $(DOCKER_ARGS) $(PORT) $(SITE_IMAGE) $(JEKYLL_CMD) --trace

.PHONY: site-build
site-build: build ## Production build into _site/
	$(CONTAINER) run --rm $(DOCKER_ARGS) $(SITE_IMAGE) bundle exec jekyll build

.PHONY: clean
clean: ## Remove the bundle cache volume
	-$(CONTAINER) rm -f $$($(CONTAINER) ps -aq --filter volume=cluster_impact_bundle_cache) 2>/dev/null
	-$(CONTAINER) volume rm cluster_impact_bundle_cache 2>/dev/null

.PHONY: rebuild
rebuild: clean build serve ## Full reset and serve

# ------------------------------------------------------------ collector

.PHONY: collector-image
collector-image: ## Build the collector image
	$(CONTAINER) build -f Containerfile.collector . -t $(COLLECTOR_IMAGE)

.PHONY: collect-dry
collect-dry: ## Run the whole pipeline against tests/fixtures, no cluster needed
	python -m collector.cli collect \
	  --from-dump tests/fixtures \
	  --out ./data --summary ./_data/summary.json --no-commit

.PHONY: backfill-dry
backfill-dry: ## Rehearse a backfill without writing or querying
	python -m collector.cli backfill --dry-run

.PHONY: verify
verify: ## Re-run every privacy assertion over the published data tree
	python -m collector.cli verify ./data

.PHONY: doctor
doctor: ## Check reachability of every configured data source
	python -m collector.cli doctor

.PHONY: test
test: ## Offline test suite (no cluster access)
	python -m pytest tests -q

.PHONY: lint
lint: ## Lint and format-check the collector
	python -m ruff check collector tests
	python -m ruff format --check collector tests

.PHONY: fmt
fmt: ## Autoformat the collector
	python -m ruff format collector tests
	python -m ruff check --fix collector tests
