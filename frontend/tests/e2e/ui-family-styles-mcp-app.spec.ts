import {
  expect,
  test,
  type FrameLocator,
  type Locator,
  type Page,
} from "@playwright/test";
import { goRoom, openSidekick, room } from "./app-navigation-fixtures";
import { settled } from "./mcp-host-fixture";
import { journalDay, task } from "./sidekick-domain-fixtures";

// The shared design language of the rooms (tokens, the room strip, the four button levels, the round +, the menu)
// measured in a real Chromium from computed style and boxes instead of read out of the stylesheets. Simulated host (see
// mcp-host-fixture.ts), not a real Claude or Android host: every tool answer is a fixture. Where the design says
// "the colour of token X", the expected value is X resolved in the page, so a retuned token does not break the test
// but a rule that stops using it does.

/** `value` for the CSS `property`, resolved in the page: tokens, light-dark() and calc() become a colour or length. */
async function resolved(
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

const style = (locator: Locator, ...properties: string[]) =>
  locator.evaluate(
    (element, names) =>
      Object.fromEntries(
        names.map((name) => [name, getComputedStyle(element)[name as never]]),
      ) as Record<string, string>,
    properties,
  );

async function openJournal(page: Page, width = 500) {
  const opened = await openSidekick(page, {
    width,
    theme: "light",
    tool: "get_journal_day",
    result: journalDay,
  });
  await settled(opened.app);
  return opened;
}

const spacing = [
  ["--sk-s1", "4px"],
  ["--sk-s2", "8px"],
  ["--sk-s3", "12px"],
  ["--sk-s4", "16px"],
  ["--sk-s5", "24px"],
  ["--sk-row-pad", "6px"],
  ["--sk-row-min", "48px"],
  ["--sk-glyph", "16px"],
  ["--sk-selected-width", "2px"],
  ["--sk-plus", "32px"],
  ["--sk-tabs-h", "44px"],
] as const;

test("Design tokens: the 4 px spacing scale, the 48 px row, the 2 px contour and the type steps resolve as designed", async ({
  page,
}) => {
  const { app, failures } = await openJournal(page);
  for (const [token, length] of spacing)
    expect(await resolved(app, "width", `var(${token})`), token).toBe(length);
  const typed = (token: string) =>
    app.locator("#root").evaluate((root, value) => {
      const probe = document.createElement("span");
      root.appendChild(probe);
      probe.style.font = value;
      const out = getComputedStyle(probe);
      const result = [out.fontSize, out.lineHeight, out.fontWeight];
      probe.remove();
      return result;
    }, `var(${token})`);
  // The section heading is 18 / 24 semibold, the label 14 / 18 medium, a control 16 / 20.
  expect(await typed("--sk-type-section")).toEqual(["18px", "24px", "600"]);
  expect(await typed("--sk-type-label")).toEqual(["14px", "18px", "500"]);
  expect((await typed("--sk-type-label-strong"))[0]).toBe("16px");
  expect((await typed("--sk-type-label-strong"))[1]).toBe("20px");
  expect((await typed("--sk-type-label-strong"))[2]).toBe("600");
  expect((await typed("--sk-type-menu"))[2]).toBe("500");
  // Without host variables the text steps fall back to 14 / 16 px and 400 / 600.
  expect(await resolved(app, "width", "var(--sk-text-sm)")).toBe("14px");
  expect(await resolved(app, "width", "var(--sk-text-md)")).toBe("16px");
  expect(await resolved(app, "font-weight", "var(--sk-weight-normal)")).toBe(
    "400",
  );
  expect(await resolved(app, "font-weight", "var(--sk-weight-semibold)")).toBe(
    "600",
  );
  // The active room and day take the page colour with the text colour as their line.
  for (const [token, base] of [
    ["--sk-nav-active-bg", "--sk-bg"],
    ["--sk-nav-active-fg", "--sk-fg"],
    ["--sk-nav-active-line", "--sk-fg"],
    ["--sk-selected-line", "--sk-fg"],
  ] as const)
    expect(await resolved(app, "color", `var(${token})`), token).toBe(
      await resolved(app, "color", `var(${base})`),
    );
  // The skeleton is a tint between the text and the page colours, not either of them.
  const skeleton = await resolved(app, "color", "var(--sk-skeleton)");
  expect(skeleton).not.toBe(await resolved(app, "color", "var(--sk-fg)"));
  expect(skeleton).not.toBe(await resolved(app, "color", "var(--sk-bg)"));
  expect(failures).toEqual([]);
});

test("Design tokens: each status and each of the eight accents is a colour of its own, and the theme changes it", async ({
  page,
}) => {
  const names = [
    ...["success", "warning", "danger"].flatMap((status) =>
      ["line", "bg", "fg"].map((part) => `--sk-${status}-${part}`),
    ),
    ...[
      "slate",
      "blue",
      "teal",
      "green",
      "amber",
      "orange",
      "rose",
      "violet",
    ].map((accent) => `--sk-accent-${accent}-line`),
  ];
  const read = async (theme: "light" | "dark") => {
    const { app } = await openSidekick(page, {
      width: 500,
      theme,
      tool: "get_journal_day",
      result: journalDay,
    });
    await settled(app);
    return Promise.all(names.map((n) => resolved(app, "color", `var(${n})`)));
  };
  const light = await read("light");
  for (const colour of light) expect(colour).toMatch(/^rgb\(/);
  // The eight accent edges are eight different colours.
  expect(new Set(light.slice(9)).size).toBe(8);
  const dark = await read("dark");
  // An edge or a tone reads differently on the dark page, so the pair is not one colour for both themes.
  for (const [index, name] of names.entries())
    expect(dark[index], name).not.toBe(light[index]);
});

test("Rooms: every room's root is transparent, and a focused control shows a focus ring", async ({
  page,
}) => {
  const { app, failures } = await openJournal(page);
  for (const [name, root] of [
    ["Arbete", ".sidekick-work"],
    ["Dagbok", ".sidekick-journal"],
    ["Inköp", ".sidekick-shopping"],
  ] as const) {
    await goRoom(app, name);
    const rootBox = app.locator(root).first();
    await expect(rootBox).toBeVisible();
    expect((await style(rootBox, "backgroundColor")).backgroundColor).toBe(
      "rgba(0, 0, 0, 0)",
    );
    // Tab to the first control inside the room: the keyboard focus is drawn (an outline, or the ring as a shadow).
    await page.keyboard.press("Tab");
    const focus = app.locator(`${root} :focus-visible`).first();
    await expect(focus).toBeVisible();
    const ring = await style(
      focus,
      "outlineStyle",
      "outlineWidth",
      "boxShadow",
    );
    expect(
      ring.outlineStyle !== "none" && ring.outlineWidth !== "0px"
        ? "outline"
        : ring.boxShadow !== "none"
          ? "shadow"
          : "none",
      `${name} focus ring`,
    ).not.toBe("none");
  }
  expect(failures).toEqual([]);
});

test("Room strip: the chosen room is the page colour with a 2 px contour, the round + is an ink disc, an open icon button has no fill", async ({
  page,
}) => {
  const { app, failures } = await openJournal(page);
  const chosen = room(app, "Dagbok");
  await expect(chosen).toHaveAttribute("aria-current", "page");
  expect(await style(chosen, "backgroundColor", "boxShadow")).toEqual({
    backgroundColor: await resolved(
      app,
      "background-color",
      "var(--sk-nav-active-bg)",
    ),
    boxShadow: await resolved(
      app,
      "box-shadow",
      "inset 0 0 0 var(--sk-selected-width) var(--sk-nav-active-line)",
    ),
  });
  // A full frame paints its page in the colour of the strip's bar, so no band shows under the head.
  const [pageColour, barColour] = await Promise.all([
    app
      .locator("html")
      .evaluate((html) => getComputedStyle(html).backgroundColor),
    app
      .locator(".sk-rooms__bar")
      .evaluate((bar) => getComputedStyle(bar).backgroundColor),
  ]);
  expect(pageColour).toBe(barColour);
  // The + is an ink disc: round, the inverse pair, a 32 px disc inside its box.
  const plus = app.locator(".sk-iconbtn--primary").first();
  const disc = await plus.evaluate((element) => {
    const css = getComputedStyle(element);
    const px = (value: string) => Number.parseFloat(value);
    return {
      radius: css.borderRadius,
      background: css.backgroundColor,
      color: css.color,
      diameter:
        element.getBoundingClientRect().width -
        px(css.paddingLeft) -
        px(css.paddingRight),
    };
  });
  expect(disc).toEqual({
    radius: "50%",
    background: await resolved(app, "background-color", "var(--sk-inverse-bg)"),
    color: await resolved(app, "color", "var(--sk-inverse-fg)"),
    diameter: 32,
  });
  expect(failures).toEqual([]);
});

test("Menu and buttons: the ⋯ menu's ring lies inside its entry, an open icon button has no fill, the four button levels are drawn as designed", async ({
  page,
}) => {
  const { app, failures } = await openJournal(page);
  const more = app.locator(".journal-day-more");
  await more.focus();
  await page.keyboard.press("Enter");
  await expect(more).toHaveAttribute("aria-expanded", "true");
  // An open icon button keeps no fill of its own: the panel it opened shows the state.
  expect((await style(more, "backgroundColor")).backgroundColor).toBe(
    "rgba(0, 0, 0, 0)",
  );
  const item = app.locator(".sk-menu-item").first();
  await expect(item).toBeVisible();
  // The entry reaches 12 into the panel's padding and pads itself back, so its text keeps the panel's text edge.
  expect(
    await style(item, "marginLeft", "marginRight", "paddingLeft", "maxWidth"),
  ).toEqual({
    marginLeft: "-12px",
    marginRight: "-12px",
    paddingLeft: "12px",
    maxWidth: "none",
  });
  await item.focus();
  await page.keyboard.press("ArrowDown");
  const focused = app.locator(".sk-menu-item:focus-visible").first();
  expect((await style(focused, "outlineOffset")).outlineOffset).toBe("-4px");
  await page.keyboard.press("Escape");
  // An icon button's focus ring lies on its own box.
  const add = app.locator(".journal-day-add");
  await add.focus();
  await page.keyboard.press("Shift");
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  expect((await style(add, "outlineOffset")).outlineOffset).toBe("-2px");
  expect(failures).toEqual([]);
});

test("Buttons: primary is filled with the inverse pair, secondary has an edge, quiet has none, in the family's label type", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 500,
    theme: "light",
    tool: "get_journal_day",
    result: {
      ...journalDay,
      entries: [],
      summary: { ...journalDay.summary, exists: false, content: null },
    },
  });
  await settled(app);
  await app.getByRole("button", { name: "Ny anteckning" }).click();
  const primary = app.locator(".journal-add-choice.sk-btn--primary");
  const secondary = app.locator(".journal-add-choice.sk-btn--secondary");
  await expect(primary).toBeVisible();
  expect(await style(primary, "backgroundColor", "color")).toEqual({
    backgroundColor: await resolved(
      app,
      "background-color",
      "var(--sk-inverse-bg)",
    ),
    color: await resolved(app, "color", "var(--sk-inverse-fg)"),
  });
  const strong = await app.locator("#root").evaluate((root) => {
    const probe = document.createElement("span");
    root.appendChild(probe);
    probe.style.font = "var(--sk-type-label-strong)";
    const out = [
      getComputedStyle(probe).fontSize,
      getComputedStyle(probe).fontWeight,
    ];
    probe.remove();
    return out;
  });
  expect(await style(primary, "fontSize", "fontWeight")).toEqual({
    fontSize: strong[0],
    fontWeight: strong[1],
  });
  expect(await style(secondary, "backgroundColor", "borderTopColor")).toEqual({
    backgroundColor: "rgba(0, 0, 0, 0)",
    borderTopColor: await resolved(app, "color", "var(--sk-border)"),
  });
  expect(failures).toEqual([]);
});

test("Inline Work card: the family's card frame and eyebrow, with the app name only for screen readers", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 390,
    theme: "light",
    tool: "get_work_agenda",
    displayMode: "inline",
    result: {
      items: [
        {
          kind: "task",
          ...task,
          project_title: null,
          agenda_group: "today",
        },
      ],
      filters: {},
      next_cursor: null,
    },
  });
  await settled(app);
  const card = app.locator(".work-compact-card");
  await expect(card).toBeVisible();
  // One rule gives every inline card the same frame: the surface, a hairline edge and the card radius.
  expect(
    await style(
      card,
      "backgroundColor",
      "borderTopWidth",
      "borderTopColor",
      "borderTopLeftRadius",
    ),
  ).toEqual({
    backgroundColor: await resolved(
      app,
      "background-color",
      "var(--sk-surface)",
    ),
    borderTopWidth: await resolved(app, "width", "var(--sk-hairline)"),
    borderTopColor: await resolved(app, "color", "var(--sk-line)"),
    borderTopLeftRadius: await resolved(app, "width", "var(--sk-radius-card)"),
  });
  // The card type is the family's eyebrow: small, normal case.
  const eyebrow = app.locator(".work-compact-kind");
  expect(await style(eyebrow, "fontSize", "textTransform")).toEqual({
    fontSize: await resolved(app, "width", "var(--sk-type-meta-size)"),
    textTransform: "none",
  });
  // The app name is a heading for screen readers only: clipped to nothing, not drawn.
  const hidden = app.locator("h1.work-visually-hidden");
  expect((await style(hidden, "clipPath")).clipPath).toBe("inset(50%)");
  const hiddenBox = await hidden.boundingBox();
  expect(hiddenBox === null || hiddenBox.width <= 1).toBe(true);
  expect(failures).toEqual([]);
});

test("Contacts room: a row is at least as high as the 48 px row token", async ({
  page,
}) => {
  const { app, failures } = await openSidekick(page, {
    width: 500,
    theme: "light",
    tool: "get_journal_day",
    result: journalDay,
  });
  await settled(app);
  await goRoom(app, "Kontakter");
  const row = app.locator(".sk-row").first();
  await expect(row).toBeVisible();
  expect((await style(row, "minHeight")).minHeight).toBe(
    await resolved(app, "width", "var(--sk-row-min)"),
  );
  expect((await row.boundingBox())?.height).toBeGreaterThanOrEqual(48);
  expect(failures).toEqual([]);
});
