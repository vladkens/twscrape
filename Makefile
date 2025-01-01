check:
	@make lint
	@make test

install:
	pip install -e .[dev]
	python -m build

build:
	python -m build --sdist --wheel --outdir dist/ .

lint:
	@# https://docs.astral.sh/ruff/settings/#sorting-imports
	@ruff check --select I --fix .
	@ruff format .
	@ruff check .
	@pyright .

test:
	@pytest -s --cov=twscrape tests/

test-cov:
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
	@make test-py v=3.13

test-sq-matrix:
	@# https://www.sqlite.org/chronology.html
	@make test-sq y=2018 v=3240000
	@make test-sq y=2019 v=3270200
	@make test-sq y=2019 v=3300100
	@make test-sq y=2020 v=3330000
	@make test-sq y=2021 v=3340100
	@make test-sq y=2023 v=3430000
	@make test-sq y=2023 v=3440000
	@make test-sq y=2024 v=3450300

update-mocks:
	@rm -rf ./tests/mocked-data/raw_*.json
	twscrape user_by_id --raw 2244994945 | jq > ./tests/mocked-data/raw_user_by_id.json
	twscrape user_by_login --raw xdevelopers | jq > ./tests/mocked-data/raw_user_by_login.json
	twscrape following --raw --limit 10  2244994945 | jq > ./tests/mocked-data/raw_following.json
	twscrape followers --raw --limit 10 2244994945 | jq > ./tests/mocked-data/raw_followers.json
	twscrape verified_followers --raw --limit 10 2244994945 | jq > ./tests/mocked-data/raw_verified_followers.json
	twscrape subscriptions --raw --limit 10 44196397 | jq > ./tests/mocked-data/raw_subscriptions.json
	twscrape tweet_details --raw 1649191520250245121 | jq > ./tests/mocked-data/raw_tweet_details.json
	twscrape tweet_replies --limit 1 --raw 1649191520250245121 | jq > ./tests/mocked-data/raw_tweet_replies.json
	twscrape retweeters --raw --limit 10 1649191520250245121 | jq > ./tests/mocked-data/raw_retweeters.json
	twscrape user_tweets --raw --limit 10 2244994945 | jq > ./tests/mocked-data/raw_user_tweets.json
	twscrape user_tweets_and_replies --raw --limit 10 2244994945 | jq > ./tests/mocked-data/raw_user_tweets_and_replies.json
	twscrape user_media --raw --limit 10 2244994945 | jq > ./tests/mocked-data/raw_user_media.json
	twscrape search --raw --limit 10 "elon musk lang:en" | jq > ./tests/mocked-data/raw_search.json
	twscrape list_timeline --raw --limit 10 1494877848087187461 | jq > ./tests/mocked-data/raw_list_timeline.json
	@# twscrape favoriters --raw --limit 10 1649191520250245121 | jq > ./tests/mocked-data/raw_favoriters.json
	@# twscrape liked_tweets --raw --limit 10 2244994945 | jq > ./tests/mocked-data/raw_likes.json
