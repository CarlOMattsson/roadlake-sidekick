/** The meta line of a record whose write waits in the phone's outbox: "Väntar…", in the muted meta type. */
export function WaitingLine({
  text,
  className = "work-card-meta",
}: {
  text: string;
  className?: string;
}) {
  return (
    <p className={className}>
      <span className="sk-queued">{text}</span>
    </p>
  );
}
