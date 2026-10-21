# twscrape

An async Python library and CLI for X/Twitter Search and GraphQL endpoints. It runs on the user's
own pool of X accounts, keeps sessions in SQLite and returns SNScrape-style models or raw
responses. Agents carry out each change end to end by following this file.

Each fact has one source, which this file points to: the public API is `twscrape/__init__.py` and
the readme's "API Surface", the CLI `twscrape --help`, dependencies `pyproject.toml`, checks and
CI the `Makefile` and `.github/workflows/`.

## Scope

- Support Python 3.10+ (`requires-python` in `pyproject.toml`). Keep dependencies few; change
  them only with `uv add` / `uv remove`, never by hand.
- The public API (exports, `API` methods and their arguments, model fields, exceptions) and the
  CLI commands and output: change them only with the person's approval. Mark a breaking change
  with `!` in the commit type (`fix!:`, `feat!:`).
- Tests never touch the network or real accounts. Only `make update` talks to X; run it only
  when the person asks, since it uses their accounts.

## Code

- Follow the `code-style-python` skill.
- Parse X responses tolerantly: an unknown or malformed optional field must not drop the tweet
  or user. Log a warning instead of failing silently.
- Signal failures with the exported exceptions (`AbortReqError`, `ApiError`, `XClIdParseError`,
  `UserParseError`), not `None`; `None` means X has no data.
- Never send more requests to X than the call needs: retries are bounded and per request, and
  shared state (healed GQL features, dedup windows) stays bounded.
- Put helper scripts in `scripts/`, named in kebab-case, run with `uv run`. A Makefile target
  longer than a line or two calls a script.

## Tests

- `tests/mocked-data/raw_*.json` are refreshed by `make update`
  (`scripts/update-mocked-data.py`): never hard-code their content (counts, ids, texts) in tests;
  compute expectations from the parsed page.
- A case that needs specific data gets a frozen `_`-prefixed fixture: real X data, trimmed to the
  entries the test reads, no tokens, cookies or private data. Load fixtures with `fake_rep`.
- Test outcomes users see, not internal state. Prefer `parametrize` over copied blocks, and
  `utils.find_obj` over hand-written walkers.

## Workflow

- Before committing, run `make check` and `make test`. `make prepare` rewrites files: not a check.
- Every change reaches `main` through a pull request, one per feature; `main` rejects direct
  pushes and allows only squash merges:
  1. Agree the plan with the person. For multi-step work keep a checklist in
     `docs/plans/yyyymmdd-<name>.md` and during the work only tick its checkboxes, with no
     progress prose. The PR that finishes the plan's last item adds a first line
     `Done: yyyy-mm-dd, PR #N` and a short final `## Result` section, and moves it to
     `docs/plans/completed/`. Plans stay; never delete them.
  2. Branch from `main` as `feat/<name>` or `fix/<name>`, in the agent's own git worktree. A small
     change that fits an open PR's topic goes into that PR instead of a new one.
  3. Commit every step that passes `make check` and `make test`: one short lowercase
     conventional line (`fix: ...`), no body, docs updated in the same commit.
  4. Push and open the PR with `gh pr create`. The title is the squash commit; the body says what
     changed and the checks run.
  5. The orchestrating agent reviews the diff, reruns the checks and sends findings back until
     the PR is clean, then hands it to the person. Once the orchestrator accepts the solution,
     the implementing agent runs `codex -C <worktree> review -c model_reasoning_effort=xhigh
     "Review the changes on the current branch against origin/main (git diff
     origin/main...HEAD)."` if available, and fixes or rejects each finding with a reason; the
     orchestrator checks that last diff before handing the PR over.
  6. The person does the final review and squash-merges. Never commit or push to `main`
     directly.
  7. On conflicts, rebase onto `main`, rerun the checks and push with `--force-with-lease`.
- Outside contributors' PRs: review them the same way. Push fixes to their branch only when
  maintainer edits are allowed, as merge commits (never rewrite their history).
- A release goes through a PR too: a branch with one `release: vX.Y.Z` commit (changelog written
  by the person's `git-changelog` skill, version bumped in `pyproject.toml`), squash-merged. The
  person pushes the `vX.Y.Z` tag; CI then publishes to PyPI and creates the GitHub release from
  the changelog entry.
- An orchestrating agent writes each task, verifies every report itself (`make check`,
  `make test`, the diff) instead of trusting it, and keeps the person informed.
- Report a blocker as soon as you hit it: a missing permission or tool, a failing service, or
  anything else that stops the task. Tell whoever delegated the task right away (a subagent
  messages the orchestrator), say what can still be done without it, and keep doing that part.
  Never wait or poll silently for more than a few minutes.
- Ask the person only when output must change, the public API must break, a dependency is
  needed, or the request is ambiguous. Otherwise decide and say so in your report.
- Keep docs to `readme.md` (users, also the PyPI page), `examples/` and `docs/plans/`. No progress
  journals, run logs or disclaimer paragraphs. `changelog.md` is written only in a release
  commit, by the person's changelog skill: don't edit it in feature work.
