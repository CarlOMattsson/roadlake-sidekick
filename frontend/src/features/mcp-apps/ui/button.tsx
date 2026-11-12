import type { ButtonHTMLAttributes } from "react";

import "./tokens.css";
import "./family.css";

/**
 * The family's button hierarchy. One primary per card (the main action: Open, Save, Add), any number
 * of secondary, quiet for low-key actions (Show all, Cancel), danger for destructive ones. All are at
 * least 44 px high. A plain `<button>` inside an app root is secondary, and `type="submit"` is primary,
 * so existing markup gets the same look; `buttonClass` gives the class for a native button.
 */
export type ButtonVariant = "primary" | "secondary" | "quiet" | "danger";

export function buttonClass(variant: ButtonVariant, extra?: string): string {
  const base = `sk-btn sk-btn--${variant}`;
  return extra ? `${base} ${extra}` : base;
}

export function Button({
  variant = "secondary",
  className,
  type = "button",
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: ButtonVariant }) {
  return (
    <button type={type} className={buttonClass(variant, className)} {...rest} />
  );
}
