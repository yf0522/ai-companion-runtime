export default function SignalField({ className = "" }: { className?: string }) {
  return (
    <div className={`signal-field ${className}`} aria-hidden="true">
      <span className="signal-field-line" />
      <span className="signal-field-line" />
      <span className="signal-field-line" />
      <span className="signal-field-node" />
      <span className="signal-field-node" />
      <span className="signal-field-node" />
    </div>
  );
}
