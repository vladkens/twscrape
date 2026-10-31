# twscrape

Async Python library and CLI for X/Twitter scraping.

- Run `make check` and `make test` before every commit.
- Commits are one short lowercase line, `type: what` (`feat`, `fix`, `docs`, `chore`, `ci`; `!` for a breaking change), with no body and the docs changed in the same commit.
- Every change reaches `main` through a pull request from a `feat/<name>` or `fix/<name>` branch, titled like a commit; the person reviews and squash-merges it: never merge.
- Only with the person's approval: a change to the public API or CLI, or a new dependency. Change dependencies only with `uv add` and `uv remove`, never by hand.
- Tests use the mocked responses in `tests/mocked-data/` and never touch the network; never hard-code the content of its `raw_*.json` in tests. Run `make update` only when the person asks: it calls X with their accounts.
- Releases are the person's: the version and `changelog.md` change only in a `release: vX.Y.Z` pull request.
- Readme images keep relative `.github/` paths: CI rewrites them for PyPI.
