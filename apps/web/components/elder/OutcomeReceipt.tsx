import { Check, CircleAlert, Clock3, Info, LoaderCircle } from "lucide-react";
import type { ToolChip } from "@/stores/chatStore";
import { outcomeReceiptForTool } from "./outcome-receipt";
import styles from "./ElderProduct.module.css";

const icons = {
  loading: LoaderCircle,
  info: Info,
  success: Check,
  pending: Clock3,
  error: CircleAlert,
};

export default function OutcomeReceipt({ tool }: { tool: ToolChip }) {
  const receipt = outcomeReceiptForTool(tool);
  const ReceiptIcon = icons[receipt.tone];

  return (
    <div className={styles.outcomeReceipt} data-tone={receipt.tone} role="status">
      <span className={styles.outcomeIcon} aria-hidden="true"><ReceiptIcon size={17} /></span>
      <span>
        <strong>{receipt.title}</strong>
        <small>{receipt.detail}</small>
      </span>
    </div>
  );
}
