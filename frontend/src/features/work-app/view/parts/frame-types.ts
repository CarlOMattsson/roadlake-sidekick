import type { WorkLabels } from "../../shared/labels";
import {
  writeFailure,
  type WorkFrame,
  type WorkTransport,
} from "../../transport/transport";

/** Props every detail frame (Task, Contact, Project) takes from WorkView. */
export type FrameProps = {
  transport: WorkTransport;
  labels: WorkLabels;
  moves: number;
  /** `label` is the record's short name (a title), for the host's model-context line when the frame routes. */
  onOpen: (frame: WorkFrame, label?: string) => void;
  /** True when a Contact list frame is already in the stack, so "All contacts" is not offered. */
  contactsOpen?: boolean;
  /** A new value reads the record again in place (nothing the user typed or opened is reset). */
  refreshKey?: number;
  /**
   * The parent to go back to. A detail frame draws its own Back row with it, so the view's actions (pen, ⋯)
   * sit at the right of that row (design system §3, Tillbakarad). Without it the frame is the root.
   */
  back?: BackTarget;
};
/** The parent of a detail frame: its name for "‹ {label}" and the step back. */
export type BackTarget = { label: string; onBack: () => void };
/** `gone`: the record was read and the server says it no longer exists, so no retry is offered. */
export type Phase = "loading" | "ready" | "error" | "gone";
export type ListPhase = "loading" | "ready" | "forbidden" | "error";
export type MorePhase = "idle" | "busy" | "failed";
/** What the last write or reload did. `failed` names the action so retry runs it again. */
export type WriteState =
  | { kind: "idle" }
  | { kind: "busy" }
  | { kind: "saved" }
  | { kind: "conflict" }
  | { kind: "forbidden" }
  | { kind: "invalid" }
  | { kind: "notFound" }
  | { kind: "failed"; action: "save" | "reload" | "write" };

/** `write` is a Contact action outside the editor (alias, archive); its retry runs the action again. */
export function failureState(
  error: unknown,
  action: "save" | "reload" | "write",
): WriteState {
  const kind = writeFailure(error);
  if (kind === "conflict") return { kind: "conflict" };
  if (kind === "forbidden") return { kind: "forbidden" };
  if (kind === "invalid") return { kind: "invalid" };
  if (kind === "not_found") return { kind: "notFound" };
  return { kind: "failed", action };
}

/**
 * The phase after a failed read: a record the server says is gone (not_found) can never be read, so it is
 * `gone` and shows its calm line; any other failure is an `error` with Try again.
 */
export function readFailurePhase(error: unknown): "gone" | "error" {
  return writeFailure(error) === "not_found" ? "gone" : "error";
}
