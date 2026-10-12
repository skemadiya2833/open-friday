# Release checklist

Use this when cutting a tagged Friday release (`vX.Y.Z`).

## Preflight (dev machine)

1. `git status` clean on the release branch.
2. Version matches in [`friday/__init__.py`](../friday/__init__.py) and [`pyproject.toml`](../pyproject.toml).
3. `pip install -r requirements/dev.lock.txt && pip install -e .`
4. `ruff check friday tests main.py scripts --select F,E9`
5. `pytest -q -k "not real_hotkey and not hotkey_conflict"`
6. `friday doctor` — note any WARN/FAIL that are environment-only (missing Ollama models is OK if documented).
7. `python scripts/pre_push_secrets_check.py`
8. `python scripts/pre_push_guard.py`

## Tag and publish

1. Update short notes in the GitHub Release body (installer one-liner, doctor flags, breaking changes).
2. `git tag -a vX.Y.Z -m "Friday vX.Y.Z"`
3. `git push origin HEAD && git push origin vX.Y.Z`
4. Confirm CI is green on the tagged commit.
5. Create a GitHub Release from the tag.

## Fresh-machine smoke (required for installer changes)

On a clean Windows 11 VM or spare PC:

```powershell
irm https://raw.githubusercontent.com/skemadiya2833/open-friday/main/deploy/windows/install.ps1 | iex
friday version
friday doctor
friday
```

Verify:

- Control Center opens at `http://127.0.0.1:8787/`
- Doctor prints `next steps` with exact `ollama pull …` lines when models are missing
- `-PullModels` path works if you re-run the installer with that flag
- Uninstall script removes `%LOCALAPPDATA%\OpenFriday` and the PATH shim

## Installer URL

Canonical raw URL (default branch `main`):

`https://raw.githubusercontent.com/skemadiya2833/open-friday/main/deploy/windows/install.ps1`

If the default branch is not `main`, update README + `deploy/windows/README.md` before advertising the one-liner.

## Out of scope for a normal release

- PyPI publish
- Auto-pulling models without `-PullModels`
- OAuth / messaging channel changes
