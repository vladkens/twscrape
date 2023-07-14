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

changelog:
	@git pull origin --tags > /dev/null
	@git log $(shell git describe --tags --abbrev=0 HEAD)^..HEAD --pretty=format:'- %s'

test34:
	docker build -f Dockerfile-test .

update-mocks:
	twscrape user_by_id --raw 2244994945 | jq > ./tests/mocked-data/user_by_id_raw.json
	twscrape user_by_login --raw twitterdev | jq > ./tests/mocked-data/user_by_login_raw.json
	twscrape followers --raw --limit 10 2244994945 | jq > ./tests/mocked-data/followers_raw.json
	twscrape following --raw --limit 10  2244994945 | jq > ./tests/mocked-data/following_raw.json
	twscrape tweet_details --raw 1649191520250245121 | jq > ./tests/mocked-data/tweet_details_raw.json
	twscrape retweeters --raw --limit 10 1649191520250245121 | jq > ./tests/mocked-data/retweeters_raw.json
	twscrape favoriters --raw --limit 10 1649191520250245121 | jq > ./tests/mocked-data/favoriters_raw.json
	twscrape user_tweets --raw --limit 10 2244994945 | jq > ./tests/mocked-data/user_tweets_raw.json
	twscrape user_tweets_and_replies --raw --limit 10 2244994945 | jq > ./tests/mocked-data/user_tweets_and_replies_raw.json
	twscrape search --raw --limit 10 "elon musk lang:en" | jq > ./tests/mocked-data/search_raw.json
