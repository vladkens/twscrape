.PHONY: lint test test-cov build

check: lint test

lint:
	ruff check --select I --fix .
	ruff format .
	clean-pyc
	lint-pyright

test:
	docker run --rm -v "$(PWD)":/app -w /app $(DOCKER_IMAGE) pytest -s --cov=twscrape tests/

test-cov:
	docker run --rm -v "$(PWD)":/app -w /app $(DOCKER_IMAGE) pytest -s --cov=twscrape tests/
	docker run --rm -v "$(PWD)/htmlcov":/app/htmlcov $(DOCKER_IMAGE) coverage html --omit='*/*site-packages/*.py'
	open htmlcov/index.html

build:
	docker build -t twscrape .

clean-pyc

# Dockerfile
FROM python:3.11-slim

RUN pip install --no-cache-dir -U pip

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY . .

CMD [ "bash", "-l", "-c", "pytest -s --cov=twscrape tests/" ]

# Dockerfile.test
FROM python:3.11-slim

RUN pip install --no-cache-dir -U pip

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY . .

CMD [ "bash", "-l", "-c", "pytest -s tests/" ]

# tox.ini
[tool:tox]
isolated_build = True
envlist = py311

[tool:tox:tool:py311]
deps =
    twscrape
    pytest
    pytest-cov
    ruff
    pyright
    jq
    twint

[tool:tox:py311]
commands =
    ruff check --select I --fix {posargs:.}
    ruff format {posargs:.}
    pytest -s --cov=twscrape {pytest:tests/}

# .github/workflows/main.yml
name: CI

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
    - name: Checkout
      uses: actions/checkout@v2

    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: 3.11

    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt

    - name: Lint
      run: make lint

    - name: Test
      run: make test

    - name: Build
      run: make build

# Dockerignore
.DS_Store
.env
.github
.py
.pyc
.py
.pytest_cache
.v2
.vscode
.venv


[tool.ruff]
select = ['I']
ignore = []

[tool.ruff.pycodestyle]
ignore = ['E5', 'E402']

[tool.ruff.perror]
ignore = []

[tool.ruff.flake8-quotes]
docstring-files = ['*.pyc']

[tool.ruff.flake8-tidy-imports]
ban-relative-imports = '*'

[tool.ruff.isort.known-first-party]
twscrape = 'twscrape'

[tool.ruff.isort]
known-first-party = ['twscrape']
