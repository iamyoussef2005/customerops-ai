# CustomerOps AI contributor instructions

## Scope and design

- Implement only the phase explicitly requested by the user. Do not proceed to future phases
  without being asked; the roadmap describes plans, not authorization.
- Write readable, typed, maintainable Python compatible with Python 3.12+.
- Keep the modular monolith. Do not introduce microservices or speculative abstractions.
- Separate API routes and schemas from business services, repositories, and infrastructure.
- Use async where appropriate, especially for I/O. Never block the event loop with synchronous
  network or database clients.
- Keep `main.py` as the application composition root. Reserved packages contain no working
  integrations until their respective phase.

## Configuration and dependencies

- Never hardcode secrets or commit credentials, real customer data, or `.env` files.
- Use environment variables through `core/config.py` for configuration. Keep `.env.example`
  synchronized and safe to publish.
- Do not introduce unnecessary dependencies. Add a library only when implemented behavior needs it.
- Keep runtime dependencies separate from development dependency groups in `pyproject.toml`.
- Never pretend an integration works when it is only mocked. Clearly label placeholders, fakes,
  and unavailable services in code, tests, and documentation.

## Changes and verification

- Always update tests when behavior changes. Test public behavior and meaningful failure cases.
- Keep commits and changes focused; do not modify unrelated work or commit without a user request.
- Keep README and architecture/roadmap documentation synchronized with implementation.
- After each task, run available checks and report results:
  `python -m ruff check .`, `python -m ruff format --check .`, `python -m mypy`,
  `python -m pytest`, and `python -m pip check`.
- If a command cannot run, explain the exact blocker, what was attempted, and how to rerun it.
  Never report an unexecuted check as passing.
- Report remaining limitations and the exact development server command on handoff.
