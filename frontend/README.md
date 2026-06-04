# Mikrotik Minder — Frontend

A small single-page operator dashboard for the Mikrotik Minder control plane.
Built with Vite + React 18 + TypeScript. No UI framework.

It lets an operator:

- enter the **API base URL**, **admin token**, and an optional **operator email**
  (all persisted to `localStorage`);
- see backend **health** (`GET /v1/health`);
- **Load** agents (`GET /v1/admin/agents`) and devices (`GET /v1/admin/devices`)
  into two tables, with error messages on failure (e.g. 401).

## Project layout

```
frontend/
├── Dockerfile              # multi-stage: node build -> nginx:alpine on :8080
├── docker-entrypoint.sh    # generates /config.js from $API_BASE at start
├── nginx.conf              # SPA fallback (try_files $uri /index.html)
├── index.html              # loads /config.js then the app
├── package.json
├── tsconfig.json
├── vite.config.ts
├── public/
│   ├── _redirects          # Cloudflare Pages SPA routing
│   └── config.js           # empty runtime-config stub (overwritten in Docker)
└── src/
    ├── api.ts              # typed API client
    ├── config.ts           # resolves the default API base URL
    ├── App.tsx
    ├── main.tsx
    ├── styles.css
    └── vite-env.d.ts
```

## Configuration: how the API base URL is resolved

The initial default API base URL is resolved in this order:

1. **Runtime** — `window.__CONFIG__.API_BASE`, injected by `/config.js`.
   In Docker this file is regenerated at container start from the `API_BASE`
   env var, so one image can target any control plane without rebuilding.
2. **Build-time** — `VITE_API_BASE` (Vite env, baked into the build).
3. **Default** — `http://localhost:8000`.

The user can always override the value in the UI; the override is saved to
`localStorage`.

## Local development

```sh
npm install
npm run dev        # Vite dev server (http://localhost:5173)
```

Build and preview a production bundle:

```sh
npm run build      # type-checks then emits static files to dist/
npm run preview    # serves dist/ on http://localhost:4173
```

Optional build-time API base:

```sh
VITE_API_BASE=https://minder.example.com npm run build
```

## Docker

Multi-stage build producing an `nginx:alpine` image that serves `dist/` on
**port 8080** with SPA fallback. The API base URL is set **at runtime** via the
`API_BASE` env var (no rebuild needed).

```sh
# from the frontend/ directory
docker build -t mikrotik-minder-frontend .

docker run --rm -p 8080:8080 \
  -e API_BASE=https://minder.example.com \
  mikrotik-minder-frontend
```

Then open http://localhost:8080. On startup the container writes
`/usr/share/nginx/html/config.js` containing the `API_BASE` value, and the app
picks it up via `window.__CONFIG__.API_BASE`. `config.js` and `index.html` are
served with `Cache-Control: no-store` so a restart with a new `API_BASE` takes
effect immediately.

### Kubernetes

No manifests are included here, but the image is k8s-ready: it listens on
**8080** and is configured through the **`API_BASE`** env var. Set it via the
container's `env`.

## Cloudflare Pages

Static deploy — no Docker involved.

- **Build command:** `npm run build`
- **Build output directory:** `dist`
- **Node version:** 18+ (22 recommended)

SPA routing is handled by `public/_redirects` (`/*  /index.html  200`), which
Vite copies into `dist/` at build time.

For a fixed API base on Pages, set the **`VITE_API_BASE`** environment variable
in the Pages project settings (build-time). Operators can still override the API
base in the UI at runtime.
```sh
# equivalent local check of the exact Pages build
npm install
npm run build   # output in dist/
```
