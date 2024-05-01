# Makefile

.PHONY: lint test test-cov build check deps update-mocks

check: lint test

lint:
	ruff check --select I --fix .
	ruff format .
	ruff check .
	pyright .

test:
	docker run --rm -v "$(PWD)":/app -w /app python:3.11-slim pytest -s --cov=twscrape tests/

test-cov:
	docker run --rm -v "$(PWD)":/app -w /app python:3.11-slim pytest -s --cov=twscrape tests/
	docker run --rm -v "$(PWD)/htmlcov":/app/htmlcov python:3.11-slim coverage html
	open htmlcov/index.html

build:
	docker build -t twscrape .

deps:
	pip install -e .[dev]

update-mocks:
	rm -rf ./tests/mocked-data/raw_*.json
	twscrape user_by_id --raw 2244994945 | jq > ./tests/mocked-data/raw_user_by_id.json
	twscrape user_by_login --raw xdevelopers | jq > ./tests/mocked-data/raw_user_by_login.json
	twscrape following --raw --limit 10  2244994945 | jq > ./tests/mocked-data/raw_following.json
	twscrape followers --raw --limit 10 2244994945 | jq > ./tests/mocked-data/raw_followers.json
	twscrape verified_followers --raw --limit 10 2244994945 | jq > ./tests/mocked-data/raw_verified_followers.json
	twscrape subscriptions --raw --limit 10 44196397 | jq > ./tests/mocked-data/raw_subscriptions.json
	twscrape tweet_details --raw 1649191520250245121 | jq > ./tests/mocked-data/raw_tweet_details.json
	twscrape tweet_replies --limit 1 --raw 1649191520250245121 | jq > ./tests/mocked-data/raw_tweet_replies.json
	twscrape retweeters --raw --limit 10 1649191520250245121 | jq > ./tests/mocked-data/raw_retweeters.json
	twscrape favoriters --raw --limit 10 1649191520250245121 | jq > ./tests/mocked-data/raw_favoriters.json
	twscrape user_tweets --raw --limit 10 2244994945 | jq > ./tests/mocked-data/raw_user_tweets.json
	twscrape user_tweets_and_replies --raw --limit 10 2244994945 | jq > ./tests/mocked-data/raw_user_tweets_and_replies.json
	twscrape user_media --raw --limit 10 2244994945 | jq > ./tests/mocked-data/raw_user_media.json
	twscrape search --raw --limit 10 "elon musk lang:en" | jq > ./tests/mocked-data/raw_search.json
	twscrape list_timeline --raw --limit 10 1494877848087187461 | jq > ./tests/mocked-data/raw_list_timeline.json
	twscrape liked_tweets --raw --limit 10 2244994945 | jq > ./tests/mocked-data/raw_likes.json


# .github/workflows/main.yml

name: CI

on:
  push:
    branches: [ main ]
  pull_request:
    branches: [ main ]

jobs:
  build:
    runs-on: ubuntu-latest

    steps:
    - name: Checkout
      uses: actions/checkout@v2

    - name: Set up Python
      uses: actions/setup-python@v2
      with:
        python-version: 3.11

    - name: Install dependencies
      run: |
        python -m pip install --upgrade pip
        pip install -r requirements.txt

    - name: Lint
      run: make lint

    - name: Test
      run: make test

    - name: Build
      run: make build


twscrape
pytest
pytest-cov
ruff
pyright
jq
twint


# Dockerfile

FROM python:3.11-slim

RUN pip install --no-cache-dir -U pip

WORKDIR /app

COPY requirements.txt requirements.txt
RUN pip install -r requirements.txt

COPY . .

CMD [ "bash", "-l", "-c", "pytest -s --cov=twscrape tests/" ]


# tox.ini

[tox]
envlist = py311

[testenv]
deps =
    pytest
    pytest-cov
    ruff
    pyright
    jq
    twint
commands =
    ruff check --select I --fix .
    ruff format .
    ruff check .
    pytest -s --cov=twscrape tests/
