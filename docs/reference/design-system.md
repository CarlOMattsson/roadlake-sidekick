# Sidekick MCP app design system

The rules every Sidekick MCP App view follows: the rooms (Work, Journal, Contacts, Shopping, Control) and the
inline cards. Source comments in `frontend/src/features/**` cite sections of this document as
"designsystem §N"; the numbering is stable. Tokens live in `frontend/src/features/mcp-apps/ui/tokens.css`,
the shared components in `ui/family.css`, `ui/row.css` and `ui/layout.css`. When a rule changes, change this
document and the token together.

Language: the rules are written in English, and the on-screen strings they quote ("Öppna Status", "Idag",
"Lägg till steg") are the Swedish default labels of the app; the English labels are the same keys (see
"Language" in §5).

Measurements are CSS px in a 412 px wide frame. "At 110 %" means the text scale used by the layout tests
(root font 17.6 px); rules for 150 % and 200 % describe large-text behavior. Layout tests run in a simulated
host. That is not a test in a real Claude or Android host, and nothing here claims it is.

## 0. The system at a glance

1. **Buttons: four levels, the same in every room.** Primary (ink, one per screen), secondary (outline),
   tertiary (text, 600) and destructive (red text). Compact is 40 drawn and 48 to tap. There is no tonal
   (grey-filled) level.
2. **One chosen state.** The surface colour, a 2 px outline in `--sk-fg`, weight 600, and a 16 px tick on chips
   and segments. A chosen tab is 600 with a 3 px line under it.
3. **One row template.** Every list row has 6 of air over its title and under its last text line, a 48 floor,
   a title of at most 3 lines (up to about 133 % text), exactly one meta line whose last part may end in an
   ellipsis, and at most one trailing control. No dividers between rows. The ring's column is 0 px wide.
4. **One section rhythm.** Section heading 18/24 600 (19.8 at 110 %), 24 above and 4 below its box.
5. **Headers.** A detail view is: back row, title directly under it, one meta line, controls. The journal's
   title row carries the day-step arrows and ⋯. Control's back row reads "‹ Arbete" and its title "Kontroll"
   stands under it.
6. **States.** The frame is always real; only the content changes. The loading skeleton has no visible text and
   follows the row template. Undo keeps the row in place with a filled ring. A failure is an icon, a heading,
   one sentence and "Försök igen".
7. **Inline cards** end in a single link row ("Öppna Status · 10 fler ›").
8. **Fold row** (`Fold`, `ui/fold.tsx`): one component for every collapsible group: "Text (n) ⌄" in the section
   type, an optional meta line, the chevron on the content edge, 48 target, full width, no surface.
9. **Action row** (`.sk-action-row`): a 24 glyph in the ring's column, text in the row type on the title's x,
   48 high, no surface and no edge. Used for "+ Lägg till steg", "+ Koppla kontakt", "Flytta N försenade till
   imorgon" and "Pausa minnet".
10. **Locked:** compact 40/48, targets at least 48, no dividers between rows, no bottom navigation, no ×
    on an inline contact chip, contact ways folded, Control has three tabs.

## 1. Principles

1.1 **One rule per thing.** The same thing looks the same in every room: same measures, same words, same counter format.

1.2 **Content first.** Controls above content take at most one row per level. What is rarely used lives in ⋯.
There are no standing create fields: creating sits behind +, so between the room strip and the content there is
at most one row of controls.

1.3 **Ink means do, outline means here.** *Chosen* (active room, chosen segment, chosen chip, chosen day) has
one form in both themes: surface fill, 2 px outline in `--sk-fg`, weight 600. *Inverse fill* (ink) means only
the primary action, and a view has at most one. Inline cards have none. In dark mode the ink is dimmed
(`#c8c8cc`) so no surface is brighter than that. One mark per level: the outlined box says which room, an
underline says which view inside the room.

1.4 **Thumb and eye.** The target is 48 × 48 wherever the code gives it (`--sk-tap-lg`, 3rem); the base unit
`--sk-tap` is 44 (2.75rem), and inline cards, which must fit without scrolling, and the leading column of a list
row use 44. Everything pressable looks pressable. Colour never carries meaning alone.

1.5 **The host decides.** Colours, typeface and radii read the host's variables first and fall back to fixed
values in `light-dark()`. Every rule holds in light and dark mode.

1.6 **The same words everywhere.** "idag" and "imorgon" are one word, lower case inside a meta line and upper
case first in a heading or label. Headings and buttons do not end in a full stop; sentences do. A quantity
always has a unit ("8 st", "2 l").

1.7 **A row title has at most 3 lines in full-screen lists up to about 133 % text.** Above that it is not cut
and the detail view shows it whole. The meta line is exactly one line; only its last part may end in an
ellipsis, and no part is left out. Excerpts have at most 2 lines and inline titles at most 2.
`--sk-row-title-lines` is 3 in full screen and `none` when the frame is narrower than 19 rem (`ui/layout.css`).

## 2. Tokens (`mcp-apps/ui/tokens.css`)

**Type scale.** No other sizes or weights are allowed.

| Token | px / line | Weight | Used for |
|---|---|---|---|
| `--sk-type-title` | 22 / 28 | 600 | view title: task, contact, list, the journal's date, "Kontroll" |
| `--sk-type-card` | 18 / 24 | 600 | inline card title |
| `--sk-type-row` | 16 / 20.8 | 400 | row title in every list, and "add" rows |
| `--sk-type-body` | 16 / 24 | 400 | running text: description, journal text, summary, empty text |
| `--sk-type-label` | 14 / 18 | unchosen 500 `--sk-muted`, chosen 600 `--sk-fg` | room strip, tabs, chips |
| `--sk-type-button` | 14 / 18 | 600 | compact button |
| `--sk-type-label-strong` | 16 / 20 | 600 | full button, back link, "Öppna …" |
| `--sk-type-menu` | 16 / 20 | 500 | menu rows |
| `--sk-type-section` | 18 / 24 (19.8 / 26.4 at 110 %) | 600 | section heading in `--sk-fg`, never red; the counter "(n)" is `--sk-muted` 400 (`.sk-count`) |
| `--sk-type-meta` | 14 / 17.5 | 400 | meta line, card kicker, status chips, help text |
| `--sk-type-caption` | 12 / 16 | 500 | day strip weekday and "Idag" |

**Spacing** follows 4, 8, 12, 16, 24, 32 (`--sk-s1`–`--sk-s6`). The side margin is 16 (12 below 400 px or from 150 % text).

| Place | Spacing |
|---|---|
| frame top → room strip (full screen) | 8, on top of the host inset |
| room strip → first row | 4 |
| row template | `--sk-row-pad` 6 over the title and under the last text line, `--sk-row-min` 48 |
| section heading | 24 from the last row's box (`--sk-section-above`), 4 to the first row's box (`--sk-section-below`); beside lists of one-line 48 rows the row's extra air (`--sk-row-air-extra`) is taken off so the glyph distances are the same |
| between blocks in one view | 16 |
| between buttons | 8 |
| create field → receipt line | 4 |

**Touch targets.** One rule: the base is 44 (`--sk-tap`) and the minimum is 48 (`--sk-tap-lg`) for primary buttons,
fields, + and icon buttons. The exceptions are the inline cards and the leading column of a list row, which stay at 44.
A control drawn lower than its target gets a transparent `::after`. Adjacent targets never overlap. Layout
tests ask the browser which control a tap at each pixel reaches and require zero conflicts.

**Colour roles.** The host variable is read first; the fallback is `light-dark(light, dark)`.
Red is only for overdue, errors and deletion; "Idag" is `--sk-muted`, never amber.

| Role | Token | Light / dark fallback | Rule |
|---|---|---|---|
| background | `--sk-bg` | #ffffff / #1c1c1e | |
| surface (card, strip) | `--sk-surface` | #f4f4f5 / #2a2a2d | |
| text | `--sk-fg` | #1f1f1f / #ededed | |
| written text under a title | `--sk-fg-2` | `color-mix` of `--sk-fg` 55 % and `--sk-muted` | an excerpt, between the title and the meta line |
| muted text | `--sk-muted` | #5f6368 / #a1a1aa | metadata, placeholders (at least 4.5:1) |
| divider | `--sk-line` | #e4e4e7 / #3a3a40 | only under the room head and the tab row, never between rows |
| outline | `--sk-border` | #8a8a90 / #75757d | secondary buttons, fields, chips, panels (at least 3:1 against both page and surface) |
| chosen | `--sk-selected-bg`, `--sk-selected-line`, `--sk-selected-width` | #e8e8e8 / #3a3a3a, `--sk-fg`, 2 px | chosen chip and segment: fill, 2 px outline (the edge plus 1 px inset, so nothing moves), 16 px tick (`--sk-check`), 600 |
| active navigation | `--sk-nav-active-bg/-fg/-line` | = `--sk-bg` / `--sk-fg` / `--sk-fg` | active room and chosen day: page colour on the strip's surface, 2 px outline, 600 |
| inverse (ink) | `--sk-inverse-bg/-fg` | #1f1f1f / #c8c8cc, text #fff / #1c1c1e | only the primary action; the host's `--color-background-inverse` wins |
| overdue | `--sk-overdue-fg` | #b42318 / #ff8a80 | text only |
| error | `--sk-danger-*` | tokens.css | error icon, destructive menu text |
| skeleton | `--sk-skeleton` | 11 % `--sk-fg` in `--sk-bg` | the page's own grey |
| focus ring | `--sk-ring` | #2563eb / #7aa7ff | one ring everywhere: 2 px, 2 outside; inside the box where the box meets an edge (room tabs, icon buttons, ⋯ menu entries) |

An accent palette (`--sk-accent-<name>-line`, eight names) exists for domain colours; only the line is defined.

**Radii.** 8 for buttons, fields and tab markers; 12 for cards and panels; 999 only for chips and avatars.

## 3. Components

**Room strip (Rumsremsan).** Four equal tabs (`flex: 1 1 0`) in `--sk-type-label`, 40 high: cells 32 drawn in a
4 px frame, each with a 48 target. The active room is drawn *chosen*; the others are `--sk-muted` 500, so only
the current place is bold and the weight change moves nothing sideways. When the four labels do not fit on one
line (measured, no breakpoint) the strip becomes a room picker: the active room's name and ⌄ ("Arbete ⌄"),
opening the same menu with a tick on the chosen room. There is no 2 × 2 grid. The strip shows in every
full-screen room; detail views mark the parent room. In Control the strip has no chosen room (no
`aria-current`, labels all muted; the picker reads "Rum ⌄" / "Rooms ⌄", no item has `aria-checked`). It is
`position: sticky` on the page colour and the fixed chrome is bounded: 96.4 at 110 %, 99 at 150 %, 104 at 200 %.

**Room head (Rumshuvud)** is the row under the strip, 44 high. On the left are the room's tools: tabs (Work),
a search field (Contacts) or the date title (Journal). The room's name is never repeated as a title. On the
right are icon buttons in a fixed order counted from the right: ⋯ outermost, then +, then search; their centres
are 28, 76 and 124 from the right edge (384, 336, 288 at 412), 48 apart, so targets of 48 × 48 meet in the gap.
The head stays one row at every width and text size. When the tabs do not fit beside the icons they are replaced by a view
picker with the chosen view's name and ⌄ ("Status ⌄"), opening the same menu as ⋯. The search field in Contacts
has no frame but a field surface (`--sk-surface`, radius 8, 40 drawn, 44 target, 8 under the strip); focus is a
2 px inset ring (a system `Highlight` outline under forced colors). Search is a standing field where search is
the room's main action (Contacts) and an icon where tabs take the row (Work). Every room's ⋯ menu ends with "Kontroll"
("Control").

**Back row (Tillbakarad)** on detail levels is 44 high with a 48 target, 4 under the strip, on the same y as the
room head. On the left is "‹ Parent" as a text button (`--sk-type-label` 600, no frame) that always names the
destination. On the right is only ⋯: no pencil and no +. "Redigera" is the first item in ⋯, and a tap on the title edits too.
The title (`--sk-type-title`) follows directly under the back row, without a kicker. Actions never sit on the
title row. Links are removed in ⋯ as "Ta bort koppling till {name}", one item per link, with Undo.

**Icon button (Ikonknapp).** No frame; a 44 × 44 box with a 24 glyph, 48 target (`::after`). Glyphs come from
`ui/icons.tsx`, so there is one ⋯ and one ›. Everything trailing ends on the content edge (a 24 glyph is centred
28 from the right). Row chevrons use `--sk-chevron` = clamp(24 px, 1rem, 32 px). `aria-label` is required. An
open ⋯ or search has no fill of its own (its box reaches 10 into the side margin, past the panel under it); the
panel or field it opened shows the state. In the ⋯ panel each entry reaches 12 into the panel's padding, so its
ring lies inside the entry, 8 clear of the text and under the hairline above.

**Buttons (Knappar).** All radius 8.
- *Primary* `.sk-btn--primary`: the inverse pair, 600. At most one per screen, none inline. Full: 48 high,
  16/20. Compact `.sk-btn--compact`: 40 drawn, 48 tap, 14/18. Round `.sk-iconbtn--primary`: the + of list heads, an
  ink circle; while disabled it is a plain tertiary glyph and while its create field is open it is drawn held.
- *Secondary* `.sk-btn--secondary`: no fill, 1 px `--sk-border`, `--sk-fg` 600. At most two per screen.
- *Tertiary* `.sk-btn--quiet`, `.sk-btn--open`: no surface, `--sk-fg` 600, `--sk-surface` while held. Any number,
  at most one per row.
- *Destructive* `.sk-btn--danger`: `--sk-overdue-fg` 600, no fill, no edge. Only in ⋯ and the row menu, followed by Undo.
- Disabled is opacity 0.5. A "+" prefix is used only when the button creates something directly in the app; what goes through Claude
  gets none ("Berätta mer om dagen").

**Tabs versus chips (Flikar).** *Tabs* switch between views of the same content (Agenda/Status/Projects;
Control's Deleted/History/Sidekick's memory). They are left-packed with width by content, `--sk-tabs-h` high
(min(48 at 110 %, 56)), no fill; chosen is 600 `--sk-fg` with a 3 px line, unchosen 500 `--sk-muted`; a
hairline runs the full width under the row. If they do not fit they become the view picker (Control's, which has no icons,
may wrap at 200 %). *Chips* never filter. The only chip is the *property chip* in detail views ("fre 30 okt ⌄", "Att göra ⌄"):
40 high, 48 target, 1 px `--sk-border`, radius 8, 14/18 500, a ⌄ at the end; it shows a value, so it has no chosen state; a tap opens
the date picker or a menu with a tick on the current value. In menus, chips do have the chosen state. The
segmented control (Control, draft review) has a 1 px outline, radius 8 and equal segments; its chosen segment uses the
chosen state.

**Chosen states (Valda lägen).** One form: the chosen fill, a 2 px outline in `--sk-fg`, 600, plus a 16 px tick on
chips and segments. Rooms and days use the active-navigation pair. Tabs use the 3 px line.

**Row (Listrad).** Every room draws the same row (see §0.3 and §1.7). Order of the meta line: time/overdue ·
status · project/link, one line, the last part may end in an ellipsis; each part is unbreakable and " · " hangs in the column gap. Overdue is
red text on the time only ("5 dagar försenad"). A meta line never repeats its group.
- *Leading column:* a ring (task, item; 22 drawn, 24 glyph, 32 from 133 % text; `--sk-ring-glyph`), a 32 avatar
  (contact), or none (notes start at 16). The ring's button is `--sk-lead-w` wide and hangs into the margin so the ring starts
  on the content edge and the title follows 12 later; the ring's column costs 0 px. Its target is the whole column in
  the row's height; a held ring shows a 40 disc in `--sk-surface` behind it. "Mark done" is the same circle in Work and
  Shopping. A done row at rest is an outlined tick in `--sk-muted`; steps are not struck through.
- *Trailing slot:* every row that opens a view ends with › (24 wide box, glyph 24, 16 below 400 px or from
  150 %; hidden in full-screen at 150 % text or more, where the whole row still opens). The whole row opens
  (`::after` of the title button covers it); the ring, Undo and quick actions sit above that cover. A row that opens
  nothing has neither › nor ⋯. Quantities are right-aligned with `tabular-nums` at the content edge.
  There is no ⋯ in list rows.
- *Quick actions (Snabbval):* a long press (`contextmenu`), Shift+F10 or the menu key opens the row menu
  (`aria-keyshortcuts`); the same choices exist in the detail view. A visually hidden button "Fler val för {title}" opens
  it for screen readers. The menu has two labelled groups, Status (To do · In progress · Blocked · Done) and Date (Today ·
  Tomorrow · Next week · Pick a date …), as chips in the chosen state; the open row is the panel's first row with × (48 × 48, "Stäng")
  in the chevron's column; the panel has `--sk-surface`, 1 px `--sk-border`, radius 12, and keeps 8 from the content edge.
  "Pick a date …" is itself the date control: a transparent native date input fills the chip's target. At 150 % text or more
  Status and Date become fold rows. After opening, the menu scrolls into view above the host's reply field
  (`scroll-margin-block-end`).
- *Tips:* the long-press tip ("Håll inne en uppgift för fler val.") sits last in the list in muted meta type until the first
  use; with a fine pointer it reads "Högerklicka … eller tryck Shift+F10 …" and is the row's `aria-description`. It takes no frame and pushes nothing down.
- *Right-aligned actions* (Undo, Restore) are compact tertiary buttons in the trailing slot, centred on the title line; a long
  title keeps its width and the button moves to the meta line's middle, and the row grows to fit it.
- *Add rows:* "+ Lägg till steg", "+ Koppla kontakt", "+ Lägg till vara" are action rows (48, the + in the ring's column).
- Titles and meta lines use `overflow-wrap: break-word` and `hyphens: manual`, never `anywhere`.

**Note row (Anteckningsrad).** One row for Journal and Contact: the title, the meta line ("12:30 · Anna Andersson · 1 uppgift"),
then an excerpt of at most 2 lines in `--sk-fg-2`. › aligns with the title line. No icon, no frame, no surface.

**Chevron rule (Chevronregeln).** › means "opens a view". ⌄ right after a label means "unfolds" and turns when open; › is
never used to unfold. ⋯ lives only in heads (room head and back row), never in a list row. An undone row that has collapsed shows no ›.

**Section heading.** 18/24 600 in `--sk-fg`, see §0.4. A section without content shows no heading. Counters read "Name (n)" and appear
only where the number carries a decision: "Försenade (2)", the status groups in Status, "Köpta (1)". Time groups and stores have none. In running
text counts are words: "1 av 7 köpta". *Which number:* a heading counter counts open rows, the same list as the section's action ("Flytta 4 …");
a row that still shows Undo is a receipt and counts in the group it now belongs to. Headings inside inline cards have no counter.

**Create (Skapa).** Two levels, one rule. + in a room head creates an object at the room's top level (task, contact); a "+ Lägg till …" row creates a
part inside the open object (step, link, item). Nothing is open at rest; + unfolds `.sk-createfield` 8 under the row, with focus.
The field is 48 high with a placeholder example, followed by a 48 square: × ("Stäng") when empty, the primary + ("Lägg till")
when it has text. Return creates and keeps the field open; Esc and × close it and return focus to +. If the new object lands out of view the field shows a
receipt "Tillagd: {name} · {group}" (`aria-live="polite"`), 4 under the field. In a grouped list the add row stands before the groups (Shopping);
in an ungrouped sublist it stands last. A standing text field exists only in Contacts, and always means search.

**Inline card.** A card is `--sk-surface`, radius 12, padding 16, no scrolling, no ink. Parts in fixed order: the *kicker*
(`--sk-type-meta`, muted: "Arbete · ons 4 nov"), the *title* (`--sk-type-card`), the *body* of at most 3 rows with no
sub-headings and no status glyphs (a row is title + metadata), at most one muted meta line, and a single link row. The
link ("Öppna Status · 10 fler ›", `OpenFoot`) is tertiary, 40/48, and the card has 8 under it. The count is the same
function in every card (`hiddenRows`: the target view's rows minus the card's visible rows). A name that opens something is a link: `--sk-fg`, underlined 1 px.
Work's inline row (`InlineRow`) is one title line with ellipsis in full width and its meta on its own line; the whole row opens
and it ends with ›. Heights at 412 (110 % text): agenda card ≤ 340, receipt cards ≤ 250, none above 450 including the host's title row.
The board card's bar uses mid-grey for To do, ink for In progress, and a diagonal hatch in ink inside a 1 px ink edge for Blocked; it never uses red. Receipts say the outcome:
"Tillagd: …", "Uppdaterad: Mjölk, nu 2 l", "Fanns redan: Mjölk".

**States (Tillstånd).** The frame (strip, head, back row) is always drawn for real; only the content changes.
- *Loading:* no visible text (a sentence is read by screen readers through `aria-live`). The skeleton is built from
  the same components as the loaded view, with the row template: a ring outline in `--sk-skeleton`, one title bar per
  title line, one meta bar. Rows show after 300 ms. It does not guess group structure: one heading placeholder and five rows with
  different widths, and the first row stands on the loaded view's y (±2). The pulse stops under `prefers-reduced-motion`.
- *Load failure:* no box. In the row system: a 24 icon in `--sk-danger-line` in the ring's column, a heading in row type 600
  without a full stop ("Uppgifterna kunde inte hämtas"), one muted sentence, and "Försök igen" (primary). The sentence is "Sidekick svarade inte." alone; "Kontrollera
  anslutningen." is added only when the cause is a network failure. While retrying the button reads "Försöker igen…" with `aria-busy` and the create + stays disabled.
- *Refresh failure:* when a list was already shown it stays; one row on top reads "Kunde inte uppdatera" with a tertiary "Försök igen".
- *Write failure:* a line under the control in `--sk-danger-fg`: "Det gick inte att spara. Försök igen." and a retry text button.
- *Undo (Ångra):* the row stays in place for 15 s (`UNDO_MS`): filled ink ring with a knocked-out tick, muted title,
  no ›, the meta line "Klar", and "Ångra" as a compact secondary button with a 2 px timeline along its foot that shrinks to 0 in 15 s; the timer holds
  while the pointer or focus is on the row, and the timeline is not drawn under `prefers-reduced-motion`. The row's height is unchanged.
  Counters already count the open rows. When the time runs out a done row leaves its group (200 ms collapse, none under reduced motion); focus moves to the next row's ring, otherwise the previous, otherwise the
  heading. A moved row stays with "Flyttad till …" until the next read. "Klara här (n) ⌄", last in the agenda, lists rows done since it was opened.
- *Empty (Tomt):* one full sentence with a full stop in body type, muted, followed by the write action when there is one ("Inga steg än.",
  "Inget skrivet den här dagen.", "Papperskorgen är tom."). A search without a hit adds "Rensa sökningen". An empty detail section without a write path is not shown.

**Day strip (Dagremsan).** The journal's title row is the date ("Tisdag 3 november") with the add + (`.journal-day-add`, ink, 40/48) and ⋯ on the same row.
The row below is "‹ 29 okt–4 nov ›": ‹ and › are 48 × 48 icon buttons with 24 glyphs next to the interval (gap 0), plus "Idag"
after › when the week lacks today. They step one week to the same weekday; the strip chooses a day, a swipe steps a week and the arrow keys a day. › is
`aria-disabled` (`--sk-border`) in the week containing today and never hidden. The strip shows seven days ending today (or the week of the chosen day), no future days;
cells are equal width, 56 high, with weekday (caption, muted), date (18/22 500) and a marker row where a 6 px `--sk-muted` dot means "has notes". The chosen day is
drawn *chosen* (active-navigation pair).

**Day summary (Dagens sammanfattning).** The label "Dagen i korthet" is meta-sized, 15.4/600 `--sk-muted`, 4 above the summary, which is an ingress
in body type. "Anteckningar" follows 16 under the summary. A day with a summary or notes has no button in the content: the add action is the + in the title row.
An empty day shows one muted sentence 12 under the strip and the full button "Berätta om dagen" with a hint ("Claude frågar om dagen och
sparar det i dagboken."). A day shows "Gjort" (done that day, read-only) as a fold row under the summary: "Gjort ⌄" with a count line that lists only non-zero parts ("6 uppgifter · 3 steg · 12 varor köpta"),
collapsed by default; unfolded, one muted label per kind and rows without buttons.

**Task view.** Title → meta line ("5 dagar försenad · Projekt", overdue in `--sk-overdue-fg`) → one control row: date chip, status chip, "Markera klar" (compact primary) →
description ("Visa mer ›" is a meta-sized link). A task without steps shows only "+ Lägg till steg"; the "Steg" heading is for screen readers until a first step exists. Steps are rows with a square in
the ring's column and a long press for their menu.

**Contact view.** Title, then the profile line "relation · roll · organisation" (the same function as the list row, one line with an ellipsis, address never shown), nicknames under it. "Om {first name}"
holds the note. "Kontaktvägar ⌄" is a fold row with the meta "E-post och telefon", collapsed by default and absent when both are missing; unfolded it lists the values as rows that open through the
bridge's `openLink`. Then Tasks, Notes and Projects with the usual section rhythm.

**Control.** Back row "‹ Arbete" (or the source room), title "Kontroll", then three tabs: "Borttaget · Historik · Sidekicks minne" ("Deleted · History · Sidekick's memory"). Deleted rows end in a tertiary "Återställ"; History
lists changes and Claude's activity, newest first, with Undo/Restore in the same style; Sidekick's memory starts with "Minnet är på" at section level with its meta line, then
"Pausa minnet" as an action row, then the "Källor" group with a switch per source. The switch is a ruled track: on = `--sk-fg` track with a `--sk-bg` knob, off = 2 px `--sk-border` edge with a `--sk-muted` knob, no text beside it;
the state is the first part of the row's meta ("På · 214 anteckningar i minnet"). Tabs stick under the strip; the title scrolls away.

**Shopping.** A list with a progress row ("1 av 8 köpta" with a bar), "+ Lägg till vara" before the store groups, one ring per item (a tap on the ring buys, the rest of the row opens the item's edit form
like a long press), and "Köpta (n) ⌄" as a fold row. The tip "Tryck på ringen när du köpt något." shows until the first use and then never again.

## 4. Decisions

| Question | Decision | Reason |
|---|---|---|
| Chip height | 40 drawn, 48 target | It reads as pressable yet lower than buttons, so the hierarchy holds. |
| Filters in Agenda | Behind the search icon in the tab row | A text field would push the first task about 70 px down. |
| "Board" or "Status" | **Status**, back row "‹ Status" | The name says how the view groups, as a list (412) and as columns (≥ 768). |
| Kontrolls navigering | Control is a sub-view of the room the user came from; the back row reads "‹ Arbete" (or that room). Opened directly by Claude, the parent is Work (`CONTROL_PARENT`). The entry is "Kontroll" last in a room's ⋯ menu. The strip marks no room. | Control belongs to no room, and the back row carries the orientation. |
| Skelettets orientering | A real frame with the active room marked; the skeleton only replaces rows | Nothing jumps when the content arrives. |
| Restore: framed or text | Tertiary text in muted colour, 48 × 48, centred in the row's end | Three framed buttons are a wall; unframed text read as a heading. |
| › on rows | The chevron rule in §3 | The row's actions decide, not taste. |
| Counter under Undo | Counts open rows, the same number as the button | A heading and a button that disagree look wrong. |
| Create: top or bottom | At the top, but behind + | The host's reply field is at the bottom, and two fields stacked there get confused. |
| "Move to tomorrow" | A text row last in "Försenade", always with the count ("Flytta 4 försenade till imorgon") | The count is the decision. |
| "Refresh" | In ⋯ in both Agenda and Status | It exists in one view only and takes room. |
| Status filter in Work (Statusfilter i Arbete) | Groups instead of chips: Status shows To do/In progress/Blocked sections and a collapsed "Klar (n) ⌄" | A chip row clips, costs 52 px before the list and looks like a status picker. |
| Status in the task | A property chip with a menu next to the date | Segment + date field + ink button read as three heavy blocks. |
| ⋯ in list rows | None; quick actions by long press and Shift+F10, the same choices in the detail view | A ⋯ per row takes about 60 of 360 px at 200 %. |
| Chosen colour in dark mode | The same model as light: `#3a3a3a` fill, outline `#ededed`, 600 | One model in both themes; the ink stays dimmed. |
| Contact e-mail and phone | In the folded "Kontaktvägar", no labels | Phone and e-mail fields in the main view crowd the contact. |
| Bottom navigation | No | The host's reply field is at the bottom and two bottom rows stack. |
| × on an inline contact chip | None; "Kopplad till Bo Berg" is text, unlinking is in full screen | It is easy to hit by accident. |

## 5. Conventions and verification

- **Headings for assistive technology.** A view named by its active tab (for example "Borttaget") has an `h2` for screen readers only
  (`.control-sr-only`); the visible title would repeat the tab. A section whose heading is redundant keeps it hidden until it has content.
- **Refresh** is a ⋯ item ("Uppdatera"). A view that re-reads through its `refreshKey` shows no refresh control of its own.
- **Language.** Swedish is the default and English the alternative; both locales carry the same label keys (locale parity is a test). Labels
  in this document are given in Swedish with English only where the pair differs structurally.
- **Large text.** The frame is a size container (`sk-frame`); width and text scale decide density, not media queries. At 360 px and 200 % nothing is
  removed: titles run on, the room strip becomes a picker, and every target stays at least 48. The › stays a 24 glyph in inline cards
  and in lists that are not full screen; in full-screen rows at 150 % text or more it is hidden (§3 Trailing slot) and the
  whole row still opens the record.
- **Host theme and size.** Colours and radii come from the host's CSS variables with the `light-dark()` fallbacks in §2; safe-area insets come from
  `--host-safe-*`. The frame keeps a foot reserve of 6 rem or the host's bottom inset, whichever is larger.
- **Motion.** The skeleton pulse, the Undo timeline and the collapse of a finished row stop or become instant under `prefers-reduced-motion: reduce`.
- **Keyboard and touch.** Every action has a keyboard path (Enter/Space, arrow keys on the day strip, Shift+F10 for row menus, Esc to close and return focus). A long press never moves focus.
- **Verification.** Build with `npm run build:mcp-app`, run the Vitest view tests and the layout tests on the sandboxed host
  (`frontend/playwright.mcp-app.config.ts`), and measure with `getBoundingClientRect` in light and dark mode at 320 and 412 px and at 100, 150 and 200 % text.
  A simulated host is not a test in a real Claude or Android host.
