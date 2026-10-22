# Build do front e entrega por nginx. Zero CDN: fonte, ícone e asset saem daqui.
FROM node:24-alpine AS build
WORKDIR /repo

COPY package.json package-lock.json* ./
COPY apps/web/package.json apps/web/
COPY packages/ds/package.json packages/ds/
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund

COPY packages/ds packages/ds
COPY apps/web apps/web
# O gate de i18n roda no build: locale incompleto não vira imagem.
RUN npm run build --workspace @gplansis/web

# 1.27 (mainline) não recebe mais correção; imagem sem root, já escuta em 8080.
FROM nginxinc/nginx-unprivileged:1.28-alpine
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /repo/apps/web/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=20s --timeout=3s CMD wget -qO- http://localhost:8080/ >/dev/null || exit 1
