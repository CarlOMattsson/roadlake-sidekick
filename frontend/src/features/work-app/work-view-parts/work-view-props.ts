import type { RoomTarget } from "../../mcp-apps/room-types";
import type { AgendaControls } from "../agenda";
import type { CardLabels } from "../card-labels";
import type { InlineSummaryLabels } from "../inline-summary-labels";
import type { WorkLabels } from "../labels";
import type { WorkFrame, WorkTransport } from "../transport";

/** The props of WorkView: both hosts use the same UI, and the transport alone decides how data is read. */
export type WorkViewProps = {
  transport: WorkTransport;
  initial?: WorkFrame;
  labels: WorkLabels;
  /** Labels for the compact cards; the host passes the set for its locale. */
  cardLabels?: CardLabels;
  /** Labels for the inline Task and Project summary; the host passes the set for its locale. */
  inlineLabels?: InlineSummaryLabels;
  /**
   * Requests fullscreen for a work_changes card, the board summary, a root Task or Project summary,
   * and the agenda, Contact list summaries. Present only when the host can show fullscreen and the
   * view is not already there; a board, a root Task, a root Project, a root agenda or a root Contact
   * list is then an inline summary. Absent otherwise, which shows the full view.
   */
  fullscreen?: () => void;
  /** True while the host answers the fullscreen request; the work_changes card's Open is busy then. */
  opening?: boolean;
  /** Sends a short model-context line for the shown board summary; absent without host support. */
  onModelContext?: (summary: string) => void;
  /** Turns on the fullscreen keyboard shortcuts of the views; only a fullscreen host passes true. */
  shortcuts?: boolean;
  /**
   * Shows the app name above the view. The fullscreen shell passes false: its tab strip already says
   * where the user is, so the name stays only as a visually hidden h1 for assistive technology.
   */
  chrome?: boolean;
  /** The agenda's filter text and read-again request, kept by the fullscreen shell; see AgendaControls. */
  agendaControls?: AgendaControls;
  /** Called with the depth of the navigation stack whenever it changes (1 at the list, more when a Task is open). */
  onStackDepth?: (depth: number) => void;
  /**
   * Opens a Journal entry linked to a Contact. Absent: the Contact shows no Journal section. Only a host
   * that can route to another room passes it; the entry's text is never sent to the model.
   */
  onOpenJournalEntry?: (entry: { id: string; title: string }) => void;
  /** Opens a mailto:, tel: or https: link through the host (bridge openLink). Absent: a plain link. */
  onOpenLink?: (url: string) => void;
  /**
   * Given by a host that routes (the app shell in the full view): opening a Task, a Project or a
   * Contact asks the shell to show it, one step on the shell's stack, instead of pushing on this view's
   * own stack. The view then has no Back of its own and no "All contacts" link, because the shell's
   * one Back leads out. Absent: the view navigates inside itself, with its own Back.
   */
  onRoute?: (target: RoomTarget) => void;
  /**
   * Whether the host can answer a tool (RoomTransport.supportsTool). Absent: every tool. The Task's Project is
   * a link only when get_project is answered; otherwise its name is shown by the meta line alone.
   */
  supportsTool?: (name: string) => boolean;
  /** A new value reads the open record or list again in place; the view, tab, filters and typed text stay. */
  refreshKey?: number;
  /** False when the host serves no Status tab (availableViews leaves it out); the agenda then points at no such view. Absent: true. */
  boardAvailable?: boolean;
  /** The Projects tab's search text (fullscreen tab row). Given, the hierarchy shows no filter field of its own. */
  hierarchyQuery?: string;
};
