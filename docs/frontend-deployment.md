# Running and deploying the frontend

The web app is in `frontend/`. Development and production use separate images:

| Image | Used by | What it is |
|---|---|---|
| `frontend/Dockerfile` (`dev`) | `docker compose` (`frontend` service) | Vite dev server with hot reload |
| `infra/frontend.Dockerfile` | `frontend-preview`, Render | type-checks and builds `dist/`, then nginx serves it and proxies `/api/` to the backend |

How to deploy it (Render, with Neon for the database) is in [deployment.md](deployment.md).

## Same origin, no CORS

The browser only talks to the frontend's address. In development Vite proxies `/api` to the
backend (`frontend/vite.config.ts`), and in production nginx does (`frontend/nginx/default.conf.template`).
So the session cookie (HttpOnly, `SameSite=Lax`) is a first-party cookie and the backend needs no CORS
settings. Don't host the frontend as a Render *Static Site*: it isn't on Render's private network, and
its rewrite rules are documented only for public URLs, so it can't proxy to a private backend.

## Locally

```bash
docker compose --profile app up -d          # backend, worker and the Vite dev server
```

Open http://localhost:5173. Edits to `frontend/src` reload on save. `node_modules` lives in the
`frontend-node-modules` volume and `npm install` runs at every start, so a changed `package.json`
is picked up by restarting: `docker compose --profile app restart frontend`.

To try the production image the way Render runs it (the backend has to be running; it uses
`infra/frontend.Dockerfile`):

```bash
docker compose --profile preview up -d --build frontend-preview
```

Open http://localhost:8080. This is the check to run before deploying.

The dev container no longer needs Node for running the app. Node is still there for `npm run test:unit`,
`npm run lint` and `npm run gen:api`.

## On Render

See [deployment.md](deployment.md) and `render.yaml`. In short, a Docker **Web Service** with Dockerfile
`./infra/frontend.Dockerfile`, build context `./frontend`, health check `/healthz` (answered by nginx
itself, so a backend outage doesn't restart the frontend), and two variables:

| Variable | Value |
|---|---|
| `API_UPSTREAM_URL` | the backend with scheme, no trailing slash: `https://rag-backend-xxxx.onrender.com`, or `http://host:port` on a private network |
| `API_HOST` | the same backend's host name alone, sent as the `Host` header and TLS server name |

`PORT` is set by Render (10000 by default) and nginx listens on it. Render ends TLS at its load
balancer and passes plain HTTP on, and the template forwards `X-Forwarded-Proto`.

Any other Docker host, such as a VPS running Compose, works the same way: run the image with `PORT`,
`API_UPSTREAM_URL` and `API_HOST` set.
