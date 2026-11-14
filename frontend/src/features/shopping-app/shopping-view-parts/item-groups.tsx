import { Fold } from "../../mcp-apps/ui/fold";
import { finePointer } from "../../mcp-apps/ui/shortcuts";
import type { ShoppingItem } from "../transport";
import { wasBuyAgainUsed } from "./helpers";
import { ListRow } from "./list-row";
import { StoreRow } from "./store-row";
import type { RowEnv } from "./row-parts";

/** One row, drawn as the store view's large row or the list view's row. */
function ItemRow({
  item,
  grouped,
  inPlace = true,
  storeMode,
  env,
}: {
  item: ShoppingItem;
  grouped: boolean;
  inPlace?: boolean;
  storeMode: boolean;
  env: RowEnv;
}) {
  return storeMode ? (
    <StoreRow item={item} inPlace={inPlace} env={env} />
  ) : (
    <ListRow item={item} grouped={grouped} inPlace={inPlace} env={env} />
  );
}

/**
 * The open groups (a heading and its rows per store; no heading when no row has a store), then, in the compact view, the row that expands or folds
 * the view in place.
 */
export function ItemGroups({
  shownGroups,
  rowCount,
  shownCount,
  folded,
  compact,
  expanded,
  storeMode,
  shopLabel,
  env,
  onExpanded,
}: {
  shownGroups: { store: string | null; shown: ShoppingItem[] }[];
  rowCount: number;
  shownCount: number;
  folded: boolean;
  compact: boolean;
  expanded: boolean;
  storeMode: boolean;
  /** The shop the view was opened for: its own heading is left out, the view's title already names it. */
  shopLabel?: string;
  env: RowEnv;
  onExpanded: (value: boolean) => void;
}) {
  const { labels: t } = env;
  // `otherStore` names the rest beside stores; with no store on any row there is nothing to tell it from.
  const storeless = shownGroups.every(({ store }) => store === null);
  return (
    <>
      {shownGroups.map(({ store, shown }) =>
        folded && shown.length === 0 ? null : (
          <section key={store ?? ""} className="shopping-group">
            {storeless ||
            (shopLabel !== undefined && store === shopLabel) ? null : (
              <h3>{store ?? t.otherStore}</h3>
            )}
            <ul
              className={
                folded
                  ? "shopping-items shopping-items--folded"
                  : "shopping-items"
              }
            >
              {shown.map((row) => (
                <ItemRow
                  key={row.id}
                  item={row}
                  grouped={store !== null}
                  storeMode={storeMode}
                  env={env}
                />
              ))}
            </ul>
          </section>
        ),
      )}
      {folded && rowCount > shownCount && (
        <div className="shopping-more">
          <button
            type="button"
            aria-expanded={false}
            onClick={() => onExpanded(true)}
          >
            {t.showAll(rowCount)}
          </button>
        </div>
      )}
      {compact && expanded && (
        <div className="shopping-more">
          <button
            type="button"
            aria-expanded={true}
            onClick={() => onExpanded(false)}
          >
            {t.showFewer}
          </button>
        </div>
      )}
    </>
  );
}

/**
 * The `boughtCount` fold row (with its chevron), inline and in fullscreen alike. `purchased` is the settled bought items, newest first,
 * each with the day it was bought; the store view says once, above them, that the ring buys an item again.
 */
export function PurchasedFold({
  purchased,
  open,
  storeMode,
  env,
  onToggle,
}: {
  purchased: ShoppingItem[];
  open: boolean;
  storeMode: boolean;
  env: RowEnv;
  onToggle: () => void;
}) {
  if (purchased.length === 0) return null;
  return (
    <div className="shopping-purchased">
      <Fold
        text={env.labels.boughtCount(purchased.length)}
        open={open}
        onToggle={onToggle}
      />
      {open && storeMode && !wasBuyAgainUsed() && (
        <p className="shopping-buy-again-tip">
          {finePointer() ? env.labels.buyAgainKeys : env.labels.buyAgainTip}
        </p>
      )}
      {open && (
        <ul className="shopping-items">
          {purchased.map((row) => (
            <ItemRow
              key={row.id}
              item={row}
              grouped={false}
              inPlace={false}
              storeMode={storeMode}
              env={env}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
