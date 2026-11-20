# syntax=docker/dockerfile:1
#
# Production image of the web app (what the Azure VM runs): nginx serves the built files and proxies /api/
# to the backend, so the browser sees one origin and the session cookie needs no CORS.
# The dev image (Vite with hot reload) is frontend/Dockerfile.
#
# Build context: frontend/ (the Dockerfile itself lives here in infra/):
#
#   docker build -f infra/frontend.Dockerfile -t rag-frontend frontend/
#
# Runtime environment (the official nginx image fills these into nginx/default.conf.template):
#   PORT              port to listen on (default 8080)
#   API_UPSTREAM_URL  backend with scheme, no trailing slash: http://rag-backend:8000
#   API_HOST          host name of that backend, no scheme: sent as Host header and TLS server name
# See notes/deployment.md.

# package.json "engines": ^22.18 || >=24.12
ARG NODE_VERSION=24

FROM node:${NODE_VERSION}-slim AS build
WORKDIR /app
COPY package.json package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci
COPY . .
# Type-checks, then builds.
RUN npm run build

FROM nginx:1.28-alpine AS runtime
# NGINX_ENTRYPOINT_LOCAL_RESOLVERS makes the image export NGINX_LOCAL_RESOLVERS, so nginx looks the
# backend up again instead of caching its first address.
ENV PORT=8080 \
    API_UPSTREAM_URL=http://rag-backend:8000 \
    API_HOST=rag-backend \
    NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1
COPY nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
