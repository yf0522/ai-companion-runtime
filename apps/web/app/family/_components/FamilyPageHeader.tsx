import type { ReactNode } from "react";
import styles from "../family.module.css";

export default function FamilyPageHeader({
  context,
  title,
  description,
  action,
}: {
  context: string;
  title: string;
  description: string;
  action?: ReactNode;
}) {
  return (
    <header className={styles.pageHeader}>
      <div>
        <p>{context}</p>
        <h2>{title}</h2>
        <span>{description}</span>
      </div>
      {action && <div className={styles.pageHeaderAction}>{action}</div>}
    </header>
  );
}

