FROM node:20-alpine

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --omit=dev

COPY server.mjs caretask-params.mjs pi-events.mjs tool-policy.mjs ./

ENV PI_SIDECAR_HOST=0.0.0.0
ENV PI_SIDECAR_PORT=8787
ENV PI_ENABLE_TOOLS=1

EXPOSE 8787

HEALTHCHECK --interval=10s --timeout=3s --start-period=15s --retries=5 \
  CMD wget -qO- http://127.0.0.1:8787/health || exit 1

CMD ["node", "server.mjs"]
