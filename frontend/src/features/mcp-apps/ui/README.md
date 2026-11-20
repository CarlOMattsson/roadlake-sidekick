# Shared MCP app components (`mcp-apps/ui/`)

The small component library every room uses (Work, Journal, Contacts, Shopping, Control). The rules behind it are in
`docs/reference/design-system.md`; the set was shaped by the November 2026 user tests and
their eight design-system rules. Every component takes its text as
props, so the caller picks the language (sv and en through the room's labels), and reads host tokens from
`tokens.css` (light and dark via `light-dark()`). Targets are at least 44 px, 48 where the design system says so.

Do not copy these into a room. A room that needs a variant asks for a prop here.

## Navigation: one type per level

| Level    | Component                                     | Use for                                                                                                                                                                         |
| -------- | --------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1 rooms  | the shell's room strip (`sidekick-shell.css`) | Arbete · Dagbok · Kontakter · Inköp. The active room is a raised pill (`--sk-nav-active-bg`, `--sk-nav-active-shadow`), never a frame. Each room button is 44 high (48 to tap). |
| 2 views  | `Tabs` (`tabs.tsx`)                           | Views of one room: Agenda/Status/Projekt, Dag/Vecka, Borttaget/Historik/Sidekicks minne.                                                                                        |
| 3 values | `Segmented` (`segmented.tsx`)                 | A value inside a view (draft review choices). Not for navigation.                                                                                                               |

### `Tabs`

```ts
<Tabs<T extends string>
  label: string                       // group name for assistive technology
  options: { value: T; label: string }[]
  value: T | null
  onChange: (value: T) => void
  disabled?: boolean
  fit?: "equal" | "content"           // equal cells (default) | packed from the start, beside tools
  rule?: boolean                      // hairline under the tabs (default true); off when the row draws it
  wrap?: boolean                      // wrap onto more lines when they do not fit (default true); false = one line, for a caller that measures
  className?: string
  ref?: Ref<HTMLDivElement> />        // the group element, for that measuring
```

Underlined text tabs: chosen = 600 `--sk-fg` with a 3 px line, others 500 muted. Arrow keys, Home, End move focus.
`aria-pressed` buttons in a labelled group. The bold width is reserved, so choosing moves nothing.

## `Menu` (`menu.tsx`)

```ts
<Menu
  anchor: RefObject<HTMLElement | null> | ((menu: HTMLElement) => HTMLElement | null)  // the ⋯ button, or a row's title
  onClose: (reason: "escape" | "tab" | "outside") => void
  open?: boolean                      // false keeps it mounted and hidden (default true: mount it while open)
  align?: "end" | "start"             // right edge on the button's (default) | start edge on the anchor's
  point?: { x; y }                    // a context menu opened by the pointer stands there
  id?, label?, className?, panelClassName?, popoverClassName?, inFlow? />
<MenuItem label onChoose disabled? danger? pressed? />
menuButtonKeys(open, setOpen)         // the button's onKeyDown: ↓ opens on the first entry, ↑ on the last, Esc closes
```

What a ⋯ button or a row's context menu (right click, Shift+F10) opens. With a fine pointer, or in a frame of at
least 40 rem, it is a **popover**: 240 wide (13.75–20 rem), in the top layer, under its button with the right edges
aligned and 4 between, turned upward without room below, 8 from the frame's edges, placed in JS and following scroll
and resize. It moves nothing on the page. The first entry takes the focus; ↑ ↓ Home End move; one Escape closes it
with the focus back on the button; Tab closes and moves on from the button; a press outside closes it without a
choice. On a phone (coarse pointer, narrow frame) it is the family's panel in the flow (`.sk-menu-panel`), unchanged.
`DetailMenu` (`detail-menu.tsx`) is the Task's and Project's ⋯ built on it.

The button keeps `aria-expanded` and `aria-controls` and the entries are buttons (a disclosure, not `role="menu"`),
because some menus hold more than menu items (saved views, the update reminder, the license row). Without the Popover
API the menu is a fixed box (no `popover` attribute).

## `Switch` (`switch.tsx`)

```ts
<Switch checked: boolean  onChange: (next: boolean) => void  label: string  disabled?: boolean  className?: string />
```

The one on/off control, for a setting that applies at once ("Visa arkiverade", a memory source). Never a bare
checkbox. `role="switch"`; the row's meta line names the state ("På · …"), the switch carries no word.

## `Progress` (`progress.tsx`)

```ts
<Progress done: number  total: number  label?: string  layout?: "inline" | "bar" />
```

The one progress bar: text first (the information), a thin bar in one colour (`--sk-fg`) on a hairline track.
`inline` (default) = short bar after the text in a meta line or row; `bar` = the bar takes the rest of the row, for a
view's head ("Kundupdrag · 1 av 8 klara", "1 av 8 köpta"). The status board's distribution bar is not progress.

## `MessageBox` (`message-box.tsx`)

```ts
<MessageBox severity: "info" | "warning" | "error"
  title: string                        // what happened, no full stop
  children?: ReactNode                 // optional sentence
  action?: { label: string; onClick: () => void; busy?: boolean; busyLabel?: string }
  className?: string />
```

A message about the view, at the top of the view. `info` grey, `warning` amber with the action that fixes it when the
app can, `error` red with "Försök igen". `error` is `role="alert"`, the others `role="status"`. A first read that failed
with nothing to show is `ErrorNotice` (states.tsx) in place of the content; a failed write on a row is `ErrorNotice
placement="row"` under that control.

## Receipts: `useReceipt` + `ReceiptBar` (`receipt.tsx`)

```ts
const receipt = useReceipt(resetKey?: unknown)   // e.g. the day, the entry id, the tab
receipt.show({ message: string,
               undo?: { label: string; onUndo: () => unknown },
               action?: { label: string; onClick: () => void },
               onEnd?: () => void })        // returns the receipt's id
receipt.dismiss(id: number, undone?: boolean)    // only if it is still shown
receipt.clear()
<ReceiptBar receipt={receipt} />                 // last in the view
```

The one receipt model. Every change is confirmed in a small elevated bar at the foot of the view (tick, message,
at most "Visa" and "Ångra"), never as a line inside the content. It moves nothing above it: inline it is added under
the card's content; in fullscreen it is sticky above the host's reply field, so in a long list it floats over the rows.
It goes away by itself after `RECEIPT_MS` (6 s), or `UNDO_MS` (15 s, with the shrinking line) when it offers Ångra; the
time holds while pointer or focus is on it. A new receipt replaces the old one; `resetKey` changing or the view
unmounting clears it, so an old receipt never comes back. Messages have no closing full stop ("Återställd: Mjölk").

A row's own new state (a done task's filled ring and "Klar", a bought item greyed) is the row's state, not the receipt:
the row keeps its height. Its Ångra belongs in the bar. A row that holds its state while Ångra is offered settles in the
receipt's `onEnd` (called when the receipt leaves without its Ångra: time up, replaced, cleared, `resetKey`); Work's rows
do this through `useUndoReceipts` (work-app/shared/use-undo-receipts.ts); Shopping holds a bought row in its place
until the bar is empty.

Why the bar and not "on the row": three of the five user tests (Dagbok, Inköp, Arbete) found receipts that move the
content or come back later, and many changes have no row to confirm on (save, edit, move to another list, delete the
open object, restore, keep out of memory). The bar covers all of them in one place and never shifts the layout.

`Notice`/`UndoNotice` (notice.tsx) are the older receipt lines; new code uses the bar.

## `EmptyState` (`states.tsx`)

```ts
<EmptyState title: string  hint?: string
  ask?: { locale: string; example: string; onSend?: () => void }
  children?: ReactNode /> // the "+ Skapa …" action row
```

The one empty recipe: what is empty (a sentence), optionally what it is for, "Säg till Claude: ”…”" which sends the
phrase where the host can, and a create row in `children`. A search without a hit adds "Rensa sökningen".

## `OpenLink` (`open-link.tsx`)

```ts
<OpenLink label: string   // "Öppna Borttaget"
          more?: string   // "4 till", "22+ till"; left out when nothing is hidden
          onOpen: () => void />
```

The inline card's one main link, always last, always with ›, inside `CardFoot`. Replaces "Visa alla (N)" and
"Öppna ›" without a name. Every room's inline cards use it, Work's included.
