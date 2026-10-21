# twscrape

Async Python library and CLI for X/Twitter scraping. Code style: the `code-style-python` skill.

## Workflow

- Before committing, run `make check` and `make test`. `make prepare` rewrites files: not a check.
- Every change reaches `main` through a pull request, one per feature:
  1. Branch from `main` as `feat/<name>` or `fix/<name>`, in the agent's own git worktree.
  2. Commit every step that passes the checks: one short lowercase line (`fix: ...`), no body,
     docs updated in the same commit.
  3. Push and open the PR with `gh pr create`. The title is the squash commit; the body says what
     changed and the checks run.
  4. The orchestrating agent reviews the diff, reruns the checks and sends findings back until the
     PR is clean, then hands it to the person.
  5. The person does the final review and squash-merges. Never merge, and never commit or push to
     `main` directly.
- Tests never touch the network. Run `make update` only when the person asks: it uses their X
  accounts. Never hard-code the content of `tests/mocked-data/raw_*.json` in tests.
- Report a blocker as soon as you hit it, say what can still be done without it, and keep doing
  that part.
- Ask the person only when the public API or CLI must change, a dependency is needed, or the
  request is ambiguous. Otherwise decide and say so in your report.
- `changelog.md` is written only in a release commit, by the person's changelog skill.
