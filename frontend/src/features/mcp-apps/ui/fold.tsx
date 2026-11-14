import { Counted } from "./count";
import { ChevronDownIcon } from "./icons";

/**
 * The one fold row (row.css .sk-fold): "Text (n) ⌄" in the section type and ink, its count muted, an
 * optional meta line under it in 15,4 text-2, ⌄ (24) on the content edge and a 48 target. the completed, bought and
 * done-here folds, the ways-to-reach fold and the row menu's groups at large text all use it.
 */
export function Fold({
  text,
  meta,
  open,
  onToggle,
  className,
  controls,
}: {
  text: string;
  meta?: string;
  open: boolean;
  onToggle: () => void;
  className?: string;
  /** The id of the region it opens, when that region stays in the page while folded (aria-controls). */
  controls?: string;
}) {
  return (
    <button
      type="button"
      className={className ? `sk-fold ${className}` : "sk-fold"}
      aria-expanded={open}
      aria-controls={controls}
      onClick={onToggle}
    >
      <span className="sk-fold-text">
        <Counted text={text} />
        {meta && <span className="sk-fold-meta">{meta}</span>}
      </span>
      <ChevronDownIcon />
    </button>
  );
}
