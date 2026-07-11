"use client";

import { useCallback, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowLeft, ArrowUpRight, Clock3, Search, ShieldCheck, UserRoundCheck } from "lucide-react";
import RoleShell from "@/components/RoleShell";
import { EmptyState, ErrorState, LoadingState, StatusBanner } from "@/components/SurfaceStates";
import {
  ApiError,
  fetchHouseholdReadiness,
  fetchOperatorHouseholds,
  type HouseholdReadinessResponse,
  type OperatorHouseholdItem,
  userFacingApiError,
} from "@/lib/api-client";
import styles from "../../operator.module.css";

function formatTime(value: string | null | undefined): string {
  if (!value) return "未记录";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "时间待确认" : date.toLocaleString("zh-CN");
}

function evidenceSummary(value: unknown): string {
  if (!value || typeof value !== "object") return "未记录";
  const entries = Object.entries(value as Record<string, unknown>);
  if (entries.length === 0) return "未记录";
  return entries.map(([key, item]) => `${key}: ${String(item)}`).join(" · ");
}

export default function OperatorReadinessWorkspace({ initialHouseholdId }: { initialHouseholdId: string | null }) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [households, setHouseholds] = useState<OperatorHouseholdItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(initialHouseholdId);
  const [readiness, setReadiness] = useState<HouseholdReadinessResponse | null>(null);
  const [loadingDirectory, setLoadingDirectory] = useState(true);
  const [loadingReadiness, setLoadingReadiness] = useState(Boolean(initialHouseholdId));
  const [error, setError] = useState<string | null>(null);

  const handleAuthError = useCallback((err: unknown): boolean => {
    if (err instanceof ApiError && err.status === 401) {
      router.push("/login");
      return true;
    }
    return false;
  }, [router]);

  const loadDirectory = useCallback(async (search = "") => {
    setLoadingDirectory(true);
    setError(null);
    try {
      const data = await fetchOperatorHouseholds(search);
      setHouseholds(data.items);
    } catch (err) {
      if (!handleAuthError(err)) setError(userFacingApiError(err, "家庭目录加载失败，请稍后重试。"));
    } finally {
      setLoadingDirectory(false);
    }
  }, [handleAuthError]);

  const loadReadiness = useCallback(async (householdId: string) => {
    setLoadingReadiness(true);
    setError(null);
    try {
      setReadiness(await fetchHouseholdReadiness(householdId));
    } catch (err) {
      if (!handleAuthError(err)) setError(userFacingApiError(err, "家庭就绪状态加载失败，请稍后重试。"));
    } finally {
      setLoadingReadiness(false);
    }
  }, [handleAuthError]);

  useEffect(() => { void loadDirectory(); }, [loadDirectory]);
  useEffect(() => {
    if (selectedId) void loadReadiness(selectedId);
    else setReadiness(null);
  }, [loadReadiness, selectedId]);

  function selectHousehold(id: string) {
    setSelectedId(id);
    router.replace(`/ops/households/readiness?household_id=${encodeURIComponent(id)}`);
  }

  function clearSelection() {
    setSelectedId(null);
    setReadiness(null);
    router.replace("/ops/households/readiness");
  }

  const selectedHousehold = households.find((item) => item.id === selectedId);
  const readyCount = readiness?.checks.filter((check) => check.status === "ready").length ?? 0;
  const blockedCount = readiness?.checks.filter((check) => check.status !== "ready").length ?? 0;

  return (
    <RoleShell role="operator" title="家庭就绪" subtitle="先选择家庭，再查看阻塞项、责任人和证据">
      <div className={styles.workspace}>
        <header className={styles.pageHeader}>
          <div>
            <h2>{selectedId ? selectedHousehold?.name || "家庭就绪详情" : "家庭目录"}</h2>
            <p>{selectedId ? `长者：${selectedHousehold?.elder_name || "姓名未记录"}。每个阻塞项都给出责任人、下一步和验证时间。` : "搜索家庭或长者姓名，进入对应的上线就绪检查。"}</p>
          </div>
          {selectedId && <button type="button" className={styles.contextLink} onClick={clearSelection}><ArrowLeft size={15} />返回家庭目录</button>}
        </header>

        {error && <ErrorState description={error} onRetry={() => selectedId ? loadReadiness(selectedId) : loadDirectory(query)} />}

        {!selectedId ? (
          <>
            <form className={`${styles.toolbar} ${styles.toolbarCompact}`} onSubmit={(event) => { event.preventDefault(); void loadDirectory(query); }}>
              <label className={styles.searchControl}>
                <span className="sr-only">搜索家庭</span>
                <Search className={styles.searchIcon} size={16} aria-hidden="true" />
                <input className={`${styles.searchField} ${styles.searchFieldWithIcon}`} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="家庭名称或长者用户名" />
              </label>
              <button type="submit" className={styles.primaryButton}>搜索</button>
            </form>
            {loadingDirectory ? (
              <LoadingState label="正在加载家庭目录" />
            ) : households.length === 0 ? (
              <EmptyState title="没有找到家庭" description={query ? "调整搜索词后重试。" : "系统中还没有可供运营查看的活跃家庭。"} />
            ) : (
              <section className={styles.householdList} aria-label="家庭目录">
                {households.map((household) => (
                  <article key={household.id} className={styles.householdRow}>
                    <div><h3>{household.name || "未命名家庭"}</h3><p>家庭 {household.id.slice(0, 8)}… · {household.status === "active" ? "活跃" : household.status}</p></div>
                    <div><strong><UserRoundCheck size={14} /> {household.elder_name || "长者姓名未记录"}</strong><p>更新于 {formatTime(household.updated_at)}</p></div>
                    <button type="button" className={styles.compactButton} onClick={() => selectHousehold(household.id)}>查看就绪 <ArrowUpRight size={14} /></button>
                  </article>
                ))}
              </section>
            )}
          </>
        ) : loadingReadiness ? (
          <LoadingState label="正在加载家庭就绪检查" />
        ) : readiness ? (
          <>
            <StatusBanner tone={readiness.status === "ready" ? "success" : "warning"} title={readiness.status === "ready" ? "家庭已就绪" : "家庭仍有阻塞项"}>
              {readiness.next_action || "所有必需项均有可验证证据。"}
            </StatusBanner>
            <section className={styles.summaryStrip} aria-label="家庭就绪统计">
              <div><span>整体状态</span><strong>{readiness.status === "ready" ? "已就绪" : "有阻塞"}</strong></div>
              <div><span>已就绪检查</span><strong>{readyCount}</strong></div>
              <div><span>阻塞检查</span><strong>{blockedCount}</strong></div>
              <div><span>最近验证</span><strong className={styles.summaryTimestamp}>{formatTime(readiness.updated_at)}</strong></div>
            </section>
            <section className={styles.readinessList} aria-label="就绪检查列表">
              {readiness.checks.map((check) => (
                <article key={check.key} className={styles.readinessRow} data-status={check.status}>
                  <div><h3>{check.label}</h3><p>{check.detail || "没有补充说明。"}</p></div>
                  <div><strong><UserRoundCheck size={14} /> {check.owner || "负责人未记录"}</strong><p><Clock3 size={13} /> 证据时间 {formatTime(check.evidence_at)}</p></div>
                  <div><strong>{check.status === "ready" ? "证据已满足" : check.action || "下一步未记录"}</strong><p>{evidenceSummary(check.evidence)}</p></div>
                </article>
              ))}
            </section>
          </>
        ) : (
          <EmptyState title="暂无就绪数据" description="服务端返回家庭检查后会显示责任人与证据。" />
        )}
      </div>
    </RoleShell>
  );
}
