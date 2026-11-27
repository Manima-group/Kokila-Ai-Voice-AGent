FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci

FROM node:22-alpine AS build
WORKDIR /app
ARG BACKEND_URL=http://api:8000
ENV NEXT_TELEMETRY_DISABLED=1 BACKEND_URL=${BACKEND_URL}
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN npm run build

FROM node:22-alpine AS runtime
WORKDIR /app
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
RUN addgroup -S -g 10001 kokila && adduser -S -u 10001 -G kokila kokila
COPY --from=build --chown=kokila:kokila /app/.next/standalone ./
COPY --from=build --chown=kokila:kokila /app/.next/static ./.next/static
COPY --from=build --chown=kokila:kokila /app/public ./public
USER kokila
EXPOSE 3000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD wget -qO- http://127.0.0.1:3000/ >/dev/null || exit 1
CMD ["node", "server.js"]
