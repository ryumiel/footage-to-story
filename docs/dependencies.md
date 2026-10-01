# Locked Python Environment

`uv.lock` records exact runtime/test package resolution, distribution URLs, hashes,
and supported Python markers from `pyproject.toml`. It is source, not a generated
skill installation layer. Canonical skills remain directly in `.agents/skills/`.

With uv installed, use:

```bash
uv sync --locked --extra dev
source .venv/bin/activate
python -m pytest -q --junitxml=artifacts/validation/junit.xml
```

`--locked` refuses changes to the lock; do not silently resolve a new environment
as part of execution. `uv lock` is a deliberate development update and must be
reviewed together with dependency changes and tests. The registry is public PyPI.
The existing pip setup remains supported but does not enforce the uv lock.

The verified local target is macOS arm64 with CPython 3.12.14. Dependency and tool
versions from actual test runs belong under ignored `artifacts/validation/`, not
as claims that other platforms were tested. The lock supports Python >=3.11, but
those other interpreter/platform combinations require their own verification.

This locks Python application/test dependencies. It does not lock the operating
system, uv itself, setuptools build isolation, FFmpeg binaries, system OpenSSH/xmllint, or Resolve. Their
observed versions must be recorded in execution evidence. Complete deployment
packaging is a separate task; do not mistake this file for a universal binary lock.
