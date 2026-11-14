import type { ElementType, ReactNode } from "react";

import "./tokens.css";
import "./family.css";

/**
 * An inline card's open row (the open label and a ›) with the license coin at its end (license-mark.tsx). Wrap the open
 * button, or the action row that ends on it, in it; without the license signal it adds nothing.
 */
export { LicenseCardFoot as CardFoot } from "../license-mark";

/**
 * The family's card shell (the inline card of the app design system): surface, hairline,
 * radius 12, padding 16, and its parts in a fixed order: the kicker (the room, then the event or count, the
 * eyebrow), the title (the object's name), the body (at most 3 rows or 4 lines of text), an optional
 * muted line (`meta`: the source or the links) and the actions (one primary button, the open label).
 * Every inline card in the four apps uses it, so they read as one family. Colours and type come from
 * tokens.css; the host's theme variables are followed.
 *
 * `as` picks the element (a `section` with an `aria-label` for a landmark, an `article` for a record).
 * `headingLevel` is the title's heading level; the eyebrow is a plain paragraph so it adds no heading.
 */
export function Card({
  eyebrow,
  title,
  headingLevel = 2,
  as: Tag = "section",
  className,
  children,
  meta,
  actions,
  ...rest
}: {
  eyebrow?: ReactNode;
  title?: ReactNode;
  headingLevel?: 1 | 2 | 3 | 4;
  as?: ElementType;
  className?: string;
  children?: ReactNode;
  /** One muted line under the body: the source or the links. */
  meta?: ReactNode;
  /** The card's actions: one primary button, optionally followed by a secondary one. */
  actions?: ReactNode;
  "aria-label"?: string;
  "aria-labelledby"?: string;
  id?: string;
}) {
  const Heading = `h${headingLevel}` as ElementType;
  return (
    <Tag className={className ? `sk-card ${className}` : "sk-card"} {...rest}>
      {eyebrow ? <Eyebrow>{eyebrow}</Eyebrow> : null}
      {title ? <Heading className="sk-card__title">{title}</Heading> : null}
      {children}
      {meta ? <p className="sk-card__meta">{meta}</p> : null}
      {actions ? <div className="sk-card__actions">{actions}</div> : null}
    </Tag>
  );
}

/** The small muted line above a title. Use `as="h1"` where the app name is also the page heading. */
export function Eyebrow({
  as: Tag = "p",
  children,
}: {
  as?: ElementType;
  children: ReactNode;
}) {
  return <Tag className="sk-eyebrow">{children}</Tag>;
}
