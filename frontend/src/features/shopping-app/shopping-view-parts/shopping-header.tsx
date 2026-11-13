import { useContext } from "react";
import type { RefObject } from "react";
import type { ShoppingList } from "../transport";
import type { ShoppingLabels } from "../labels";
import { BackHeader } from "../../mcp-apps/ui/back-header";
import { MoreIcon, PlusIcon } from "../../mcp-apps/ui/icons";
import { onEscapeKey } from "../../mcp-apps/ui/key-scope";
import type { useMoreMark } from "../../mcp-apps/update-reminder";
import type { HostSettingsEntry } from "../../mcp-apps/room-types";
import { RoomSurfaceContext } from "../../mcp-apps/ui/room-context";
import { MoreMenu } from "./more-menu";

/**
 * The head of the view: the title, the way back to the picker with the + and ⋯ of the fullscreen view, the ⋯ menu
 * and the hint.
 */
export function ShoppingHeader({
  labels: t,
  id,
  list,
  headerTitle,
  busy,
  fullscreen,
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
}: {
  labels: ShoppingLabels;
  id: string;
  list?: ShoppingList;
  headerTitle?: string;
  busy: boolean;
  fullscreen: boolean;
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
}) {
  const { framed } = useContext(RoomSurfaceContext);
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
            fullscreen &&
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
                <button
                  ref={moreButton}
                  type="button"
                  className="shopping-more-trigger sk-iconbtn"
                  aria-label={moreMark.label}
                  aria-expanded={moreOpen}
                  onClick={onToggleMore}
                  onKeyDown={(event) => {
                    if (moreOpen) onEscapeKey(event, onCloseMore);
                  }}
                >
                  <MoreIcon />
                  {moreMark.dot}
                </button>
              </>
            )
          }
        />
      )}
      {moreOpen && fullscreen && list && (
        <MoreMenu
          control={control}
          onClose={onCloseMore}
          onEscape={() => {
            onCloseMore();
            moreButton.current?.focus();
          }}
        >
          <button
            type="button"
            className="sk-menu-item"
            aria-expanded={editOpen}
            onClick={onToggleEdit}
          >
            {t.editList}
          </button>
        </MoreMenu>
      )}
      {showHint && <p>{t.hint}</p>}
    </header>
  );
}
