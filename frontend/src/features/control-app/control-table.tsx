import type { ReactNode } from "react";
import { ChevronRightIcon } from "../mcp-apps/ui/icons";
import { KindIcon } from "./kind-icon";
import "../mcp-apps/ui/row.css";

/** One row of a table: what it is, the middle cells in column order, and the action at the end. */
export type TableRow = {
  key: string;
  /** The record kind: its glyph stands before the title. */
  kind: string;
  /** The spoken name of the kind, the glyph's accessible name. */
  kindName: string;
  title: string;
  /** The cells between "What" and the action, in the order of the table's `heads`. */
  cells: readonly string[];
  action?: ReactNode;
  /** Full-width content under the row (a question, a failure). */
  below?: ReactNode;
  /** The row opens the record: it is a button over the whole row, with hover and a ›. Absent: plain text. */
  open?: () => void;
};

/** The rows of one day (or all rows, with no heading). */
export type TableGroup = { key: string; heading: string; rows: TableRow[] };

/**
 * A list as a table (desktop spec 3.5), drawn from 48rem (use-wide-frame.ts): the columns What (glyph and title), the
 * middle ones, and the action at the end. Markup is ARIA table roles on grid rows, so a row is one grid and its hover
 * tone (row.css `data-sk-row`) and its stretched open button work as on every other row. A row that opens the record is a
 * button of 44 high whose target reaches over the row; Undo and Restore stay their own buttons above it. A day heading is
 * the first row of its group. Texts and the data come from the caller.
 */
export function ControlTable({
  label,
  heads,
  actionHead,
  groups,
  chevron = false,
  wideAction = false,
}: {
  label: string;
  /** The column heads in order, "What" first; the action's head follows them (`actionHead`). */
  heads: readonly [string, ...string[]];
  actionHead: string;
  groups: readonly TableGroup[];
  /** Reserve the column of the › (a table whose rows may open). */
  chevron?: boolean;
  /** The action column holds two buttons (Restore and Delete permanently) and is as wide as they need. */
  wideAction?: boolean;
}) {
  const [what, ...middle] = heads;
  return (
    <div
      role="table"
      aria-label={label}
      className="control-table"
      data-cols={middle.length}
      data-chevron={chevron ? "" : undefined}
      data-action={wideAction ? "wide" : undefined}
    >
      <div role="rowgroup">
        <div role="row" className="control-thead-row">
          <div role="columnheader">{what}</div>
          {middle.map((head) => (
            <div role="columnheader" key={head}>
              {head}
            </div>
          ))}
          <div role="columnheader">
            <span className="control-sr-only">{actionHead}</span>
          </div>
          {chevron ? <span aria-hidden="true" /> : null}
        </div>
      </div>
      {groups.map((group) => (
        <div role="rowgroup" key={group.key} className="control-tgroup">
          {group.heading ? (
            <div role="row" className="control-tday-row">
              <div role="rowheader" className="control-tday">
                {group.heading}
              </div>
            </div>
          ) : null}
          {group.rows.map((row) => (
            <div
              role="row"
              key={row.key}
              className="control-trow"
              data-sk-row={row.open ? "" : undefined}
            >
              <div role="cell" className="control-tcell control-tcell--what">
                {row.open ? (
                  <button
                    type="button"
                    className="control-topen"
                    onClick={row.open}
                  >
                    <KindIcon kind={row.kind} name={row.kindName} />
                    <span className="control-ttitle">{row.title}</span>
                  </button>
                ) : (
                  <>
                    <KindIcon kind={row.kind} name={row.kindName} />
                    <span className="control-ttitle">{row.title}</span>
                  </>
                )}
              </div>
              {row.cells.map((text, index) => (
                <div role="cell" className="control-tcell" key={index}>
                  {text}
                </div>
              ))}
              <div role="cell" className="control-tcell control-tcell--action">
                {row.action}
              </div>
              {chevron ? (
                <span className="control-tchev" aria-hidden="true">
                  {row.open ? <ChevronRightIcon /> : null}
                </span>
              ) : null}
              {row.below ? (
                <div role="cell" className="control-tbelow">
                  {row.below}
                </div>
              ) : null}
            </div>
          ))}
        </div>
      ))}
    </div>
  );
}
