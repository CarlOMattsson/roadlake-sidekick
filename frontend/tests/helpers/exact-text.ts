/**
 * The elements whose full text is `text`, the count included: the innermost that is not a span. A heading or button with a count has
 * the count in its own element (`.sk-count`), so `getByText("Att göra (9)")` finds nothing, and jsdom's
 * accessible name reads "Att göra(9)" without the space. `selector` narrows the candidates (e.g. "summary").
 */
export function elementsWithText(text: string, selector = "*"): HTMLElement[] {
  // The heading's own text wrapper (a span, count.tsx) is skipped: the innermost element that is not a span is returned.
  const whole = (el: Element) =>
    el.tagName !== "SPAN" && el.textContent === text;
  return Array.from(document.querySelectorAll<HTMLElement>(selector)).filter(
    (el) => whole(el) && !Array.from(el.querySelectorAll("*")).some(whole),
  );
}

/** The one element whose full text is `text`; throws when there is none or several. */
export function elementWithText(text: string, selector = "*"): HTMLElement {
  const found = elementsWithText(text, selector);
  const only = found[0];
  if (found.length !== 1 || only === undefined) {
    throw new Error(
      `expected one element with the text "${text}", found ${found.length}`,
    );
  }
  return only;
}
