import { useEffect, useRef, useState } from "react";
import {
  isForbidden,
  type JournalDraft,
  type JournalSource,
  type JournalTransport,
} from "../transport";

export type DraftRead = { draft: JournalDraft; source: JournalSource };
type Phase = "loading" | "ready" | "forbidden" | "error";

/**
 * Loads the draft when the frame opens (and again on retry). The owner opened the draft to review it, so the
 * app asks for its content; `onRead` applies what came back. A newer load or an unmount makes an older answer
 * stale, and a stale answer is dropped.
 */
export function useDraftLoader(
  transport: JournalTransport,
  id: string,
  onRead: (read: DraftRead) => void,
) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [attempt, setAttempt] = useState(0);
  const ticket = useRef(0);
  // The effect below must not restart when the caller's handler changes; it uses the latest one.
  const onReadRef = useRef(onRead);
  useEffect(() => {
    onReadRef.current = onRead;
  });

  useEffect(() => {
    const marker = ticket;
    const current = ++marker.current;
    transport
      .getDraft(id)
      .then((read) => {
        if (current !== marker.current) return;
        onReadRef.current(read);
        setPhase("ready");
      })
      .catch((error: unknown) => {
        if (current !== marker.current) return;
        setPhase(isForbidden(error) ? "forbidden" : "error");
      });
    return () => {
      marker.current++;
    };
  }, [transport, id, attempt]);

  function retry() {
    setPhase("loading");
    setAttempt((n) => n + 1);
  }
  return { phase, retry };
}
