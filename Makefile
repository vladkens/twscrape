all:
	@echo "hi"

lint:
	ruff check twapi

lint-fix:
	ruff check --fix twapi

pylint:
	pylint --errors-only twapi

test:
	pytest --cov=twapi tests/

act:
	act --container-architecture linux/amd64
