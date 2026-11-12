import { AppFrame } from "../../mcp-apps/ui/layout";
import type { WorkLabels } from "../shared/labels";
import type { WorkTransport } from "../transport/transport";
import { UnsortedView } from "./unsorted-view";

/**
 * The To sort page (Att sortera). It covers the shell, which stays mounted and hidden; Back returns. The fullscreen
 * frame (AppFrame, as the shell uses) gives the page the foot reserve below it, so the reply field does not cover the
 * Undo line or the last row.
 */
export function SortingPage({
  transport,
  labels,
  onBack,
}: {
  transport: WorkTransport;
  labels: WorkLabels;
  onBack: () => void;
}) {
  return (
    <AppFrame mode="full">
      <section className="work-unsorted-page">
        <button type="button" className="work-back" onClick={onBack}>
          {labels.back}
        </button>
        <h2 className="work-unsorted-heading">{labels.unsortedHeading}</h2>
        <UnsortedView transport={transport} labels={labels} />
      </section>
    </AppFrame>
  );
}
