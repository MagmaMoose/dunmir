# ---- Build stage ----
FROM node:22-alpine AS build
WORKDIR /app

# Install deps first for better layer caching.
COPY package.json package-lock.json* ./
RUN npm ci || npm install

COPY . .
RUN npm run build

# ---- Runtime stage ----
FROM nginx:alpine

# nginx config (listens on 8080, SPA fallback).
COPY nginx.conf /etc/nginx/conf.d/default.conf
# Remove the stock server block so ours is the only one.
RUN rm -f /etc/nginx/conf.d/default.conf.bak

COPY --from=build /app/dist /usr/share/nginx/html

# Runtime config generation from API_BASE.
COPY docker-entrypoint.sh /docker-entrypoint.d/99-app-config.sh
RUN chmod +x /docker-entrypoint.d/99-app-config.sh

EXPOSE 8080

# The official nginx image already has an entrypoint that runs every
# executable in /docker-entrypoint.d/ before starting nginx, so dropping our
# script there gives us runtime config generation without overriding CMD.
CMD ["nginx", "-g", "daemon off;"]
