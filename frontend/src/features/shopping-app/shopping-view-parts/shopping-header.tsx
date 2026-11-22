import { useContext, useId } from "react";
import type { RefObject } from "react";
import type { ShoppingList } from "../transport";
import type { ShoppingLabels } from "../labels";
import { BackHeader } from "../../mcp-apps/ui/back-header";
import { PlusIcon } from "../../mcp-apps/ui/icons";
import { RoomHead } from "../../mcp-apps/ui/room-head";
import type { useMoreMark } from "../../mcp-apps/update-reminder";
import type { HostSettingsEntry } from "../../mcp-apps/room-types";
import { RoomSurfaceContext } from "../../mcp-apps/ui/room-context";
import { MoreButton, MoreMenu } from "./more-menu";

/**
 * The head of the view: the title, the way back to the picker with the + and ⋯ of the fullscreen view, the ⋯ menu
 * and the hint.
 *
 * `wide` (fullscreen in a frame of at least 64rem, where the shell offers its one-row head): the lists stand beside the
 * chosen list, so there is no way back. The head is the shared room head in the shell's row (ui/room-head.tsx), with
 * + and ⋯ on the same places as in every room: + adds an item to the open list ("n"), or makes the first list while
 * there is none, and ⋯ is the room's menu. The list's name is the detail's own heading (shopping-view.tsx).
 */
export function ShoppingHeader({
  labels: t,
  id,
  list,
  headerTitle,
  busy,
  menu,
  canAdd,
  addOpen,
  addButton,
  moreOpen,
  moreButton,
  moreMark,
  editOpen,
  control,
  showHint,
  onBack,
  onToggleAdd,
  onToggleMore,
  onCloseMore,
  onToggleEdit,
  wide = false,
  onNewList,
  newOpen = false,
}: {
  labels: ShoppingLabels;
  id: string;
  list?: ShoppingList;
  headerTitle?: string;
  busy: boolean;
  /** The + and ⋯ of the list's head: the fullscreen view and the compact card have them. */
  menu: boolean;
  canAdd: boolean;
  addOpen: boolean;
  addButton: RefObject<HTMLButtonElement | null>;
  moreOpen: boolean;
  moreButton: RefObject<HTMLButtonElement | null>;
  moreMark: ReturnType<typeof useMoreMark>;
  editOpen: boolean;
  /** The last entry of the ⋯: Control, or the host's own settings (the phone). */
  control?: HostSettingsEntry;
  showHint: boolean;
  onBack: () => void;
  onToggleAdd: () => void;
  onToggleMore: () => void;
  onCloseMore: () => void;
  onToggleEdit: () => void;
  /** The wide frame's head (see above). */
  wide?: boolean;
  /** Wide, with no list to add to: + opens the "New list" field instead. */
  onNewList?: () => void;
  newOpen?: boolean;
}) {
  const { framed } = useContext(RoomSurfaceContext);
  const menuId = useId();
  const moreMenu = moreOpen && (wide || (menu && list)) && (
    <MoreMenu
      id={menuId}
      anchor={moreButton}
      control={control}
      onClose={onCloseMore}
    >
      {list && (
        <button
          type="button"
          className="sk-menu-item"
          aria-expanded={editOpen}
          onClick={onToggleEdit}
        >
          {t.editList}
        </button>
      )}
    </MoreMenu>
  );
  const moreTrigger = (
    <MoreButton
      label={moreMark.label}
      dot={moreMark.dot}
      open={moreOpen}
      menuId={menuId}
      buttonRef={moreButton}
      onOpenChange={(open) => {
        if (open !== moreOpen) onToggleMore();
      }}
    />
  );
  if (wide)
    return (
      <header className="shopping-head">
        <h1 className="shopping-visually-hidden">{t.title}</h1>
        <RoomHead
          scope="sidekick-shopping"
          keysTitle={t.title}
          // No view tabs: an empty cell takes their place, so the tools stand at the row's end as in every room.
          tabs={<span aria-hidden="true" />}
          add={
            list
              ? canAdd
                ? {
                    label: t.addItem,
                    expanded: addOpen,
                    disabled: busy,
                    onPress: onToggleAdd,
                    onKey: () => {
                      if (!addOpen) onToggleAdd();
                    },
                  }
                : undefined
              : onNewList && {
                  label: t.newList,
                  expanded: newOpen,
                  onPress: onNewList,
                }
          }
          addRef={list ? addButton : undefined}
          more={moreTrigger}
        />
        {moreMenu}
      </header>
    );
  return (
    <header className="shopping-head">
      {/* The strip above already says Shopping: framed, the heading stays for assistive technology only. */}
      <h1 className={framed ? "shopping-visually-hidden" : "sk-eyebrow"}>
        {t.title}
      </h1>
      {/* The way back to the rows, in the room itself: a list is chosen, so the picker is one tap away. The
            list's name is the title of this row; fullscreen keeps "Edit list" behind the ⋯ menu. A tap while
            a read or write runs is left out, so the reply of that read cannot show the old list again. */}
      {id && (
        <BackHeader
          label={t.backToLists}
          title={headerTitle}
          onBack={() => {
            if (!busy) onBack();
          }}
          actions={
            menu &&
            list && (
              <>
                {/* + is the list's primary: a round ink button left of ⋯. It opens the
                      create field at the top of the list; Enter adds and keeps it open, Esc or × closes it and gives
                      the focus back to +. */}
                {canAdd && (
                  <button
                    ref={addButton}
                    type="button"
                    className="shopping-add sk-iconbtn sk-iconbtn--primary"
                    aria-label={t.addItem}
                    aria-expanded={addOpen}
                    onClick={onToggleAdd}
                  >
                    <PlusIcon />
                  </button>
                )}
                {moreTrigger}
              </>
            )
          }
        />
      )}
      {moreMenu}
      {showHint && <p>{t.hint}</p>}
    </header>
  );
}
