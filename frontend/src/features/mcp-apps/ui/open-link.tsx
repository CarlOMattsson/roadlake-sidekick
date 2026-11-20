import { CardFoot } from "./card";
import { ChevronRightIcon } from "./icons";
import "./open-link.css";

/**
 * The card's main link (helhet rule 2, designsystem §3 Inline card): "Öppna <vy> ›", in 600, followed by "· N till" in
 * the muted meta type, always with › and always last in the card, inside `CardFoot` (license coin). Exactly one per
 * inline card; it opens the room or view in fullscreen. Use it for every inline card's way into the room, never
 * "Visa alla (N)" or a link without ›. `label` is the whole open phrase ("Öppna Borttaget"); `more` is the rest that
 * the card does not show, already in words ("12 till", "22+ till"), and is left out when nothing more is hidden.
 * Inside a full view a list's "show more" is not this link.
 */
export type OpenLinkProps = {
  label: string;
  more?: string;
  onOpen: () => void;
};

export function OpenLink({ label, more, onOpen }: OpenLinkProps) {
  return (
    <CardFoot>
      <button
        type="button"
        className="sk-btn--open sk-open-link"
        onClick={onOpen}
      >
        <span className="sk-open-link__text">
          {label}
          {more ? (
            <>
              {" "}
              <span className="sk-open-link__more">{`· ${more}`}</span>
            </>
          ) : null}
        </span>
        <ChevronRightIcon />
      </button>
    </CardFoot>
  );
}
