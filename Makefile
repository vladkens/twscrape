.PHONY: all build

all:
	@echo "hi"

build:
	python -m build

lint:
	ruff check twscrape
	ruff check tests

lint-fix:
	ruff check --fix twscrape
	ruff check --fix tests

pylint:
	pylint --errors-only twscrape

test:
	pytest -s --cov=twscrape tests/

get-cov:
	coverage report -m

act:
	act --container-architecture linux/amd64
