# syntax=docker/dockerfile:1
#
# Development image only: docker-compose.yml uses `target: dev`. Build context: frontend/.
# The production image (nginx) is infra/frontend.Dockerfile. See docs/deployment.md.

# package.json "engines": ^22.18 || >=24.12
ARG NODE_VERSION=24

FROM node:${NODE_VERSION}-slim AS dev
WORKDIR /app
# node_modules sits in a named volume (see docker-compose.yml). Creating it here gives the volume
# the right owner, and keeps the host's copy out of the container (different platform).
RUN mkdir node_modules && chown node:node /app node_modules
USER node
EXPOSE 5173
# `npm install` does nothing when node_modules already matches package-lock.json.
CMD ["sh", "-c", "npm install && exec npm run dev"]
