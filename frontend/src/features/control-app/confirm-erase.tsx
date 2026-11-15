import { useEffect, useRef } from "react";

/**
 * The question before anything is removed for good, inline where the owner pressed the button. It takes the focus when
 * it opens, so a screen reader reads it and the buttons are next in order. Cancel comes first in the DOM, so Tab reaches
 * the safe button before the red one (the red one keeps its place on the left); Escape cancels too. While the removal
 * is on its way (`busy`) neither button answers.
 */
export function ConfirmErase({
  question,
  yes,
  no,
  busy,
  onYes,
  onNo,
}: {
  question: string;
  yes: string;
  no: string;
  busy: boolean;
  onYes: () => void;
  onNo: () => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const cancel = useRef(onNo);
  const waiting = useRef(busy);
  useEffect(() => {
    cancel.current = onNo;
    waiting.current = busy;
  }, [onNo, busy]);
  useEffect(() => {
    const node = root.current;
    if (!node) return undefined;
    node.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key !== "Escape" || waiting.current) return;
      event.stopPropagation();
      cancel.current();
    }
    node.addEventListener("keydown", onKey);
    return () => node.removeEventListener("keydown", onKey);
  }, []);
  return (
    <div
      ref={root}
      tabIndex={-1}
      role="group"
      aria-label={question}
      className="control-confirm"
    >
      <p className="control-confirm-title">{question}</p>
      <div className="control-confirm-actions">
        <button
          type="button"
          className="sk-btn--quiet"
          disabled={busy}
          onClick={onNo}
        >
          {no}
        </button>
        <button
          type="button"
          className="sk-btn--danger control-confirm-yes"
          disabled={busy}
          onClick={onYes}
        >
          {yes}
        </button>
      </div>
    </div>
  );
}
