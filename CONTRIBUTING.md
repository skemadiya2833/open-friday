# Contributing to Project Friday

Thanks for helping. Maintenance time is limited — focused PRs are gold.

## Setup

```bash
python -m venv friday_env
friday_env\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
ollama pull qwen2.5vl:7b-q4_K_M
ollama pull nomic-embed-text
python main.py --server
```

Open http://127.0.0.1:8787/

Optional React shell:

```bash
cd web
npm install
npm run build   # serves from web/dist via FastAPI
```

## Where to contribute

| Area | Path |
|------|------|
| Skills | `friday/skills/builtin/<id>/` |
| Tools | `friday/tools/` |
| Memory | `friday/memory/` |
| Computer-use loop | `friday/agent/`, `friday/actions/` |
| Control Center UI | `web/public/` (default) or `web/src/` (React) |
| Voice | `friday/voice/` |

## Skill packs

1. Create `friday/skills/builtin/my_skill/`
2. Add `manifest.yaml` + `handler.py` with `SkillHandler`
3. Restart the server — the registry hot-loads on startup

## Tests and checks

```powershell
pip install -r requirements/dev.lock.txt
pytest -q                                  # ~175 tests; add --ignore=tests/test_runs_estop.py if you have no interactive desktop
ruff check friday tests main.py scripts --select F,E9
```

Rules that keep this project safe:

- New dependencies go in `requirements/*.in`, are locked with `uv pip compile`, and need a licence and Python 3.14 wheel check (see `docs/decisions/DEPENDENCY_MATRIX.md`).
- Anything that changes the system, sends data out, or controls the desktop is a `confirm`-tier tool at minimum and goes through `friday/tools/registry.py` (policy, approval, audit). No direct `subprocess`/`os.system` from skills.
- Screen text, web pages and tool output are untrusted data; never concatenate them into instructions (see `friday/agent/guard.py`).
- Write state files with `friday.atomic.write_text_atomic`.
- Tests must use scratch folders only and must not touch real accounts. Live-desktop checks belong in `friday/bench/`, never in `pytest`.
- Read `docs/THREAT_MODEL.md` before touching `friday/server/` or `friday/safety/`.
## Contact

Maintainer: **Sunil Kemadiya** (CEO, [Devoids](https://devoids.in)) — skemadiya@gmail.com
