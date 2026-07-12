"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  BookOpenText,
  CheckCircle2,
  CircleHelp,
  Clock3,
  Gauge,
  RefreshCw,
  UserRound,
  Wrench,
} from "lucide-react";
import RoleShell from "@/components/RoleShell";
import { ErrorState, LoadingState } from "@/components/SurfaceStates";
import {
  ApiError,
  fetchOperatorPlatformReadiness,
} from "@/lib/api-client";
import {
  formatEvidenceAge,
  formatReadinessDuration,
  formatReadinessTime,
  mapPlatformReadiness,
  type PlatformReadinessCheckView,
  type PlatformReadinessView,
} from "../_lib/platform-readiness";
import styles from "../operator.module.css";

function verdictIcon(view: PlatformReadinessView) {
  if (view.state === "ready") return CheckCircle2;
  if (view.state === "stale") return Clock3;
  if (view.state === "unknown") return CircleHelp;
  return AlertTriangle;
}

function checkIcon(check: PlatformReadinessCheckView, evidenceState: PlatformReadinessView["evidenceState"]) {
  if (evidenceState === "stale") return Clock3;
  if (evidenceState === "unknown" || check.status === "unknown") return CircleHelp;
  if (check.status === "ready") return CheckCircle2;
  return AlertTriangle;
}

function statusMetric(view: PlatformReadinessView): string {
  if (view.state === "unknown") return "待确认";
  if (view.state === "stale") return "已过期";
  return view.statusLabel;
}

function readinessError(error: unknown): { title: string; description: string } {
  if (error instanceof ApiError && error.status === 403) {
    return {
      title: "没有平台诊断权限",
      description: "当前账号不是正式运营角色。平台状态不能视为正常，请切换到运营账号后重试。",
    };
  }
  if (error instanceof ApiError) {
    return {
      title: "平台证据读取失败",
      description: "服务返回了错误，当前状态不能视为可用。请重试；若持续失败，按平台就绪手册排查 API。",
    };
  }
  return {
    title: "无法连接平台诊断服务",
    description: "网络请求没有完成，当前状态不能视为可用。请检查本地服务或网络后重试。",
  };
}

export default function OpsPlatformPage() {
  const router = useRouter();
  const [view, setView] = useState<PlatformReadinessView | null>(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<{ title: string; description: string } | null>(null);

  const load = useCallback(async (manual = false) => {
    if (manual) setRefreshing(true);
    else setLoading(true);
    setError(null);
    try {
      const payload = await fetchOperatorPlatformReadiness();
      setView(mapPlatformReadiness(payload, new Date()));
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 401) {
        router.push("/login");
        return;
      }
      setView(null);
      setError(readinessError(caught));
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [router]);

  useEffect(() => { void load(); }, [load]);

  const VerdictIcon = view ? verdictIcon(view) : CircleHelp;

  return (
    <RoleShell role="operator" title="平台就绪" subtitle="运行依赖、证据时效与修复责任">
      <div className={styles.workspace}>
        <header className={styles.pageHeader}>
          <div>
            <h2>平台就绪控制台</h2>
            <p>判断平台是否可以承载照护服务，并把受限或阻断项交给明确负责人。家庭上线条件在独立工作区维护。</p>
          </div>
          <button
            type="button"
            className={styles.secondaryButton}
            onClick={() => void load(true)}
            disabled={loading || refreshing}
            aria-label="刷新平台就绪证据"
          >
            <RefreshCw size={16} aria-hidden="true" />
            {refreshing ? "正在刷新" : "刷新证据"}
          </button>
        </header>

        {loading && !view ? (
          <LoadingState label="正在检查平台运行依赖" />
        ) : error ? (
          <ErrorState title={error.title} description={error.description} onRetry={() => void load()} />
        ) : view ? (
          <>
            <section
              className={styles.platformVerdict}
              data-tone={view.tone}
              data-readiness-state={view.state}
              role="status"
              aria-live="polite"
              aria-label={`平台结论：${view.statusLabel}`}
            >
              <div className={styles.platformVerdictIcon} aria-hidden="true">
                <VerdictIcon size={24} />
              </div>
              <div className={styles.platformVerdictBody}>
                <span className={styles.contextLabel}>当前结论</span>
                <h3>{view.title}</h3>
                <p>{view.description}</p>
              </div>
              <div className={styles.platformVerdictMeta}>
                <span>证据时间</span>
                <strong>{formatReadinessTime(view.checkedAt)}</strong>
                <small>{view.evidenceState === "fresh" ? formatEvidenceAge(view.ageSeconds) : view.evidenceState === "stale" ? `已过期 · ${formatEvidenceAge(view.ageSeconds)}` : "时效待确认"}</small>
              </div>
            </section>

            <section className={styles.summaryStrip} aria-label="平台就绪证据摘要">
              <div><span>服务结论</span><strong>{statusMetric(view)}</strong></div>
              <div><span>证据时效</span><strong>{view.evidenceState === "fresh" ? "有效" : view.evidenceState === "stale" ? "已过期" : "待确认"}</strong></div>
              <div><span>检查项目</span><strong>{view.checkCount === null ? "未记录" : `${view.checkCount} 项`}</strong></div>
              <div><span>检查耗时</span><strong>{formatReadinessDuration(view.durationMs)}</strong></div>
            </section>

            <section className={styles.platformEvidence} aria-labelledby="platform-checks-heading">
              <div className={styles.platformSectionHeading}>
                <div>
                  <h3 id="platform-checks-heading">运行依赖与修复责任</h3>
                  <p>阻断和未知项优先排列；每项保留来源摘要、负责人、下一步和手册定位。</p>
                </div>
                <span>{view.evidenceState === "fresh" ? "本次检查" : view.evidenceState === "stale" ? "过期记录" : "待确认记录"}</span>
              </div>

              {view.checks.length === 0 ? (
                <div className={styles.platformNoChecks} role="alert">
                  没有可验证的检查项。当前平台状态不能视为可用，请刷新并检查就绪服务。
                </div>
              ) : (
                <div className={styles.platformCheckList} aria-label="平台检查项目">
                  {view.checks.map((check) => {
                    const CheckIcon = checkIcon(check, view.evidenceState);
                    const rowTone = view.evidenceState === "fresh" ? check.tone : view.evidenceState;
                    return (
                      <article key={check.id} className={styles.platformCheckRow} data-tone={rowTone}>
                        <div className={styles.platformCheckMain}>
                          <div className={styles.platformCheckTitle}>
                            <span className={styles.platformCheckIcon} aria-hidden="true"><CheckIcon size={18} /></span>
                            <div>
                              <h4>{check.label}</h4>
                              <code>{check.id}</code>
                            </div>
                            <span className={styles.platformCheckStatus}>
                              {view.evidenceState === "fresh" ? check.statusLabel : `上次记录 · ${check.statusLabel}`}
                            </span>
                          </div>
                          <p className={styles.platformCheckSummary}>{check.summary}</p>

                          {check.observed.length > 0 && (
                            <dl className={styles.platformObserved}>
                              {check.observed.map((item) => (
                                <div key={`${check.id}-${item.label}`}>
                                  <dt>{item.label}</dt>
                                  <dd>{item.value}</dd>
                                </div>
                              ))}
                            </dl>
                          )}

                          <dl className={styles.platformCheckFacts}>
                            <div><dt><Clock3 size={14} />检查耗时</dt><dd>{formatReadinessDuration(check.durationMs)}</dd></div>
                            <div><dt><UserRound size={14} />负责人</dt><dd>{check.owner}</dd></div>
                            <div><dt><BookOpenText size={14} />运行手册</dt><dd><code>{check.runbook}</code></dd></div>
                          </dl>
                        </div>
                        <div className={styles.platformNextAction}>
                          <span><Wrench size={15} aria-hidden="true" />下一步</span>
                          <strong>{check.nextAction}</strong>
                        </div>
                      </article>
                    );
                  })}
                </div>
              )}
            </section>

            <footer className={styles.platformBoundaryNote}>
              <Gauge size={17} aria-hidden="true" />
              <span>这里判断平台运行依赖；某个家庭能否上线，请前往<a href="/ops/households/readiness">家庭就绪</a>。</span>
            </footer>
          </>
        ) : null}
      </div>
    </RoleShell>
  );
}
