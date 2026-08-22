# Onboarding Generico — tareas de desarrollo
# Ejecute `make ayuda` para ver el catalogo completo.

SHELL       := /bin/bash
PYTHON      ?= python3
VENV        := .venv
BIN         := $(VENV)/bin
TF          ?= terraform
ENV         ?= dev
CLOUD       ?= aws

.DEFAULT_GOAL := ayuda

.PHONY: ayuda
ayuda:  ## Muestra este catalogo de tareas
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}'

# --- Entorno -----------------------------------------------------------------
$(VENV):
	$(PYTHON) -m venv $(VENV)

.PHONY: install
install: $(VENV)  ## Crea el entorno virtual e instala dependencias de desarrollo
	$(BIN)/pip install --upgrade pip
	$(BIN)/pip install -e ".[dev,api]"

.PHONY: install-aws
install-aws: install  ## Anade las dependencias del adaptador de AWS
	$(BIN)/pip install -e ".[aws]"

.PHONY: install-gcp
install-gcp: install  ## Anade las dependencias del adaptador de GCP
	$(BIN)/pip install -e ".[gcp]"

# --- Calidad -----------------------------------------------------------------
.PHONY: test
test:  ## Ejecuta la bateria de pruebas
	PYTHONPATH=src $(PYTHON) -m pytest tests

.PHONY: test-cov
test-cov:  ## Ejecuta las pruebas con informe de cobertura
	PYTHONPATH=src $(PYTHON) -m pytest tests --cov --cov-report=term-missing --cov-report=xml

.PHONY: smoke
smoke:  ## Prueba de humo sin dependencias externas (no requiere pytest)
	PYTHONPATH=src $(PYTHON) tests/run_smoke.py

.PHONY: lint
lint:  ## Lint con ruff y verificacion de tipos con mypy
	$(BIN)/ruff check src tests
	$(BIN)/ruff format --check src tests
	$(BIN)/mypy

.PHONY: format
format:  ## Aplica el formateo automatico
	$(BIN)/ruff format src tests
	$(BIN)/ruff check --fix src tests

.PHONY: verificar
verificar: lint test  ## Puerta de calidad completa: lint + tipos + pruebas

# --- Infraestructura ---------------------------------------------------------
.PHONY: tf-fmt
tf-fmt:  ## Formatea todo el HCL
	$(TF) fmt -recursive infra/terraform

.PHONY: tf-validate
tf-validate:  ## Valida el entorno indicado (ENV=dev|stg|prd)
	cd infra/terraform/envs/$(ENV) && $(TF) init -backend=false && $(TF) validate

.PHONY: tf-plan
tf-plan:  ## Plan del entorno indicado (ENV=dev|stg|prd)
	cd infra/terraform/envs/$(ENV) && $(TF) plan -out=tfplan.$(ENV)

# --- Contenedores ------------------------------------------------------------
.PHONY: docker-build
docker-build:  ## Construye las imagenes de la API y de inferencia
	docker build -f deploy/docker/Dockerfile.api -t onboarding-generico/api:local .
	docker build -f deploy/docker/Dockerfile.inference -t onboarding-generico/inference:local .

.PHONY: up
up:  ## Levanta el entorno local con adaptadores en memoria
	docker compose -f deploy/docker/docker-compose.yml up --build

.PHONY: down
down:  ## Detiene el entorno local
	docker compose -f deploy/docker/docker-compose.yml down -v

# --- Utilidades --------------------------------------------------------------
.PHONY: limpiar
limpiar:  ## Elimina artefactos de construccion y cache
	rm -rf .pytest_cache .mypy_cache .ruff_cache htmlcov .coverage coverage.xml build dist
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
