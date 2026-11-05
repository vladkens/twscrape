# twscrape

Async Python library and CLI for X/Twitter scraping.

- Run `make check` and `make test` before every commit.
- Tests use the mocked responses in `tests/mocked-data/` and never touch the network. Never hard-code the content of its `raw_*.json` in tests: `make update` rewrites them.
- `make update` calls X with real accounts: run it only when asked.
- Pull request titles are one short lowercase line, `type: what` (`feat`, `fix`, `docs`, `chore`, `ci`; `!` for a breaking change): the title becomes the squash commit. Docs change in the same pull request.
- A change to the public API or CLI, or a new dependency, needs the maintainer's approval. Change dependencies with `uv add` and `uv remove`, never by hand.
- The version and `changelog.md` change only in a `release: vX.Y.Z` pull request, which CI tags and publishes on merge.
- Readme images keep relative `.github/` paths: CI rewrites them for PyPI.
