FROM node:22.21.0-bookworm-slim
RUN npm install --global npm@11.16.0
ENV NEXT_TELEMETRY_DISABLED=1 \
    FORMA_API_ORIGIN=http://api:8000
WORKDIR /app

COPY package.json package-lock.json .npmrc ./
COPY apps/web/package.json apps/web/
RUN npm ci
COPY apps/web apps/web
COPY packages/assembly_view packages/assembly_view
RUN npm run build -w @forma/web

USER node
WORKDIR /app/apps/web
EXPOSE 3000
CMD ["/app/node_modules/.bin/next", "start", "--hostname", "0.0.0.0", "--port", "3000"]
