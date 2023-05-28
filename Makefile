.PHONY: all build

all:
	@echo "hi"

install:
	@pip install -e .[dev]

build:
	@python -m build

ci:
	@make lint
	@make test

lint:
	@ruff check twscrape
	@ruff check tests

lint-fix:
	@ruff check --fix twscrape
	@ruff check --fix tests

pylint:
	@pylint --errors-only twscrape

test:
	@pytest -s --cov=twscrape tests/

show-cov:
	@pytest -s --cov=twscrape tests/
	@coverage html
	@open htmlcov/index.html

act:
	@act --container-architecture linux/amd64
