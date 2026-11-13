import { ErrorNotice } from "../../mcp-apps/ui/states";
import type { WriteFailure } from "../transport/transport";
import type { WorkLabels } from "./labels";

/**
 * A refused or failed create in the family's write error row. Only a transient failure can be repeated, so only it
 * gets "Försök igen"; the other refusals explain, and a forbidden write is calm text. `failedMessage` is the line for that
 * transient failure ("Det gick inte att skapa …"), without the retry words: the button says them.
 */
export function WriteFailureRow({
  failure,
  failedMessage,
  labels: t,
  retrying = false,
  onRetry,
}: {
  failure: WriteFailure;
  failedMessage: string;
  labels: WorkLabels;
  retrying?: boolean;
  onRetry: () => void;
}) {
  // Not being allowed is calm text, not an error.
  if (failure === "forbidden") return <p>{t.forbiddenWrite}</p>;
  const message =
    failure === "conflict"
      ? t.createConflict
      : failure === "invalid"
        ? t.invalidChange
        : failure === "not_found"
          ? t.notFound
          : failedMessage;
  return (
    <ErrorNotice
      placement="row"
      locale={t.dateLocale}
      message={message}
      retrying={retrying}
      onRetry={failure === "failed" ? onRetry : undefined}
    />
  );
}
