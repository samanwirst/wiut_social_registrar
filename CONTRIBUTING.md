# Contributing

Use Python 3.11+ (Docker uses 3.12) and Node.js 22.12+ (Docker uses 24 LTS).
Runtime deployment and Outlook sign-in are documented in [README.md](README.md).
Development checks do not need real credentials or a running bot.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
npm ci --prefix frontend
make check
```

`make check` runs Ruff lint/format checks, the TypeScript/frontend build, and pytest.
Use `python -m ruff check --fix .` and `python -m ruff format .` to apply formatting.
Do not reformat historical migrations under `migrations/versions/`.

Use [architecture.md](docs/architecture.md) to identify the module that owns a change.
Share domain rules and repeated stateful logic without introducing generic frameworks.
Preserve public behavior, configuration precedence, and database transaction boundaries.
Add focused regression tests for changed behavior or previously uncovered invariants.

Run the [database and browser checks](docs/testing.md) appropriate to the change.
Keep sample configuration credential-free and all runtime data ignored. Review `git diff`
and `git diff --check` before proposing a commit. Follow the user's instructions about
committing and pushing.

Project instructions for coding agents live in [AGENTS.md](AGENTS.md), with scoped
guidance in the relevant directories. These files link to the same architecture and
testing documents used by human contributors.
