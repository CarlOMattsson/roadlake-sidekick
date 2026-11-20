import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
  type RefObject,
} from "react";
import { onEscapeKey } from "./key-scope";
import { finePointer } from "./shortcuts";
import "./menu.css";

/** Space between the menu and its button, and the least space it keeps from the frame's edges (designsystem §3). */
const GAP = 4;
const EDGE = 8;

/** The frame width (rem) from which a menu opens as a popover with any pointer: the frame's middle layout. */
const POPOVER_FROM_REM = 40;

/**
 * Whether a menu opens as a popover now: a fine pointer (a mouse, as the host reports it in `data-host-pointer`),
 * or a frame at least 40 rem wide. The width is the frame's own, without a scrollbar, in root rem, so large text
 * falls back to the panel. Otherwise (a phone) the menu is the panel in the flow under its head.
 */
function popoverWanted(): boolean {
  if (typeof document === "undefined") return false;
  const root = document.documentElement;
  const rem = parseFloat(getComputedStyle(root).fontSize) || 16;
  return finePointer() || root.clientWidth / rem >= POPOVER_FROM_REM;
}

/**
 * `popoverWanted`, read again when the frame is resized, the pointer media changes or the host reports another
 * pointer (`data-host-pointer` on the root, host-style.ts).
 */
export function useMenuPopover(): boolean {
  const [wanted, setWanted] = useState(popoverWanted);
  useEffect(() => {
    const read = () => setWanted(popoverWanted());
    read();
    window.addEventListener("resize", read);
    const pointer = window.matchMedia?.("(pointer: fine)");
    pointer?.addEventListener?.("change", read);
    const host =
      typeof MutationObserver === "undefined"
        ? undefined
        : new MutationObserver(read);
    host?.observe(document.documentElement, {
      attributes: true,
      attributeFilter: ["data-host-pointer"],
    });
    return () => {
      window.removeEventListener("resize", read);
      pointer?.removeEventListener?.("change", read);
      host?.disconnect();
    };
  }, []);
  return wanted;
}

/** The data attribute the menu button leaves for the menu: "last" when ↑ opened it, so the focus starts on the last entry. */
const START = "menuStart";

/**
 * The keys of the button that opens a menu (designsystem §3 "Meny"): ↓ opens it with the focus on its first entry
 * and ↑ on its last; Escape closes an open one. Enter and Space press the button as a click does. Spread it as the
 * button's `onKeyDown`.
 */
export function menuButtonKeys(
  open: boolean,
  setOpen: (open: boolean) => void,
) {
  return (event: KeyboardEvent<HTMLElement>) => {
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const last = event.key === "ArrowUp";
      if (!open) {
        event.currentTarget.dataset[START] = last ? "last" : "first";
        setOpen(true);
        return;
      }
      // Open already: the focus goes into it (the menu the button controls).
      const controls = event.currentTarget.getAttribute("aria-controls");
      const menu = controls ? document.getElementById(controls) : null;
      const entries = menu ? entriesOf(menu) : [];
      (last ? entries.at(-1) : entries[0])?.focus();
      return;
    }
    if (open) onEscapeKey(event, () => setOpen(false));
  };
}

/** Where a menu stands and gives the focus back: a ref to its button, or a function that finds it from the menu. */
export type MenuAnchor =
  RefObject<HTMLElement | null> | ((menu: HTMLElement) => HTMLElement | null);

/** Why a menu closed itself: its caller decides where the focus goes after an outside click. */
export type MenuCloseReason = "escape" | "tab" | "outside";

const FOCUSABLE =
  "button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href], [tabindex]:not([tabindex='-1'])";

/** The entries the arrow keys move over: every enabled control of the menu that is not inside a folded part. */
function entriesOf(menu: HTMLElement): HTMLElement[] {
  return [...menu.querySelectorAll<HTMLElement>(FOCUSABLE)].filter((entry) =>
    // A control the menu does not draw (display: none) cannot take the focus; an engine without checkVisibility
    // (jsdom) goes by `hidden` alone.
    typeof entry.checkVisibility === "function"
      ? entry.checkVisibility()
      : !entry.closest("[hidden]") && !entry.closest("[inert]"),
  );
}

/** A field takes its own arrow keys (a date, the saved view's name). */
function ownsArrows(target: EventTarget | null): boolean {
  return (
    target instanceof HTMLElement &&
    (target.isContentEditable ||
      target instanceof HTMLTextAreaElement ||
      target instanceof HTMLSelectElement ||
      (target instanceof HTMLInputElement &&
        !["checkbox", "radio", "button"].includes(target.type)))
  );
}

/**
 * Whether the engine has the Popover API (the top layer). Without it the menu is a fixed box over the page
 * (menu.css) and carries no `popover` attribute, which an engine that only knows its style would hide.
 */
const POPOVER_API =
  typeof HTMLElement !== "undefined" &&
  typeof HTMLElement.prototype.showPopover === "function";

function isShown(element: HTMLElement): boolean {
  try {
    return element.matches(":popover-open");
  } catch {
    return false;
  }
}

/**
 * The one menu (designsystem §3 "Meny"): what a ⋯ button or a row's context menu opens. With a mouse, or in a frame at
 * least 40 rem wide, it is a popover 240 wide in the top layer: under its button, its right edge on the button's
 * (`align="end"`) or its start edge on the anchor's (`"start"`, a row's title), 4 between them, turned upward when
 * there is no room below and kept 8 from the frame's edges; a context menu opened by the pointer stands at the
 * pointer (`point`). It moves nothing on the page, follows a scroll and a resize, and closes on Escape (the focus back
 * on the button), on Tab (the focus moves on from the button) and on a press outside it (nothing chosen). Its first
 * entry takes the focus when it opens (its last when ↑ opened it, `menuButtonKeys`).
 *
 * On a phone (a coarse pointer in a narrow frame) it is today's panel in the flow under its head (`panelClassName`,
 * the family's `.sk-menu-panel`), with Escape as before, so the phone does not change.
 *
 * The entries are the caller's controls (`sk-menu-item` buttons, and the rows a room adds: the saved views, the
 * update reminder, the license): ↑ ↓ Home End move over them. The button keeps `aria-expanded` and `aria-controls`
 * (a disclosure), because some menus hold more than menu items.
 */
export function Menu({
  id,
  open = true,
  anchor,
  align = "end",
  point,
  onClose,
  label,
  className,
  panelClassName = "sk-menu-panel",
  popoverClassName = "sk-menu-popover",
  inFlow = false,
  children,
}: {
  id?: string;
  /** False keeps the menu mounted and hidden (its parts keep their state). Default true: the caller mounts it while open. */
  open?: boolean;
  /**
   * The button that opened it, or the element a context menu stands under; the focus returns here. A function finds it
   * from the menu element (a row's title, for a menu that lives in the row).
   */
  anchor: MenuAnchor;
  align?: "end" | "start";
  /** Where the pointer opened a context menu (client px); absent for a button and for Shift+F10. */
  point?: { x: number; y: number };
  onClose: (reason: MenuCloseReason) => void;
  label?: string;
  /** A class for both presentations. */
  className?: string;
  /** The class of the phone's panel in the flow. */
  panelClassName?: string;
  /** The class of the popover. */
  popoverClassName?: string;
  /** Always the panel in the flow: a room's menu that has not moved to the popover yet (the Contact's). */
  inFlow?: boolean;
  children: ReactNode;
}) {
  const popover = useMenuPopover() && !inFlow;
  const menu = useRef<HTMLDivElement>(null);
  const anchorOf = (): HTMLElement | null =>
    typeof anchor === "function"
      ? menu.current && anchor(menu.current)
      : anchor.current;
  const closeRef = useRef(onClose);
  useEffect(() => {
    closeRef.current = onClose;
  });
  const pointX = point?.x;
  const pointY = point?.y;

  function focusStart(element: HTMLElement) {
    const button = anchorOf();
    const start = button?.dataset[START];
    if (button) delete button.dataset[START];
    if (!popover && !start) return;
    const entries = entriesOf(element);
    (start === "last" ? entries.at(-1) : entries[0])?.focus({
      preventScroll: true,
    });
  }

  // Into the top layer while open, placed against its anchor; the first entry takes the focus.
  useLayoutEffect(() => {
    const element = menu.current;
    if (!element || !open) return;
    if (popover && POPOVER_API && !isShown(element)) element.showPopover();
    const place = () => {
      if (!popover) return;
      // The layout size, not the drawn one: the menu fades in from a 0.98 scale.
      const width = element.offsetWidth;
      const height = element.offsetHeight;
      const frameW = document.documentElement.clientWidth || window.innerWidth;
      const frameH = window.innerHeight;
      let left: number;
      let top: number;
      if (pointX !== undefined && pointY !== undefined) {
        left = pointX + width > frameW - EDGE ? pointX - width : pointX;
        top = pointY + height > frameH - EDGE ? pointY - height : pointY;
      } else {
        const at = anchorOf()?.getBoundingClientRect();
        if (!at) return;
        left = align === "end" ? at.right - width : at.left;
        top = at.bottom + GAP;
        if (top + height > frameH - EDGE && at.top - GAP - height >= EDGE)
          top = at.top - GAP - height;
      }
      left = Math.min(
        Math.max(left, EDGE),
        Math.max(EDGE, frameW - EDGE - width),
      );
      top = Math.min(
        Math.max(top, EDGE),
        Math.max(EDGE, frameH - EDGE - height),
      );
      element.style.left = `${Math.round(left)}px`;
      element.style.top = `${Math.round(top)}px`;
    };
    place();
    focusStart(element);
    if (!popover) return;
    window.addEventListener("scroll", place, true);
    window.addEventListener("resize", place);
    const sizes =
      typeof ResizeObserver === "undefined"
        ? undefined
        : new ResizeObserver(place);
    sizes?.observe(element);
    // A press outside the menu and its button closes it without a choice.
    const outside = (event: PointerEvent) => {
      const target = event.target as Node | null;
      if (!target || element.contains(target)) return;
      if (anchorOf()?.contains(target)) return;
      closeRef.current("outside");
    };
    document.addEventListener("pointerdown", outside, true);
    return () => {
      window.removeEventListener("scroll", place, true);
      window.removeEventListener("resize", place);
      sizes?.disconnect();
      document.removeEventListener("pointerdown", outside, true);
      if (POPOVER_API && isShown(element)) element.hidePopover();
      element.style.left = "";
      element.style.top = "";
    };
    // `focusStart` reads the anchor at open; a new point (another right click) places it again.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, popover, align, pointX, pointY, anchor]);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    if (event.key === "Escape") {
      onEscapeKey(event, () => {
        anchorOf()?.focus({ preventScroll: true });
        onClose("escape");
      });
      return;
    }
    if (event.defaultPrevented) return;
    if (event.key === "Tab") {
      if (!popover) return;
      // The focus goes to the button first, so Tab's own move starts there: on to what follows the button.
      anchorOf()?.focus({ preventScroll: true });
      onClose("tab");
      return;
    }
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    if (ownsArrows(event.target)) return;
    const entries = entriesOf(event.currentTarget);
    if (entries.length === 0) return;
    const at = entries.indexOf(event.target as HTMLElement);
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? entries.length - 1
          : event.key === "ArrowDown"
            ? (at + 1) % entries.length
            : (at - 1 + entries.length) % entries.length;
    event.preventDefault();
    event.stopPropagation();
    entries[next]?.focus();
  }

  const classes = [popover ? popoverClassName : panelClassName, className]
    .filter(Boolean)
    .join(" ");
  return (
    // The container is not a control: it handles the keys bubbling up from the entries inside (as KeyScope).
    <div
      ref={menu}
      id={id}
      className={classes}
      hidden={!open}
      popover={popover && POPOVER_API ? "manual" : undefined}
      aria-label={label}
      role={label ? "group" : undefined}
      data-menu={popover ? "popover" : "panel"}
      data-align={popover ? (point ? "point" : align) : undefined}
      onKeyDown={onKeyDown}
    >
      {children}
    </div>
  );
}

/**
 * One entry of a menu: a 44 row with the menu's 16/20 at 500. `danger` draws a deletion in the danger colour (last,
 * after a divider in the popover); `pressed` is a mark the record carries or not, ticked at the entry's end.
 */
export function MenuItem({
  label,
  onChoose,
  disabled,
  danger = false,
  pressed,
}: {
  label: string;
  onChoose: () => void;
  disabled?: boolean;
  danger?: boolean;
  pressed?: boolean;
}) {
  return (
    <button
      type="button"
      className={danger ? "sk-menu-item sk-menu-item--danger" : "sk-menu-item"}
      disabled={disabled}
      aria-pressed={pressed}
      onClick={onChoose}
    >
      {label}
    </button>
  );
}
