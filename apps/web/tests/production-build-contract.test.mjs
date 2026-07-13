import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

test("production web image receives required public build-time values", () => {
  const dockerfile = readFileSync(new URL("../Dockerfile", import.meta.url), "utf8");
  const productionCompose = readFileSync(
    new URL("../../../infra/docker-compose.production.yml", import.meta.url),
    "utf8",
  );
  const workflow = readFileSync(
    new URL("../../../.github/workflows/production-contracts.yml", import.meta.url),
    "utf8",
  );
  const runbook = readFileSync(
    new URL("../../../docs/runbooks/production-deployment.md", import.meta.url),
    "utf8",
  );
  const runnerStage = dockerfile.slice(dockerfile.indexOf("FROM node:18-alpine AS runner"));
  const expectedNames = [
    "NEXT_PUBLIC_API_URL",
    "NEXT_PUBLIC_WS_URL",
    "NEXT_PUBLIC_AGENT_RUNTIME",
  ];
  for (const name of expectedNames) {
    assert.ok(dockerfile.includes(`ARG ${name}`));
    assert.ok(dockerfile.includes(`test -n "$${name}"`));
    assert.ok(productionCompose.includes(name + ": ${" + name + ":?"));
    assert.ok(workflow.includes(`'${name}=`));
  }
  for (const service of [
    "api", "web", "postgres", "redis", "minio", "jaeger", "prometheus", "grafana",
  ]) {
    assert.match(productionCompose, new RegExp(`${service}:[\\s\\S]*?ports: !override \\[\\]`));
  }
  assert.match(productionCompose, /web:[\s\S]*environment:[\s\S]*NEXT_PUBLIC_API_URL:/);
  assert.ok(dockerfile.includes('case "$NEXT_PUBLIC_API_URL" in'));
  assert.ok(dockerfile.includes('case "$NEXT_PUBLIC_WS_URL" in'));
  assert.ok(dockerfile.includes("https://*"));
  assert.ok(dockerfile.includes("wss://*"));
  assert.ok(workflow.includes("trap 'rm -f .env.production"));
  assert.ok(workflow.includes("docker compose --env-file .env.production"));
  assert.ok(workflow.includes("config --format json"));
  assert.ok(workflow.includes("build web"));
  assert.ok(workflow.includes("for service in config[\"services\"].values()"));
  assert.ok(workflow.includes("Invalid public URL values are rejected"));
  assert.ok(workflow.includes("if docker build"));
  assert.ok(workflow.includes("http://127.0.0.1"));
  assert.ok(workflow.includes("*build_args.values()"));
  assert.ok(workflow.includes("*runtime_environment.values()"));
  assert.ok(runbook.includes("docker compose --env-file .env.production"));
  assert.ok(runbook.includes("service-level `env_file`"));
  assert.ok(runbook.includes("build-time inlined"));
  assert.ok(runbook.includes("CREATE INDEX CONCURRENTLY"));
  assert.ok(!runnerStage.includes("NEXT_PUBLIC_API_URL=$NEXT_PUBLIC_API_URL"));
  assert.ok(!runnerStage.includes("NEXT_PUBLIC_WS_URL=$NEXT_PUBLIC_WS_URL"));
});
