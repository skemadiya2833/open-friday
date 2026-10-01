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

## Tests

```bash
python tests/test_skills_tools.py
```

## Contact

Maintainer: **Sagar Kemadiya** (CEO, [Devoids](https://devoids.in)) — skemadiya@gmail.com
