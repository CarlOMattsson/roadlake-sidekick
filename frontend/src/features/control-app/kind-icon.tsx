import type { ReactNode } from "react";
import { CycleIcon, FolderIcon } from "../mcp-apps/ui/icons";

/** The glyph of a record kind, drawn small beside a table row's title; the kind's name is its accessible name. */
function glyphOf(kind: string): ReactNode {
  switch (kind) {
    case "project":
      return <FolderIcon />;
    case "process":
    case "process_run":
      return <CycleIcon />;
    case "task":
    case "step":
    case "action":
    case "ai_step_run":
      return (
        <Outline>
          <circle cx="12" cy="12" r="9" />
          <path d="M8 12.5l2.7 2.7L16 9.5" />
        </Outline>
      );
    case "contact":
    case "contact_alias":
    case "contact_alias_removed":
    case "contact_link":
    case "contact_task_link":
    case "contact_project_link":
      return (
        <Outline>
          <circle cx="12" cy="8" r="3.5" />
          <path d="M5 20a7 7 0 0 1 14 0" />
        </Outline>
      );
    case "journal_entry":
      return (
        <Outline>
          <path d="M6 4h12v16H6z" />
          <path d="M9 9h6M9 13h6" />
        </Outline>
      );
    case "shopping_item":
    case "shopping_list":
      return (
        <Outline>
          <path d="M6 8h12l-1 12H7z" />
          <path d="M9 8a3 3 0 0 1 6 0" />
        </Outline>
      );
    default:
      return (
        <Outline>
          <circle cx="12" cy="12" r="3" />
        </Outline>
      );
  }
}

function Outline({ children }: { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="24"
      height="24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

/** A kind's glyph at 16 px in the muted colour (control.css .control-kind), named by `name` for assistive technology. */
export function KindIcon({ kind, name }: { kind: string; name: string }) {
  return (
    <span className="control-kind" role="img" aria-label={name}>
      {glyphOf(kind)}
    </span>
  );
}
