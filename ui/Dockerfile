# ── Stage 1: install deps ────────────────────────────────────────────────────
FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci --prefer-offline

# ── Stage 2: build ───────────────────────────────────────────────────────────
FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# Build-time env vars (non-secret; injected by CI or k8s ConfigMap at build time).
# The runtime NEXT_PUBLIC_* vars are baked into the JS bundle here.
ARG NEXT_PUBLIC_BMAD_CREW_URL=http://localhost:8000
ENV NEXT_PUBLIC_BMAD_CREW_URL=${NEXT_PUBLIC_BMAD_CREW_URL}

RUN npm run build

# ── Stage 3: minimal runtime image ───────────────────────────────────────────
FROM node:20-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production

# Only copy what Next.js needs to run.
COPY --from=builder /app/public ./public
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static

EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME="0.0.0.0"

CMD ["node", "server.js"]
