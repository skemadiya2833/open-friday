# Contributing to Project Friday

Thanks for helping. Maintenance time is limited — focused PRs are gold.

## Setup

```powershell
python -m venv friday_env
friday_env\Scripts\activate
pip install -r requirements/core.lock.txt
pip install -r requirements/dev.lock.txt
pip install -e .
copy .env.example .env
# Use models already installed locally (default: qwen3.5:9b). Do not pull extras unless asked.
friday doctor
friday serve --server
# or: python main.py --server
```

Open http://127.0.0.1:8787/

Optional React shell:

```bash
cd web
npm install
npm run build   # serves from web/dist via FastAPI
```

## Credits and references

See [`docs/REFERENCES.md`](docs/REFERENCES.md) and [`docs/THIRD_PARTY_NOTICES.md`](docs/THIRD_PARTY_NOTICES.md).
Adapted-from headers must stay listed in the notices file — `python scripts/check_third_party_notices.py`
(also run from `scripts/pre_push_secrets_check.py`).

## Where to contribute

| Area | Path |
|------|------|
| Skills | `friday/skills/builtin/<id>/` |
| Tools | `friday/tools/` |
| Memory | `friday/memory/` |
| Computer-use loop | `friday/agent/`, `friday/actions/` |
| Research reports | `friday/reports/`, `web/public/reports.js` |
| Control Center UI | `web/public/` (default) or `web/src/` (React) |
| Voice | `friday/voice/` |

## Skill packs

1. Create `friday/skills/builtin/my_skill/`
2. Add `manifest.yaml` + `handler.py` with `SkillHandler`
3. Restart the server — the registry hot-loads on startup

## Tests and checks

GitHub Actions runs the same suite on push/PR (`.github/workflows/ci.yml`). Still run locally before pushing:

```powershell
pip install -r requirements/dev.lock.txt
pip install -e .
playwright install chromium                 # once; needed for webauthn/XSS browser tests
pytest -q -k "not real_hotkey and not hotkey_conflict"
ruff check friday tests main.py scripts --select F,E9
friday doctor --json --no-hardware
python scripts/pre_push_secrets_check.py   # required before any push — secrets / data/tls / audit dumps
python scripts/pre_push_guard.py           # blocks .internal/ and non-public branch names
```

Cutting a release: [`docs/RELEASE_CHECKLIST.md`](docs/RELEASE_CHECKLIST.md).

Rules that keep this project safe:

- New dependencies go in `requirements/*.in`, are locked with `uv pip compile`, and need a licence and Python 3.14 wheel check documented in the PR.
- Anything that changes the system, sends data out, or controls the desktop is a `confirm`-tier tool at minimum and goes through `friday/tools/registry.py` (policy, approval, audit). No direct `subprocess`/`os.system` from skills.
- Screen text, web pages and tool output are untrusted data; never concatenate them into instructions (see `friday/agent/guard.py`).
- Write state files with `friday.atomic.write_text_atomic`.
- Tests must use scratch folders only and must not touch real accounts. Live-desktop checks belong in `friday/bench/`, never in `pytest`.
- Read `docs/THREAT_MODEL.md` before touching `friday/server/` or `friday/safety/`.
## Contact

Maintainer: **Sunil Kemadiya** (CEO, [Devoids](https://devoids.in)) — skemadiya@gmail.com
