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
npm run test:cov   # one pass with a v8 coverage report; two workers, because with all of them the
                   # instrumented run is slow enough to trip a timing-sensitive spec
```

Specs live in `src/__tests__/`. They stub `fetch` (`helpers.ts`: `stubFetch` answers by URL, `serve`
by method and path, `writes` lists the non-GET calls), so no backend is needed. When a spec shows a
bug, it is written to fail first.

## Talking to the backend

In dev, Vite proxies `/api/*` to the FastAPI backend at `http://localhost:8000`, with the same path as in
production (`/api/v1/...`). Start the backend from `backend/` with `uvicorn app.main:app --port 8000`
(or the "Backend: FastAPI" launch config). Set `VITE_API_PROXY_TARGET` to point the proxy somewhere else.

Call the API through `api` from `src/api/client.ts`. Its types are generated from `openapi.json`: after
changing the API, see "Running it" in [docs/backend-workflow.md](../docs/backend-workflow.md).
Path alias: `@` -> `src/`.

IDE: [Vue (Official)](https://marketplace.visualstudio.com/items?itemName=Vue.volar), disable Vetur.
