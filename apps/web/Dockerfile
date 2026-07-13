FROM node:18-alpine AS deps
WORKDIR /app
COPY package.json ./
RUN npm install

FROM node:18-alpine AS builder
WORKDIR /app
ARG NEXT_PUBLIC_API_URL
ARG NEXT_PUBLIC_WS_URL
ARG NEXT_PUBLIC_AGENT_RUNTIME
ENV NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL
ENV NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL
ENV NEXT_PUBLIC_AGENT_RUNTIME=$NEXT_PUBLIC_AGENT_RUNTIME
COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN test -n "$NEXT_PUBLIC_API_URL" \
    && test -n "$NEXT_PUBLIC_WS_URL" \
    && test -n "$NEXT_PUBLIC_AGENT_RUNTIME" \
    && case "$NEXT_PUBLIC_API_URL" in https://*) ;; *) echo "NEXT_PUBLIC_API_URL must use https:// and must not be loopback" >&2; exit 1;; esac \
    && case "$NEXT_PUBLIC_API_URL" in *localhost*|*127.0.0.1*|*0.0.0.0*|*\[::1\]*) echo "NEXT_PUBLIC_API_URL must not be loopback" >&2; exit 1;; *) ;; esac \
    && case "$NEXT_PUBLIC_WS_URL" in wss://*) ;; *) echo "NEXT_PUBLIC_WS_URL must use wss:// and must not be loopback" >&2; exit 1;; esac \
    && case "$NEXT_PUBLIC_WS_URL" in *localhost*|*127.0.0.1*|*0.0.0.0*|*\[::1\]*) echo "NEXT_PUBLIC_WS_URL must not be loopback" >&2; exit 1;; *) ;; esac \
    && npm run build

FROM node:18-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
EXPOSE 3000
CMD ["node", "server.js"]
