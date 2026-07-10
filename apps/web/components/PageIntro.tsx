import { Badge } from "@astryxdesign/core/Badge";

export default function PageIntro({ kicker, title, description, action, tone = "teal" }: { kicker: string; title: string; description: string; action?: React.ReactNode; tone?: "teal" | "orange" | "red" | "neutral"; }) {
  return (
    <section className="page-intro">
      <div>
        <Badge label={kicker} variant={tone} />
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
      {action && <div>{action}</div>}
    </section>
  );
}
