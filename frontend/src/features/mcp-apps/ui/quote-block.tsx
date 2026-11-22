import "./tokens.css";
import "./quote-block.css";

/**
 * Text from a source Sidekick does not trust (a line of an e-mail, a page), shown so the owner can judge it: only in a
 * detail view, under a label that says where it comes from and that Sidekick did not write it ("Ur mejlet, inte
 * skrivet av Sidekick"). The text is plain text: no Markdown, no HTML and no links. A web address is shown as its
 * domain name in plain text and cannot be followed, so a quote cannot lead the owner anywhere. Line breaks are kept.
 */
export function QuoteBlock({
  label,
  text,
  className,
}: {
  /** Where the text comes from and that Sidekick did not write it. */
  label: string;
  text: string;
  className?: string;
}) {
  return (
    <figure className={className ? `sk-quote ${className}` : "sk-quote"}>
      <figcaption className="sk-quote__label">{label}</figcaption>
      <blockquote className="sk-quote__text">{quoteText(text)}</blockquote>
    </figure>
  );
}

// A web address: a scheme (any, so javascript: and data: are caught too) or a bare www. host, up to the next space.
const ADDRESS = /\b(?:[a-z][a-z0-9+.-]*:\/\/|www\.)[^\s<>"']+/gi;
const SCHEME_ONLY = /\b(?:javascript|data|vbscript|file):[^\s<>"']*/gi;

/** The quote as it is shown: every web address replaced by its domain name, a script or data address by "…". */
export function quoteText(text: string): string {
  return text
    .replace(ADDRESS, (match) => {
      // A full stop or a bracket after the address belongs to the sentence.
      const tail = /[.,;:!?)\]]+$/.exec(match)?.[0] ?? "";
      const address = match.slice(0, match.length - tail.length);
      return `${domainOf(address) ?? "…"}${tail}`;
    })
    .replace(SCHEME_ONLY, "…");
}

function domainOf(address: string): string | null {
  const withScheme = /^www\./i.test(address) ? `https://${address}` : address;
  try {
    const url = new URL(withScheme);
    if (url.protocol !== "http:" && url.protocol !== "https:") return null;
    return url.hostname.replace(/^www\./i, "") || null;
  } catch {
    return null;
  }
}
