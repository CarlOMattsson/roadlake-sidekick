import { Tabs } from "../mcp-apps/ui/tabs";
import type { JournalLabels } from "./labels";

export type JournalViewMode = "day" | "week";

/**
 * The switch between the day view and the calendar week view: level 2 navigation, so the shared underlined `Tabs`
 * (helhet rule 3), packed from the start of the head's first row with + and ⋯ at its end. Both views show it in the
 * same place, so the first two rows never move between the views.
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
      <Tabs
        fit="content"
        rule={false}
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
