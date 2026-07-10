export default function PageIntro({
  title,
  description,
  action,
}: {
  title: string;
  description: string;
  action?: React.ReactNode;
}) {
  return (
    <section className="page-intro">
      <div>
        <h2>{title}</h2>
        <p>{description}</p>
      </div>
      {action && <div className="page-intro-action">{action}</div>}
    </section>
  );
}
