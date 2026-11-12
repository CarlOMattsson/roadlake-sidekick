import { useEffect, useRef, useState, type RefObject } from "react";

export type Confirm = "reject" | "finalize" | undefined;

/**
 * The finalize/reject confirmation and its focus: Yes takes focus when the confirmation opens, and closing it
 * returns focus to the button that opened it.
 */
export function useDraftConfirm() {
  const [confirm, setConfirm] = useState<Confirm>();
  const confirmYes = useRef<HTMLButtonElement>(null);
  const finalizeButton = useRef<HTMLButtonElement>(null);
  const rejectButton = useRef<HTMLButtonElement>(null);
  const refocus = useRef<RefObject<HTMLButtonElement | null> | undefined>(
    undefined,
  );

  useEffect(() => {
    if (confirm) confirmYes.current?.focus();
    else if (refocus.current) {
      refocus.current.current?.focus();
      refocus.current = undefined;
    }
  }, [confirm]);

  function ask(kind: "reject" | "finalize") {
    refocus.current = kind === "reject" ? rejectButton : finalizeButton;
    setConfirm(kind);
  }
  function close() {
    setConfirm(undefined);
  }
  return { confirm, ask, close, confirmYes, finalizeButton, rejectButton };
}
