from prometheus_client import Counter, Gauge, Histogram

# Core latency metrics
TTFT_SECONDS = Histogram(
    "companion_ttft_seconds",
    "Time to first token",
    buckets=[0.1, 0.3, 0.5, 1.0, 2.0, 5.0],
)

TOTAL_LATENCY_SECONDS = Histogram(
    "companion_total_latency_seconds",
    "Total request latency",
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

# Model metrics
MODEL_CALLS_TOTAL = Counter(
    "companion_model_calls_total",
    "Total model calls",
    ["provider", "model", "status"],
)

TOKENS_TOTAL = Counter(
    "companion_tokens_total",
    "Total tokens used",
    ["provider", "direction"],  # direction: prompt / completion
)

# Tool metrics
TOOL_CALLS_TOTAL = Counter(
    "companion_tool_calls_total",
    "Total tool calls",
    ["tool", "status"],
)

# Risk metrics
RISK_DETECTIONS_TOTAL = Counter(
    "companion_risk_detections_total",
    "Total risk detections",
    ["level"],
)

# Connection metrics
WS_CONNECTIONS = Gauge(
    "companion_ws_connections",
    "Current WebSocket connections",
)

# Memory metrics
MEMORY_RECALL_SECONDS = Histogram(
    "companion_memory_recall_seconds",
    "Memory recall latency",
    buckets=[0.05, 0.1, 0.2, 0.3, 0.5],
)

MEMORY_LIFECYCLE_TOTAL = Counter(
    "companion_memory_lifecycle_total",
    "Memory lifecycle events",
    ["event", "purpose", "status"],
)

MEMORY_EMBEDDINGS_TOTAL = Counter(
    "companion_memory_embeddings_total",
    "Memory embedding lifecycle events",
    ["model", "state"],
)

REFLECTION_PROPOSALS_TOTAL = Counter(
    "companion_reflection_proposals_total",
    "Reflection proposal lifecycle events",
    ["target_type", "status"],
)

FAMILY_SUMMARY_TOTAL = Counter(
    "companion_family_summary_total",
    "Family summary requests by privacy boundary",
    ["summary_type", "status"],
)

QUEUE_DEPTH = Gauge(
    "companion_queue_depth",
    "Worker queue depth by queue",
    ["queue"],
)

DELIVERY_ATTEMPTS_TOTAL = Counter(
    "companion_delivery_attempts_total",
    "Reminder and notification delivery attempts",
    ["kind", "state"],
)

HOUSEHOLD_READINESS_TOTAL = Counter(
    "companion_household_readiness_total",
    "Household readiness evaluations by result",
    ["status"],
)

NOTIFICATION_WEBHOOK_RECEIPTS_TOTAL = Counter(
    "companion_notification_webhook_receipts_total",
    "Signed notification webhook receipt verification results",
    ["status"],
)

AUDIT_COMPLETENESS = Gauge(
    "companion_audit_completeness_ratio",
    "Ratio of policy-triggered care and safety actions with required audit records",
    ["window"],
)

DEVICE_HEALTH = Gauge(
    "companion_device_health",
    "Device health by status",
    ["status"],
)

EVIDENCE_MANIFEST_TOTAL = Counter(
    "companion_evidence_manifest_total",
    "Evidence manifest generation results",
    ["environment", "status"],
)

PLATFORM_READINESS_EVALUATIONS_TOTAL = Counter(
    "companion_platform_readiness_evaluations_total",
    "Platform readiness evaluations by aggregate state",
    ["status"],
)

PLATFORM_READINESS_CHECKS_TOTAL = Counter(
    "companion_platform_readiness_checks_total",
    "Platform readiness check results by stable check and state",
    ["check_id", "status"],
)

PLATFORM_READINESS_CHECK_DURATION_SECONDS = Histogram(
    "companion_platform_readiness_check_duration_seconds",
    "Platform readiness check duration by stable check and state",
    ["check_id", "status"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 1.5, 2.0, 2.5],
)


def record_platform_readiness(payload: dict) -> None:
    """Record readiness evidence with fixed, low-cardinality labels only."""
    canonical_states = {"ready", "degraded", "unsafe_to_serve"}
    stable_check_ids = {
        "public_api_ws_config",
        "risk_policy",
        "database",
        "redis",
        "migration_heads",
        "notification_provider",
        "device_identity",
        "worker_heartbeat",
    }
    aggregate = payload.get("status")
    aggregate_label = aggregate if aggregate in canonical_states else "unsafe_to_serve"
    PLATFORM_READINESS_EVALUATIONS_TOTAL.labels(status=aggregate_label).inc()

    checks = payload.get("checks")
    if not isinstance(checks, dict):
        return
    for raw_check_id, raw_check in checks.items():
        check_id = raw_check_id if raw_check_id in stable_check_ids else "unknown"
        check = raw_check if isinstance(raw_check, dict) else {}
        state = check.get("status")
        state_label = state if state in canonical_states else "unsafe_to_serve"
        duration_ms = check.get("duration_ms")
        duration_seconds = (
            max(0.0, float(duration_ms)) / 1000
            if isinstance(duration_ms, (int, float)) and not isinstance(duration_ms, bool)
            else 0.0
        )
        PLATFORM_READINESS_CHECKS_TOTAL.labels(check_id=check_id, status=state_label).inc()
        PLATFORM_READINESS_CHECK_DURATION_SECONDS.labels(
            check_id=check_id,
            status=state_label,
        ).observe(duration_seconds)

# Cost metrics
COST_CENTS_TOTAL = Counter(
    "companion_cost_cents_total",
    "Total cost in cents",
    ["provider"],
)
