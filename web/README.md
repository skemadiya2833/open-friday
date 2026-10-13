# Friday Control Center (web)

## Canonical UI: `public/`

The shipped Control Center is **vanilla JS** in [`public/`](public/) (`index.html`, `app.js`, `live.js`, …).

FastAPI serves `web/public` by default (`FRIDAY_UI=public`). A Vite `web/dist` build is **opt-in** (`FRIDAY_UI=dist`) so an old build cannot silently replace the live UI.

## Experimental: `src/` (React)

[`src/App.tsx`](src/App.tsx) is a thin React shell for experiments. It is **not** the product UI.

- Do not expect feature parity with `public/` (voice, camera, Systems, pairing).
- Prefer editing `public/` for Control Center work.
- `npm run build` only matters if you intentionally set `FRIDAY_UI=dist`.

## Scripts

```bash
cd web
npm install          # only if using the React experiment
npm run build        # writes dist/ — unused unless FRIDAY_UI=dist
```
