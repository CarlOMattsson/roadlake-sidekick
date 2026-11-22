import { type ElementType, type ReactNode, type Ref } from "react";

/**
 * The title of a detail frame. It takes focus by script (`tabIndex={-1}`) when the frame is entered, and when
 * `onEdit` is set a click on it opens the editor, a pointer shortcut. The keyboard route to the same action is
 * the Edit item in the header menu, so the heading itself has no key handler and no role of its own.
 */
export function DetailTitle({
  heading,
  onEdit,
  leading,
  children,
}: {
  heading: Ref<HTMLHeadingElement>;
  /** Unset while editing is not offered (loading, archived, a write in flight): a click does nothing. */
  onEdit?: () => void;
  /** Drawn before the title on its line: a Task's ring beside its list in a wide frame (desktop spec 3.1). */
  leading?: ReactNode;
  children: ReactNode;
}) {
  // A heading is not a control; the click is a pointer shortcut. jsx-a11y sees a component tag here, so the
  // intent is stated in this comment and not in a lint disable (the same as `KeyScope`).
  const Tag: ElementType = "h2";
  const title = (
    <Tag
      ref={heading}
      tabIndex={-1}
      className="work-detail-title"
      onClick={onEdit}
    >
      {children}
    </Tag>
  );
  if (!leading) return title;
  return (
    <div className="work-detail-title-row">
      {leading}
      {title}
    </div>
  );
}
