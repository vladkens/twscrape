.PHONY: all build

all:
	@echo "hi"

build:
	python -m build

lint:
	ruff check twscrape

lint-fix:
	ruff check --fix twscrape

pylint:
	pylint --errors-only twscrape

test:
	pytest --cov=twscrape tests/

act:
	act --container-architecture linux/amd64
