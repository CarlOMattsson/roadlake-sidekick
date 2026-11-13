import type { RowQueue } from "../../../mcp-apps/ui/row-queue";
import type { WorkLabels } from "../../shared/labels";
import type { WorkFrame } from "../../transport/transport";
import type { RowOffers } from "./use-row-offers";
import type { RowMenuState } from "./use-row-menu";
import type { RowState } from "./use-row-state";
import type { NoticeSource } from "./agenda-notice";
import type { RowWrites } from "./use-row-writes";

/** What every row of the agenda needs from the view: its labels, the state of its rows, what the host offers, and its writes. */
export type AgendaRowContext = {
  labels: WorkLabels;
  now: Date;
  /** A read or bulk write is running: the controls are off. */
  disabled: boolean;
  /** False when the host serves no Status tab: a ticked row then says only "Done". */
  boardAvailable: boolean;
  /** The key of the row the keys have selected. */
  selected: string | undefined;
  rows: RowState;
  rowQueue: RowQueue;
  menu: RowMenuState;
  offers: RowOffers;
  writes: RowWrites;
  onOpen: (frame: WorkFrame) => void;
  /** The last notice and its buttons: a row shows the one that belongs to it. */
  notice: NoticeSource;
  /** The ids (lower case) of the Tasks whose tick waits in the phone's outbox: drawn done, "Skickas…". */
  sending: ReadonlySet<string>;
  /** The ids (lower case) of the Tasks this agenda draws done: their Steps say so instead of their dates. */
  doneTasks: ReadonlySet<string>;
};
