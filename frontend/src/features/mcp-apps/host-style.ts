import type { HostContext } from "@/features/mcp-apps/bridge";

/**
 * The host style fields this module applies now live in HostContext (bridge.ts). The alias keeps
 * the older name working for existing callers. Values come from the host and are untrusted,
 * so every entry is checked at runtime before it reaches the DOM.
 */
export type HostStyleContext = HostContext;

const VARIABLE_NAME = /^--[a-z0-9-]{1,64}$/;
const FORBIDDEN_VALUE = /url\(|@import|;/i;
const MAX_VALUE_LENGTH = 200;
const SAFE_AREA_SIDES = ["top", "right", "bottom", "left"] as const;

/**
 * Applies host style to the app root: CSS variables, theme, safe area and the input kind. Invalid entries are
 * ignored silently. A missing or invalid safe-area side becomes 0px.
 */
export function applyHostStyle(ctx: HostStyleContext, root: HTMLElement): void {
  applyVariables(ctx.styles?.variables, root);
  applyTheme(ctx.theme, root);
  applySafeArea(ctx.safeAreaInsets, root);
  applyPointer(ctx, root);
}

/**
 * The input the host reports, as `data-host-pointer` on the root: "fine" (a mouse, no long press) or "coarse" (a
 * finger). The device's own flags decide first (`deviceCapabilities`: hover without touch is fine, touch without hover
 * coarse), then the platform ("desktop" fine, "mobile" coarse). With neither, the attribute stays as it was, so a
 * later context that leaves the fields out keeps the earlier answer and the frame's media query decides alone.
 */
function applyPointer(ctx: HostStyleContext, root: HTMLElement): void {
  const device = ctx.deviceCapabilities;
  const touch = typeof device?.touch === "boolean" ? device.touch : undefined;
  const hover = typeof device?.hover === "boolean" ? device.hover : undefined;
  const pointer =
    hover === true && touch !== true
      ? "fine"
      : touch === true && hover !== true
        ? "coarse"
        : ctx.platform === "desktop"
          ? "fine"
          : ctx.platform === "mobile"
            ? "coarse"
            : undefined;
  if (pointer) root.dataset.hostPointer = pointer;
}

function applyVariables(variables: unknown, root: HTMLElement): void {
  if (typeof variables !== "object" || variables === null) return;
  for (const [name, value] of Object.entries(variables)) {
    if (VARIABLE_NAME.test(name) && isSafeValue(value)) {
      root.style.setProperty(name, value);
    }
  }
}

function isSafeValue(value: unknown): value is string {
  return (
    typeof value === "string" &&
    value.length <= MAX_VALUE_LENGTH &&
    !FORBIDDEN_VALUE.test(value)
  );
}

function applyTheme(theme: unknown, root: HTMLElement): void {
  if (theme !== "light" && theme !== "dark") return;
  root.setAttribute("data-theme", theme);
  root.style.colorScheme = theme;
}

function applySafeArea(insets: unknown, root: HTMLElement): void {
  const source: Record<string, unknown> =
    typeof insets === "object" && insets !== null
      ? (insets as Record<string, unknown>)
      : {};
  for (const side of SAFE_AREA_SIDES) {
    const value = source[side];
    const px =
      typeof value === "number" && Number.isFinite(value) && value >= 0
        ? value
        : 0;
    root.style.setProperty(`--host-safe-${side}`, `${px}px`);
  }
}
