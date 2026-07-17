# ---- Build ----
FROM node:22-slim AS builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY prisma/ ./prisma/
RUN npx prisma generate
COPY tsconfig.json ./
COPY src/ ./src/
RUN npx tsc

# ---- Runtime ----
FROM node:22-slim

WORKDIR /app

RUN apt-get update -qq && apt-get install -y -qq --no-install-recommends \
    openssl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY package.json package-lock.json ./
RUN npm ci --only=production

COPY --from=builder /app/node_modules/.prisma /app/node_modules/.prisma
COPY --from=builder /app/dist ./dist
COPY static/ ./static/
COPY prisma/ ./prisma/
COPY .env ./.env

RUN mkdir -p /app/.rbs_rag

EXPOSE 3001

ENV NODE_ENV=production
ENV DATABASE_URL=file:./dev.db

CMD ["node", "dist/index.js"]
