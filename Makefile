all:
	@echo "hi"

lint:
	ruff check .

lint-fix:
	ruff check --fix .

pylint:
	pylint --errors-only twapi

test:
	pytest --cov=twapi tests/

act:
	act --container-architecture linux/amd64
