.PHONY: all build

all:
	@echo "hi"

install:
	@pip install -e .[dev]

build:
	@python -m build

ci:
	@make format
	@make lint
	@make test

format:
	@black .

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

changelog:
	@git pull origin --tags > /dev/null
	@git log $(shell git describe --tags --abbrev=0 HEAD)^..HEAD --pretty=format:'- %s'

test-py:
	$(eval name=twscrape_py$(v))
	@docker -l warning build -f Dockerfile.python --build-arg VER=$(v) -t $(name) .
	@docker run $(name)

test-sq:
	$(eval name=twscrape_sq$(v))
	@docker -l warning build -f Dockerfile.sqlite --build-arg SQLY=$(y) --build-arg SQLV=$(v) -t $(name) .
	@docker run $(name)

test-py-matrix:
	@make test-py v=3.10
	@make test-py v=3.11
	@make test-py v=3.12

test-sq-matrix:
	@# https://www.sqlite.org/chronology.html
	@make test-sq y=2018 v=3240000
	@make test-sq y=2019 v=3270200
	@make test-sq y=2019 v=3300100
	@make test-sq y=2020 v=3330000
	@make test-sq y=2021 v=3340100
	@make test-sq y=2023 v=3430000
	@make test-sq y=2023 v=3440000

update-mocks:
	twscrape user_by_id --raw 2244994945 | jq > ./tests/mocked-data/user_by_id_raw.json
	twscrape user_by_login --raw xdevelopers | jq > ./tests/mocked-data/user_by_login_raw.json
	twscrape followers --raw --limit 10 2244994945 | jq > ./tests/mocked-data/followers_raw.json
	twscrape following --raw --limit 10  2244994945 | jq > ./tests/mocked-data/following_raw.json
	twscrape tweet_details --raw 1649191520250245121 | jq > ./tests/mocked-data/tweet_details_raw.json
	twscrape retweeters --raw --limit 10 1649191520250245121 | jq > ./tests/mocked-data/retweeters_raw.json
	twscrape favoriters --raw --limit 10 1649191520250245121 | jq > ./tests/mocked-data/favoriters_raw.json
	twscrape user_tweets --raw --limit 10 2244994945 | jq > ./tests/mocked-data/user_tweets_raw.json
	twscrape user_tweets_and_replies --raw --limit 10 2244994945 | jq > ./tests/mocked-data/user_tweets_and_replies_raw.json
	twscrape search --raw --limit 10 "elon musk lang:en" | jq > ./tests/mocked-data/search_raw.json
	twscrape list_timeline --raw --limit 10 1494877848087187461 | jq > ./tests/mocked-data/list_timeline_raw.json
