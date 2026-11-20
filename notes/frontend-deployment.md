# Running and deploying the frontend

The web app is in `frontend/`. Development and production use separate images:

| Image | Used by | What it is |
|---|---|---|
| `frontend/Dockerfile` (`dev`) | `docker compose` (`frontend` service) | Vite dev server with hot reload |
| `infra/frontend.Dockerfile` | `frontend-preview`, the Azure VM | type-checks and builds `dist/`, then nginx serves it and proxies `/api/` to the backend |

How to deploy it (one Azure VM) is in [deployment.md](deployment.md).

## Same origin, no CORS

The browser only talks to the frontend's address. In development Vite proxies `/api` to the
backend (`frontend/vite.config.ts`), and in production nginx does (`frontend/nginx/default.conf.template`).
So the session cookie (HttpOnly, `SameSite=Lax`) is a first-party cookie and the backend needs no CORS
settings. Don't host the frontend as a static site: a static host can't proxy to a private backend, so the
browser would call the API on another origin.

## Locally

```bash
docker compose --profile app up -d          # backend, worker and the Vite dev server
```

Open http://localhost:5173. Edits to `frontend/src` reload on save. `node_modules` lives in the
`frontend-node-modules` volume and `npm install` runs at every start, so a changed `package.json`
is picked up by restarting: `docker compose --profile app restart frontend`.

To try the production image the way the Azure VM runs it (the backend has to be running; it uses
`infra/frontend.Dockerfile`):

```bash
docker compose --profile preview up -d --build frontend-preview
```

Open http://localhost:8080. This is the check to run before deploying.

The dev container no longer needs Node for running the app. Node is still there for `npm run test:unit`,
`npm run lint` and `npm run gen:api`.

## On the Azure VM

See [deployment.md](deployment.md) and `infra/azure/docker-compose.yml`. The `frontend` service runs
the `infra/frontend.Dockerfile` image with:

| Variable | Value |
|---|---|
| `PORT` | `8080`, the port nginx listens on inside the compose network |
| `API_UPSTREAM_URL` | `http://rag-backend:8000`: the backend with scheme, no trailing slash |
| `API_HOST` | `rag-backend`, the same backend's host name alone (sent as the `Host` header) |

Caddy in front of it ends TLS and passes plain HTTP on; the template forwards `X-Forwarded-Proto`, so
the backend sees `https` and the secure session cookie works. The health check is `/healthz`, answered
by nginx itself, so a backend outage doesn't make the frontend look dead.

Any other Docker host works the same way: run the image with `PORT`, `API_UPSTREAM_URL` and `API_HOST` set.
