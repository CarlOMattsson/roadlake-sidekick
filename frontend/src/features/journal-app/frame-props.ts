import type { JournalLabels } from "./labels";
import type { JournalTransport } from "./transport";

/** What every frame of the journal view gets: the transport, the labels and the move count that decides focus. */
export type FrameProps = {
  transport: JournalTransport;
  labels: JournalLabels;
  moves: number;
};
export type LoadPhase = "loading" | "ready" | "forbidden" | "error";
