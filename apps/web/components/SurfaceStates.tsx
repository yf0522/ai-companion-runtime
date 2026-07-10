"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Card } from "@astryxdesign/core/Card";
import { EmptyState as AstryxEmptyState } from "@astryxdesign/core/EmptyState";
import { Heading } from "@astryxdesign/core/Heading";
import { Icon } from "@astryxdesign/core/Icon";
import { Spinner } from "@astryxdesign/core/Spinner";
import { Text } from "@astryxdesign/core/Text";
import { AlertTriangle, CheckCircle2, CircleAlert, Inbox } from "lucide-react";

type SurfaceTone = "info" | "success" | "warning" | "critical" | "offline";

const toneConfig = {
  info: { variant: "cyan", icon: CircleAlert },
  success: { variant: "green", icon: CheckCircle2 },
  warning: { variant: "yellow", icon: AlertTriangle },
  critical: { variant: "red", icon: AlertTriangle },
  offline: { variant: "gray", icon: CircleAlert },
} as const;

export function LoadingState({ label = "正在加载" }: { label?: string }) {
  return <Card variant="transparent" padding={5}><Spinner size="lg" shade="subtle" label={label} /></Card>;
}

export function EmptyState({ title, description, action }: { title: string; description: string; action?: React.ReactNode }) {
  return <AstryxEmptyState icon={<Icon icon={Inbox} color="secondary" />} title={title} description={description} actions={action} />;
}

export function ErrorState({ title = "加载失败", description, onRetry }: { title?: string; description: string; onRetry?: () => void }) {
  return (
    <Card variant="red" padding={5} role="alert">
      <div style={{ display: "grid", gap: 10 }}>
        <Icon icon={AlertTriangle} color="error" />
        <Heading level={3}>{title}</Heading>
        <Text color="secondary">{description}</Text>
        {onRetry && <div><Button label="重试" variant="secondary" onClick={onRetry} /></div>}
      </div>
    </Card>
  );
}

export function StatusBanner({ tone = "info", title, children }: { tone?: SurfaceTone; title: string; children?: React.ReactNode }) {
  const config = toneConfig[tone];
  return (
    <Card variant={config.variant} padding={4}>
      <div style={{ display: "flex", alignItems: "flex-start", gap: 12 }}>
        <Icon icon={config.icon} color={tone === "critical" ? "error" : tone === "warning" ? "warning" : tone === "success" ? "success" : "secondary"} />
        <div style={{ minWidth: 0 }}>
          <Badge label={title} variant={tone === "critical" ? "error" : tone === "warning" ? "warning" : tone === "success" ? "success" : "neutral"} />
          {children && <Text display="block" type="supporting" style={{ marginTop: 8 }}>{children}</Text>}
        </div>
      </div>
    </Card>
  );
}
