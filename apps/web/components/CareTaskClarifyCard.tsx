"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { Text } from "@astryxdesign/core/Text";

export interface CareTaskCandidate { id: string; title: string; status?: string; due_at?: string | null; task_type?: string; }

function formatDue(dueAt?: string | null): string | null {
  if (!dueAt) return null;
  const date = new Date(dueAt);
  if (Number.isNaN(date.getTime())) return null;
  return date.toLocaleString("zh-CN", { month: "numeric", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export default function CareTaskClarifyCard({ candidates, verb = "确认", disabled = false, onSelect }: { candidates: CareTaskCandidate[]; verb?: string; disabled?: boolean; onSelect: (candidate: CareTaskCandidate) => void; }) {
  if (!candidates.length) return null;
  return (
    <Card variant="yellow" padding={4} style={{ marginTop: 12 }}>
      <Badge label={`需要选择要${verb}的任务`} variant="warning" />
      <div className="clarify-grid">
        {candidates.map((candidate) => (
          <Button key={candidate.id} label={candidate.title} variant="secondary" size="lg" isDisabled={disabled} onClick={() => onSelect(candidate)} endContent={formatDue(candidate.due_at) ? <Text type="supporting">{formatDue(candidate.due_at)}</Text> : undefined} />
        ))}
      </div>
    </Card>
  );
}
