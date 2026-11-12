import { beforeEach, describe, expect, it } from "vitest";
import {
  applyHostStyle,
  type HostStyleContext,
} from "@/features/mcp-apps/host-style";

let root: HTMLElement;

beforeEach(() => {
  root = document.createElement("div");
  document.body.replaceChildren(root);
});

/** Custom properties set by the variables path. The safe-area path always writes --host-safe-*. */
function variableNames(el: HTMLElement): string[] {
  return Array.from({ length: el.style.length }, (_, i) =>
    el.style.item(i),
  ).filter((name) => !name.startsWith("--host-safe-"));
}

describe("applyHostStyle variables", () => {
  it("sets valid variables on the root", () => {
    applyHostStyle(
      {
        styles: {
          variables: {
            "--color-text-primary": "#1a1a1a",
            "--font-text-body": "15px",
          },
        },
      },
      root,
    );
    expect(root.style.getPropertyValue("--color-text-primary")).toBe("#1a1a1a");
    expect(root.style.getPropertyValue("--font-text-body")).toBe("15px");
  });

  it("ignores keys that do not match the variable name pattern", () => {
    applyHostStyle(
      {
        styles: {
          variables: {
            "color-text": "red",
            "--Color-Text": "red",
            "--under_score": "red",
            "--": "red",
            [`--${"a".repeat(65)}`]: "red",
          },
        },
      },
      root,
    );
    expect(variableNames(root)).toEqual([]);
  });

  it("accepts a key of exactly 64 characters after the dashes", () => {
    const name = `--${"a".repeat(64)}`;
    applyHostStyle({ styles: { variables: { [name]: "1px" } } }, root);
    expect(root.style.getPropertyValue(name)).toBe("1px");
  });

  it("ignores values that are too long, not strings, or unsafe", () => {
    applyHostStyle(
      {
        styles: {
          variables: {
            "--long": "a".repeat(201),
            "--number": 12,
            "--null": null,
            "--object": { value: "red" },
            "--url": "url(https://example.com/x.png)",
            "--url-upper": "URL(https://example.com/x.png)",
            "--import": "@import 'x.css'",
            "--semicolon": "red; background: blue",
          },
        },
      },
      root,
    );
    expect(variableNames(root)).toEqual([]);
  });

  it("accepts a value of exactly 200 characters", () => {
    const value = "a".repeat(200);
    applyHostStyle({ styles: { variables: { "--ok": value } } }, root);
    expect(root.style.getPropertyValue("--ok")).toBe(value);
  });

  it("keeps the valid entries when others are invalid", () => {
    applyHostStyle(
      {
        styles: {
          variables: { "--bad": "url(x)", "--good": "#fff" },
        },
      },
      root,
    );
    expect(root.style.getPropertyValue("--good")).toBe("#fff");
    expect(root.style.getPropertyValue("--bad")).toBe("");
  });

  it("ignores a styles object or variables value that is not an object", () => {
    const junk: HostStyleContext[] = [
      {},
      { styles: {} },
      { styles: { variables: null as unknown as Record<string, unknown> } },
      {
        styles: {
          variables: "--a: red" as unknown as Record<string, unknown>,
        },
      },
    ];
    for (const ctx of junk) applyHostStyle(ctx, root);
    expect(root.style.getPropertyValue("--a")).toBe("");
    expect(root.style.length).toBe(4);
  });
});

describe("applyHostStyle theme", () => {
  it("sets data-theme and color-scheme for dark", () => {
    applyHostStyle({ theme: "dark" }, root);
    expect(root.getAttribute("data-theme")).toBe("dark");
    expect(root.style.colorScheme).toBe("dark");
  });

  it("sets data-theme and color-scheme for light", () => {
    applyHostStyle({ theme: "light" }, root);
    expect(root.getAttribute("data-theme")).toBe("light");
    expect(root.style.colorScheme).toBe("light");
  });

  it("ignores an unknown theme", () => {
    applyHostStyle({ theme: "sepia" }, root);
    expect(root.hasAttribute("data-theme")).toBe(false);
    expect(root.style.colorScheme).toBe("");
  });
});

describe("applyHostStyle safe area", () => {
  it("sets the four safe area variables in px", () => {
    applyHostStyle(
      { safeAreaInsets: { top: 47, right: 0, bottom: 34, left: 12 } },
      root,
    );
    expect(root.style.getPropertyValue("--host-safe-top")).toBe("47px");
    expect(root.style.getPropertyValue("--host-safe-right")).toBe("0px");
    expect(root.style.getPropertyValue("--host-safe-bottom")).toBe("34px");
    expect(root.style.getPropertyValue("--host-safe-left")).toBe("12px");
  });

  it("uses 0px for missing sides", () => {
    applyHostStyle(
      { safeAreaInsets: { top: 20 } } as unknown as HostStyleContext,
      root,
    );
    expect(root.style.getPropertyValue("--host-safe-top")).toBe("20px");
    expect(root.style.getPropertyValue("--host-safe-right")).toBe("0px");
    expect(root.style.getPropertyValue("--host-safe-bottom")).toBe("0px");
    expect(root.style.getPropertyValue("--host-safe-left")).toBe("0px");
  });

  it("uses 0px for invalid side values", () => {
    applyHostStyle(
      {
        safeAreaInsets: {
          top: "47" as unknown as number,
          right: -4,
          bottom: Number.NaN,
          left: 8,
        },
      },
      root,
    );
    expect(root.style.getPropertyValue("--host-safe-top")).toBe("0px");
    expect(root.style.getPropertyValue("--host-safe-right")).toBe("0px");
    expect(root.style.getPropertyValue("--host-safe-bottom")).toBe("0px");
    expect(root.style.getPropertyValue("--host-safe-left")).toBe("8px");
  });

  it("sets all four to 0px when safeAreaInsets is absent", () => {
    applyHostStyle({}, root);
    expect(root.style.getPropertyValue("--host-safe-top")).toBe("0px");
    expect(root.style.getPropertyValue("--host-safe-left")).toBe("0px");
  });
});

describe("applyHostStyle pointer", () => {
  const pointerOf = (ctx: HostStyleContext) => {
    applyHostStyle(ctx, root);
    return root.dataset.hostPointer;
  };

  it("reads the device flags first: hover without touch is fine, touch without hover coarse", () => {
    expect(
      pointerOf({ deviceCapabilities: { hover: true, touch: false } }),
    ).toBe("fine");
    expect(
      pointerOf({ deviceCapabilities: { touch: true, hover: false } }),
    ).toBe("coarse");
    // The flags win over the platform.
    expect(
      pointerOf({ platform: "desktop", deviceCapabilities: { touch: true } }),
    ).toBe("coarse");
  });

  it("falls back to the platform: desktop is fine, mobile coarse", () => {
    expect(pointerOf({ platform: "desktop" })).toBe("fine");
    expect(pointerOf({ platform: "mobile" })).toBe("coarse");
    // Both flags (a touch laptop) say nothing: the platform decides.
    expect(
      pointerOf({
        platform: "desktop",
        deviceCapabilities: { touch: true, hover: true },
      }),
    ).toBe("fine");
  });

  it("leaves the attribute as it was when the context tells nothing (web, no flags, junk)", () => {
    expect(pointerOf({ platform: "web" })).toBeUndefined();
    expect(
      pointerOf({
        deviceCapabilities: "yes" as unknown as { touch: boolean },
      }),
    ).toBeUndefined();
    pointerOf({ platform: "desktop" });
    expect(pointerOf({ theme: "dark" })).toBe("fine");
  });
});
