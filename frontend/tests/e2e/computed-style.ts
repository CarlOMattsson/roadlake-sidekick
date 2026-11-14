import { expect, type FrameLocator, type Locator } from "@playwright/test";

// Helpers for specs that measure how a view looks in a real Chromium: the computed style and the boxes of the
// rendered elements. Where a value comes from a design token, the expected value is the token resolved in the page,
// so a retuned token does not break a test but a rule that stops using it does.

/** `value` of the CSS `property`, resolved in the page (tokens, light-dark() and calc() become a colour or length). */
export async function resolved(
  app: FrameLocator,
  property: string,
  value: string,
): Promise<string> {
  return app.locator("#root").evaluate(
    (root, [name, text]) => {
      const probe = document.createElement("span");
      root.appendChild(probe);
      probe.style.setProperty(name as string, text as string);
      const out = getComputedStyle(probe).getPropertyValue(name as string);
      probe.remove();
      return out;
    },
    [property, value],
  );
}

/** Like `resolved`, for a value that reads a custom property set on `scope` or below, such as a frame's token. */
export const resolvedWithin = (
  scope: Locator,
  property: string,
  value: string,
): Promise<string> =>
  scope.evaluate(
    (element, [name, text]) => {
      const probe = document.createElement("span");
      element.appendChild(probe);
      probe.style.setProperty(name as string, text as string);
      const out = getComputedStyle(probe).getPropertyValue(name as string);
      probe.remove();
      return out;
    },
    [property, value],
  );

/** The computed values of `properties` (camel-case, or custom properties such as `--sk-row-title-lines`). */
export const style = (locator: Locator, ...properties: string[]) =>
  locator.evaluate((element, names) => {
    const computed = getComputedStyle(element);
    return Object.fromEntries(
      names.map((name) => [
        name,
        name.startsWith("--")
          ? computed.getPropertyValue(name).trim()
          : computed[name as never],
      ]),
    ) as Record<string, string>;
  }, properties);

/** The computed values of `properties` of the pseudo-element `pseudo` (for example `::before`) of `locator`. */
export const pseudoStyle = (
  locator: Locator,
  pseudo: string,
  ...properties: string[]
) =>
  locator.evaluate(
    (element, [which, ...names]) => {
      const computed = getComputedStyle(element, which);
      return Object.fromEntries(
        names.map((name) => [name, computed[name as never]]),
      ) as Record<string, string>;
    },
    [pseudo, ...properties],
  );

export const box = async (locator: Locator) => {
  const found = await locator.boundingBox();
  expect(found, "the element has a box").not.toBeNull();
  return found!;
};
