# FIX_LOG

## 1. Startup regression reproduced

The CLI was rejecting the exact automation flags needed for a clean startup test:

- `python -m desktop.main --headless --safe-test --exit-after 3 --print-ready`
- `python -m desktop.main --doctor --json`

The pre-fix run exited with `code 2` and `unrecognized arguments`, proving the entrypoint was not ready for automated startup checks.

## 2. Root cause

The desktop launcher in `desktop/main.py` implemented a narrow parser that exposed only a subset of the runtime flags, and it did not support the control-plane hooks required by the startup automation workflow (`--doctor`, `--json`, `--exit-after`, `--print-ready`).

A secondary runtime issue was also confirmed in `desktop/server.py`: the browser requested `/app.js`, but the HTTP app only served `/` and `/sw.js`, which produced a 404 for the web bundle.

## 3. Fix

- Added the missing launcher flags and graceful doctor output in `desktop/main.py`.
- Added a safe exit timer that stops the headless process after the requested delay.
- Added direct file routes for `/app.js`, `/style.css`, and `manifest.webmanifest` in `desktop/server.py`.
- Added a package entry point in `pyproject.toml` and a root wrapper `touchlink.py` for `python -m desktop.main` / `python touchlink.py` consistency.

## 4. Verification

Fresh verification was run with:

```bash
.\.venv_diag\Scripts\python.exe -m pytest tests/test_bootstrap.py -q
```

and the startup checks now pass, confirming the app can be launched in automated headless-safe mode and can report a doctor summary in JSON.
