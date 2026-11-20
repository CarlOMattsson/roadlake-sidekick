import { useState } from "react";
import { Tabs } from "../../../mcp-apps/ui/tabs";
import type { BoardUndo } from "../board-columns";
import { boardLabelsFor } from "../board-labels";
import { sectionCount } from "../board-sections";
import type { BoardSegment } from "../../shared/work-items";
import type { WorkItemRecord } from "../../transport/transport";

type Section = {
  segment: BoardSegment;
  items: WorkItemRecord[];
  shown: WorkItemRecord[];
  unshown: number;
};

/** The column chosen on the last board, so a board that mounts again (Back from a card) shows the same column. */
let lastChosen: string | undefined;

/**
 * The column a phone's board shows: the one the owner chose, else in_progress when something is in progress (what is
 * being worked on comes first), else the first column (todo). A chosen column that has gone (the Projects tab with no
 * Project left) falls back the same way. The default is taken once, when the board first has cards: a card moved to
 * in_progress later does not carry the owner away from the column the move was made in.
 */
export function useChosenColumn(sections: readonly Section[]) {
  const [chosen, setChosen] = useState<string | undefined>(lastChosen);
  // The default once the board has cards, kept from then on (state set during render, React's pattern for a value
  // derived once from the props).
  const [settledDefault, setSettledDefault] = useState<string>();
  const keys = sections.map(({ segment }) => segment.key);
  const anyCard = sections.some(
    ({ items, unshown }) => items.length + unshown > 0,
  );
  const busyNow = sections.some(
    ({ segment, items, unshown }) =>
      segment.key === "in_progress" && items.length + unshown > 0,
  );
  const firstDefault = busyNow ? "in_progress" : keys[0];
  if (settledDefault === undefined && anyCard && firstDefault)
    setSettledDefault(firstDefault);
  const wanted = settledDefault ?? (anyCard ? firstDefault : undefined);
  const fallback =
    wanted && keys.includes(wanted) ? wanted : (keys[0] ?? "todo");
  const column = chosen && keys.includes(chosen) ? chosen : fallback;
  function choose(next: string) {
    lastChosen = next;
    setChosen(next);
  }
  return { column, choose };
}

/**
 * The phone's column tabs (a narrow board shows one status at a time): one option per status with its count, as the
 * section headings count it, so in_progress and blocked are one press away and never lie under 40 todo rows. The four
 * Task statuses always stand, so the order and place of each never change; the Projects tab only when the board has
 * Projects.
 */
export function ColumnTabs({
  sections,
  undos,
  column,
  onChoose,
  locale,
}: {
  sections: readonly Section[];
  undos: Record<string, BoardUndo>;
  column: string;
  onChoose: (column: string) => void;
  locale: string;
}) {
  const words = boardLabelsFor(locale);
  const options = sections.map((section) => ({
    value: section.segment.key,
    label: words.columnTab(
      section.segment.label,
      Math.max(0, sectionCount({ ...section, undos })),
    ),
  }));
  return (
    <div className="work-column-tabs">
      <Tabs
        label={words.columnTabs}
        options={options}
        value={column}
        onChange={onChoose}
        fit="equal"
      />
    </div>
  );
}
