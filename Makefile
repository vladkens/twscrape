.PHONY: all build

SQTEST = docker -l warning build -f sqlite.dockerfile

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

act:
	@act --container-architecture linux/amd64

changelog:
	@git pull origin --tags > /dev/null
	@git log $(shell git describe --tags --abbrev=0 HEAD)^..HEAD --pretty=format:'- %s'

test34:
	@# https://www.sqlite.org/chronology.html
	@$(SQTEST) --build-arg SQLY=2018 --build-arg SQLV=3240000 -t twscrape_sq24 .
	@$(SQTEST) --build-arg SQLY=2019 --build-arg SQLV=3270200 -t twscrape_sq27 .
	@$(SQTEST) --build-arg SQLY=2019 --build-arg SQLV=3300100 -t twscrape_sq30 .
	@$(SQTEST) --build-arg SQLY=2020 --build-arg SQLV=3330000 -t twscrape_sq33 .
	@$(SQTEST) --build-arg SQLY=2021 --build-arg SQLV=3340100 -t twscrape_sq34 .
	@$(SQTEST) --build-arg SQLY=2023 --build-arg SQLV=3430000 -t twscrape_sq43 .
	@docker run twscrape_sq24
	@docker run twscrape_sq27
	@docker run twscrape_sq30
	@docker run twscrape_sq33
	@docker run twscrape_sq34
	@docker run twscrape_sq43

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
