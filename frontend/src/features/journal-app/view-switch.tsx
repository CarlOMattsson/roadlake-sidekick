import { Segmented } from "../mcp-apps/ui/segmented";
import type { JournalLabels } from "./labels";

export type JournalViewMode = "day" | "week";

/**
 * The small switch between the day view and the calendar week view. Both views show it in the same place, at the end
 * of their week row, so it reads as one control and the shown view is the pressed one.
 */
export function JournalViewSwitch({
  value,
  labels: t,
  disabled,
  onChange,
}: {
  value: JournalViewMode;
  labels: JournalLabels;
  disabled?: boolean;
  onChange: (mode: JournalViewMode) => void;
}) {
  return (
    <div className="journal-view-switch">
      <Segmented
        label={t.viewSwitch}
        options={[
          { value: "day", label: t.viewDay },
          { value: "week", label: t.viewWeek },
        ]}
        value={value}
        disabled={disabled}
        onChange={onChange}
      />
    </div>
  );
}
