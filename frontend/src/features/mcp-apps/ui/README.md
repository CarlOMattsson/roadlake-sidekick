# Shared MCP app components (`mcp-apps/ui/`)

The small component library every room uses (Work, Journal, Contacts, Shopping, Control). The rules behind it are in
`docs/reference/design-system.md`; the set was shaped by the November 2026 user tests and
their eight design-system rules. Every component takes its text as
props, so the caller picks the language (sv and en through the room's labels), and reads host tokens from
`tokens.css` (light and dark via `light-dark()`). Targets are at least 44 px, 48 where the design system says so.

Do not copy these into a room. A room that needs a variant asks for a prop here.

## Navigation: one type per level

| Level    | Component                                     | Use for                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                               |
| -------- | --------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1 rooms  | the shell's room strip (`sidekick-shell.css`) | Arbete · Dagbok · Inköp · Mer ⌄ (Kontakter is a row of Mer, `shell-parts/room-strip.tsx`). The active room is a raised pill (`--sk-nav-active-bg`, `--sk-nav-active-shadow`), never a frame. Each room button is 44 high (48 to tap). What a cell draws follows the frame by default: the name alone, and in a phone's frame a glyph over the name, the strip 48 there. Names alone, a glyph with each name, or glyphs alone at every width are the instance's choice (`nav-icons.ts`, `shell-parts/strip-cell.tsx`). |
| 2 views  | `Tabs` (`tabs.tsx`)                           | Views of one room: Agenda/Status/Projekt, Dag/Vecka, Borttaget/Historik/Sidekicks minne.                                                                                                                                                                                                                                                                                                                                                                                                                              |
| 3 values | `Segmented` (`segmented.tsx`)                 | A value inside a view (draft review choices). Not for navigation.                                                                                                                                                                                                                                                                                                                                                                                                                                                     |

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
  overlay?                            // the phone's panel lies over the page: a press outside closes it too
  id?, label?, className?, panelClassName?, popoverClassName?, inFlow? />
<MenuItem label onChoose disabled? danger? pressed? meta? current? />  // meta: a muted second line; current: ticked, aria-current
openMenuByKey(button, setOpen)        // opens from a shortcut (g 5) with the focus on the first entry
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

## `InsightLine` (`insight-line.tsx`)

```ts
<InsightLine text locale
  density?: "list" | "inline" | "detail"   // list (default): 2 lines; inline: 2 lines, no button; detail: whole
  onMore?: () => void                      // list: "Visa mer ›" opens the view that says more
  className? />
```

One sentence the server wrote ("Du sov dåligt, så den tunga uppgiften flyttades till imorgon."), body type, no heading,
the first block of Start and Automationer; an empty `text` draws nothing. In a list it stops after two lines
(`--sk-insight-lines`) with "…" after a whole word (`useWordClip`, `use-word-clip.ts`, which the journal's draft
summary uses too); screen readers get the whole sentence. Without `onMore`, a cut sentence offers "Visa mer" in place
(no ›, `aria-expanded`, then "Visa mindre"). A narrow full-screen frame (large text) does not cut it, as it does not
cut a row title. The words "Visa mer"/"Visa mindre" come from `insight-labels.ts` (sv and en, by `locale`).

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

## Photos: `PhotoStrip`, `PhotoGrid` (`photos.tsx`) and `PhotoViewer` (`photo-viewer.tsx`)

```ts
type Photo = { id; thumb?: string /* data:image/… */; alt?; date?: "YYYY-MM-DD"; width?; height?
  taken_at?: string /* ISO 8601 */; location?: { lat; lon; name? }; camera?; orientation? /* EXIF 1–8 */ }

<PhotoStrip photos locale onOpen(id) onMore?() size?: 64 | 40  max?: 4  label? />
<PhotoGrid  photos locale onOpen(id) onMore?() layout?: "columns" | "fill"  rows?: 2  label? />
<PhotoViewer photos currentId onChange(id) onClose() load(id) => Promise<string | Blob>
             backLabel locale actions?: { label; onChoose(photo); danger?; disabled? }[]  keys? />
```

Square tiles, radius 8, 8 apart, in a labelled list ("Foton"). `PhotoStrip` is one row that never wraps: 64 on a
journal card inline, 40 on a week day (drawn 40, 44 to tap); in a card narrower than four tiles they shrink together.
`PhotoGrid layout="fill"` is the day's block: 72 tiles that fill the row, at most `rows` rows. `layout="columns"` is
the entry: every photo, three to the row, four from 36 rem. When the photos do not fit, the last tile is "+n" (that
photo under a dark veil, named "3 foton till"): `onMore` shows them all, or without it the tile opens that photo.
Nothing is drawn without photos.

`PhotoViewer` is the layer for one large photo: the Back row "‹ {backLabel}" with ⋯ (`actions`; no ⋯ without them),
the photo fitted to the width at its known size, the caption in body text and "2 av 5 · 14 nov" under it. ‹ and ›
stand on the photo's sides, at the same height for a landscape and a portrait photo, and are held off at either end.
← and → step, a sideways swipe steps on a touch screen, and Esc or Back calls `onClose` (the room gives the focus back
to the tile, `[data-photo-id]`). The viewer listens in the capture phase, before the shell's Esc, and an open ⋯ takes
the keys first. `load(id)` runs only for the photo on screen (a tool call through the bridge), with the thumbnail
blurred in its place until it comes; the last 12 are kept, so a step back draws at once. A failed fetch keeps the
thumbnail and shows "Fotot kunde inte hämtas" with "Försök igen".

Metadata: the app reads the capture time, the location, the camera and the orientation from the file before it shrinks
it, and they travel as fields beside the clean image (the file itself carries none). Only the viewer shows them. Its
meta line becomes "2 av 5 · 14 nov 09:30 · Visby": when the photo was taken (else its day) and the place name when
there is one. Under it, "Fotodetaljer ⌄" (the shared `Fold`) names what it holds ("Tagen, plats och kamera"), so a
saved location can be seen without opening it. Open, it lists Tagen ("14 november 2026 09:30"), Plats (the name over
"57,6348° N, 18,2948° Ö", or the coordinates alone) and Kamera, and it stays open from photo to photo. It has no map,
no link, and no coordinates in any tile, row or card. `taken_at` is shown as the camera's wall clock (an offset is
not converted), a value that is not a date and time is left out, and coordinates outside ±90/±180 are left out.
`orientation` is kept as data and not drawn, because the re-encoded pixels are already upright. Editing and removing
the fields belongs to the room. The field names are the client's assumption until the photo tools' schemas exist.
`tests/e2e/photos-mcp-app.spec.ts` measures the tiles and the viewer on a test surface (no host, no bridge).

Sources: only `data:image/png|jpeg|webp|gif|avif;base64,…` is drawn (`safePhotoSrc`), because the host's CSP allows
`img-src 'self' data:` and no network. A Blob from `load` is read into a `data:` URL. Any other address (http, blob:,
SVG) is refused and the tile shows the photo glyph, so it never becomes a request. Nothing logs a source, and a failed
fetch's cause is dropped. Names: the caption, or "Foto {n} från {dag}" without one or when it is only a file name
(`photoAlt`). Texts are in `photo-labels.ts` (sv and en).

## Decisions: `DecisionCard`, `ApproveGroup`, `TrustNote`, `QuoteBlock`

One family for everything Sidekick or Claude proposes and the owner answers: suggestions, ready conversations and
suspicious suggestions. The same words on the same buttons everywhere come from `decision-labels.ts` (sv and en with
equal keys, picked by `locale`); what the suggestion says (title, changes, "why") comes from the server in the app's
language. What a check found comes as closed codes and is put in words here (`decision-codes.ts`), so no text a mail
or a model wrote reaches a trust note. The view owns the calls, the receipt bar with Ångra, the keyboard shortcuts and
the owner's clock.

```ts
<DecisionCard locale  kicker  title
  changes?: { label; value; before? }[]
  why?: string
  source?: { name: string; at?: string }          // `at` is display text the view formats ("07:02")
  trust?: { state: "ok" | "unsure" | "suspicious" | "off"; reason?; reasons?; confidence? }   // from decisionTrust
  edited?: boolean                                // "ändrad av dig" after the source
  actions: { approve; dismiss; review?; edit? }   // review: a suspicious card's way to its detail
  answerLabels?: { approve?; dismiss? }           // "Starta", "Hoppa över idag" on a ready conversation
  density?: "inline" | "full"   frame?: boolean   // frame={false}: the detail pane beside a list
  busy?: "approve" | "dismiss"  failed?: "approve" | "dismiss"
  applyError?: "project_gone" | "conflict" | "invalid_payload" | "not_permitted"
  decided?: { message; open?: { label; onOpen }; hold? }
  headingLevel?  children? />                     // children: shown in full, e.g. a QuoteBlock
```

- Order: trust note, kicker with source ("Förslag · från Morgonmejl · 07:02"), title, changes, "Varför", answers.
- Answers: **Avböj on the left, Godkänn on the right**, always. Inline Godkänn is a compact secondary and Avböj a compact
  tertiary, at the card's end edge; in `full` Godkänn is the compact primary, Avböj a secondary and Ändra (with `edit`)
  stands apart at the start. A full card under 30 rem wide shares its width between the answers, 48 high.
- Inline shows at most two changes (the rest as "+n" on the last line, read as "n ändringar till") and "Varför" in two
  lines. Under a trust note it shows the first reason, one change (none on a suspicious card) and no "Varför", heading
  and reason run together ("Kontrollen var osäker: …"). `full` shows every change ("före → efter", read as "ändras till"), the whole sentence and the check's line
  ("Kontrollerad · säker 94 %", "Inte kontrollerad").
- **Suspicious** has no Godkänn on the card. Inline: Avböj (framed, the suggested answer) and Granska (`review`). Full:
  Avböj is the primary and "Godkänn ändå" a tertiary that asks "Godkänna ett misstänkt förslag?" once (focus on Avbryt,
  Escape takes the question back and returns the focus).
- `busy` holds both answers (the running one reads "Godkänner…"); `failed` adds the failure's line under the buttons
  ("Det gick inte att godkänna. Försök igen.", or the `applyError` in words: "Något har ändrats sedan förslaget kom.
  Uppdatera och försök igen.") and the card stays. `decided` turns the card into its receipt
  ("Tillagd: Lena Holm · Öppna ›"); with `hold` it keeps the undecided height while the view's ReceiptBar offers Ångra,
  then shrinks to the receipt when the view drops `hold` (the receipt's `onEnd`).

```ts
decisionTrust(check: SuggestionCheck, locale) → DecisionTrust
// check: { check_state: "off"|"queued"|"checked"|"failed"; verdict?; confidence?; screening_flags?; reason_codes? }
```

The server's check as it keeps it (snake_case) to the card's trust. **Suspicious** when the verdict is `suspicious` or a
suspicious flag is set (`payment_related`, `homoglyph_domain`, `instruction_like_text`: money, an imitated address,
text aimed at an AI); **unsure** when the verdict is `uncertain` or any other flag is set (`contains_link`,
`contact_detail_unverified`, `duplicate_existing`, `large_batch`, or a flag the app does not know yet); otherwise
**ok** with the confidence when the check is done, and **off** ("Inte kontrollerad") when it is off, queued or failed.
A warning verdict warns whatever the check state. The sentences are the flags' (suspicious first), then the checker's
reason codes, each once: `reason` is the first, `reasons` all of them. An unknown code has no sentence. This is how
the card _reads_ the codes; which cards may be grouped or decided by a tool is the server's rule (`bulk_eligible`).
Fixtures in the server's shape: `suggestions` in the frontend UX test fixtures.

```ts
<ApproveGroup locale  title  items: { id; label }[]  excluded: ReadonlySet<string>
  onToggle(id)  onApproveAll(ids)  busy?  failed?
  max?: number                                    // at most this many per confirmation
  heading?: "card" | "section"  headingLevel? />
groupBatch(items, excluded, max?) → { batch, ids, beyond }
```

The suggestions the server marked safe together (`bulk`; the component decides nothing). Each row is a toggle
(`aria-pressed`) with a ring that is **filled while the row is in the group**; a tap takes it out and the button
counts again ("Godkänn alla 3", "Godkänn 2", a held "Godkänn" with nothing left). No "select all". Rows are 44.
`max` caps one confirmation: the first `max` items form the batch, the rest wait under the line "2 till efter de här,
högst 3 åt gången", and taking a row out pulls none in. **Claude's voice mode approves at most three per
confirmation**: a view answering there passes `max={3}`, and a tool path that confirms without drawing the group uses
`groupBatch` for the same ids. The view resets `excluded` when the items change.

```ts
<TrustNote state: "unsure" | "suspicious"  reason?  locale  title?  flow?: "block" | "run" />
<QuoteBlock label  text />                        // quoteText(text) is what it shows
```

`TrustNote` is the amber note with ⚠ and words ("Kontrollen var osäker", "Misstänkt förslag", or `title` for a report),
`role="note"`; suspicious adds the warning line as an edge and a start bar, so the levels differ in form too. Red is
never used here: red means failure, overdue or delete. `QuoteBlock` shows untrusted text (a mail) in a detail view
only, under a label that says Sidekick did not write it: plain text, no Markdown, no links; a web address is shown as
its domain name and a script or data address as "…".

The gallery `tests/ux/gallery/decision.html` shows every state with fixture data; screenshots and measures:
`GALLERY_OUT=<dir> npx playwright test --config playwright.gallery.config.ts` (a simulated page, not Claude or Android).

## Review cards: `FlipCard` (`flip-card.tsx`) and `QuestionCard` (`question-card.tsx`)

```ts
<FlipCard locale  front: { photo?: { src; alt }; text? }  back: { title; meta? }
  revealed  onReveal  grades: { label; onChoose; primary? }[]   // in key order: 1, 2, …
  density?: "full" | "inline"  loading?  busy?  notice?  ref? />

<QuestionCard locale  prompt  options: string[]  onAnswer(index)
  chosen?: number | null  result?: { correct; explain? } | null
  action?: { label; onClick }  unavailable?: string  notice?  headingLevel?  ref? />

reviewLabelsFor(locale)   // review-labels.ts: the cards' own words, and again/good/next/retry for the caller's buttons
```

`FlipCard` is one review card: a fixed face (a photo, or the question drawn as text), then the prompt and "Visa
svaret", or the answer and the grade buttons. The prompt and the answer share one grid cell, and so do the reveal and
the grades, so the card never changes height when it turns and the grades stand where the reveal stood. `full` is one
centred column at most 30 rem wide with a 200 face; `inline` puts a 120 face beside the text, with the buttons under
both, which keeps a Claude card under 340 at 110 % text. Every button is 48 high and as wide as its column. Inline has
no primary button; in fullscreen the reveal and the grade marked `primary` ("Kunde") are. `loading` makes the face a
skeleton and holds the reveal; `busy` holds the grades while one is sent (aria-disabled, so the focus stays).

`QuestionCard` is one multiple-choice question: the prompt as a heading, the options as 48 high rows where one press
answers, then a status line ("Rätt." or "Inte riktigt." and the explanation) and the one primary action, "Nästa" or
"Försök igen" (a wrong answer is asked again; no score). The server checks the answer: `chosen` is the option sent,
and until `result` comes that row reads "Rättas…" and every row is held. Right is the success tone with a tick, wrong
the warning tone with a cross, never red. `unavailable` holds the options with its reason ("Kräver anslutning").

Both cards take their keys while the focus is inside them (WCAG 2.1.4, active only on focus): in `FlipCard` Space or
Enter turns it and 1–9 choose a grade; in `QuestionCard` 1–9 answer and the arrow keys move between options. Each
button names its key in `aria-keyshortcuts`. A turn moves the focus to the answer (read after a hidden "Svar:"), a
grade moves it to the next card's reveal, and the action moves it to the next question's first option; a change the
view makes by itself moves no focus. A view that wants the keys at once focuses the card through `ref` and lists them
in its shortcut help. The answer rises in over `--sk-dur-slow`; under reduced motion it does not move at all.

A photo is drawn only from a `data:image/` URL (`isDrawablePhoto`): the app makes no request of its own. Its `alt`
must not give the answer away ("Foto att känna igen"). `tests/e2e/review-cards-mcp-app.spec.ts` builds a test surface
of the cards and measures them in Chromium (no host); no view uses them yet.
