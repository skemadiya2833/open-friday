# Scripts

Only shipping helpers live here. Local benches, probes, and one-off harnesses stay on the maintainer machine (see root `.gitignore`).

| Script | Purpose |
|--------|---------|
| `pre_push_secrets_check.py` | Block secrets / TLS / audit dumps before push |
| `pre_push_guard.py` | Block `.internal/` and non-public branch names |
| `check_third_party_notices.py` | Keep `docs/THIRD_PARTY_NOTICES.md` in sync |
| `dev.ps1` | Optional Windows helper for a local yellow-path run |

```powershell
python scripts/pre_push_secrets_check.py
python scripts/pre_push_guard.py
```
