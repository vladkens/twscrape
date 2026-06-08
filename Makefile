.PHONY: prepare install update lint check test test-py test-sq test-matrix-py test-matrix-sq

prepare: lint check

install:
	uv sync

update:
	uv run scripts/update_gql_ops.py
	uv run scripts/update_mocked_data.py

update-deps:
	uv sync --upgrade --all-groups
	uv --preview-features audit audit

lint:
	uv run ruff check --select I --fix .
	uv run ruff format .

check:
	uv run ruff format --check .
	uv run ruff check .
	uv run ty check

test:
	@uv run pytest -s --cov=twscrape tests/

test-py:
	$(eval name=twscrape_py$(v))
	@docker -l warning build -f Dockerfile.py-matrix --build-arg VER=$(v) -t $(name) .
	@docker run $(name)

test-sq:
	$(eval name=twscrape_sq$(v))
	@docker -l warning build -f Dockerfile.sq-matrix --build-arg SQLY=$(y) --build-arg SQLV=$(v) -t $(name) .
	@docker run $(name)

test-matrix-py:
	@make test-py v=3.10
	@make test-py v=3.11
	@make test-py v=3.12
	@make test-py v=3.13
	@make test-py v=3.14

test-matrix-sq:
	@# https://www.sqlite.org/chronology.html https://www.sqlite.org/download.html
	@make test-sq y=2018 v=3240000
# 	@make test-sq y=2019 v=3270200
# 	@make test-sq y=2019 v=3300100
# 	@make test-sq y=2020 v=3330000
# 	@make test-sq y=2021 v=3340100
# 	@make test-sq y=2023 v=3430000
# 	@make test-sq y=2023 v=3440000
# 	@make test-sq y=2024 v=3450300
	@make test-sq y=2026 v=3530100
