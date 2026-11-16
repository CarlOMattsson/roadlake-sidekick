import { aiLabelsFor } from "./ai-labels";
import "../../mcp-apps/ui/ai-step-mark.css";

/** The small "AI" on a Task's row while the Task is marked as possible with AI; read aloud as "Möjlig med AI". */
export function AiTaskMark({ locale }: { locale: string }) {
  const a = aiLabelsFor(locale);
  return (
    <span className="sk-ai-mark" role="img" aria-label={a.possible}>
      <span aria-hidden="true">{a.mark}</span>
    </span>
  );
}
