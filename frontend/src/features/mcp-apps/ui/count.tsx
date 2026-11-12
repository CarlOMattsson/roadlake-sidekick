/**
 * A section heading's text with its count in the count's style: "Försenade" in the section type, " (5)" muted
 * and 400 (family.css .sk-count). A text without a count at its end stays as it is.
 */
export function Counted({ text }: { text: string }) {
  const at = text.lastIndexOf(" (");
  return at < 0 ? (
    text
  ) : (
    // One inline box, so the space before "(5)" stays inside a flex heading (the fold buttons) and in its name.
    <span>
      {text.slice(0, at)}
      <span className="sk-count">{text.slice(at)}</span>
    </span>
  );
}
