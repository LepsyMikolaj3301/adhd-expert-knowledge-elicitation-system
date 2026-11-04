# frontend

Vue 3 + TypeScript + Vite + Vue Router + Pinia, tested with Vitest, linted with oxlint/ESLint, formatted with Prettier.
Needs Node `^22.18.0 || >=24.12.0` (the devcontainer installs Node 24).

```sh
npm install        # once
npm run dev        # http://localhost:5173, HMR
npm run build      # type-check + production build into dist/
npm run type-check # vue-tsc only
npm run lint       # oxlint + eslint (with --fix)
npm run format     # prettier on src/
npm run test:unit  # vitest (watch mode; add -- --run for a single pass)
```

## Talking to the backend

In dev, Vite proxies `/api/*` to the FastAPI backend and strips the prefix, so `fetch('/api/health')` hits
`GET /health` on `http://localhost:8000`. Start the backend from `backend/` with `uvicorn app.main:app --port 8000`
(or the "Backend: FastAPI" launch config). Set `VITE_API_PROXY_TARGET` to point the proxy somewhere else.
Path alias: `@` -> `src/`.

IDE: [Vue (Official)](https://marketplace.visualstudio.com/items?itemName=Vue.volar), disable Vetur.
