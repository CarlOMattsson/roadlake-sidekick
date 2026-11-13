import { useEffect, useId, useRef, useState } from "react";
import type { ShoppingItem, ShoppingTransport } from "../transport";
import type { ShoppingLabels } from "../labels";
import { onEnterKey } from "../../mcp-apps/ui/enter-key";
import { ErrorNotice } from "../../mcp-apps/ui/states";

type Contact = { id: string; display_name: string };

/**
 * The gift recipient as one control: the chosen contact by name with Change and Remove, or one button that opens a
 * contact search whose hits are picked directly. The id travels in a hidden field, so Save reads it with the rest of
 * the form. A host without a contact search (the mobile app) keeps a recipient that is already set and offers Remove
 * only.
 */
export function RecipientField({
  item,
  labels: t,
  contacts,
}: {
  item: ShoppingItem;
  labels: ShoppingLabels;
  contacts: ShoppingTransport["contacts"];
}) {
  const labelId = useId();
  const [recipient, setRecipient] = useState<{
    id: string;
    name: string;
  } | null>(
    item.recipient_contact_id
      ? {
          id: item.recipient_contact_id,
          name: item.recipient_contact_name ?? t.linkedContact,
        }
      : null,
  );
  const [picking, setPicking] = useState(false);
  const [query, setQuery] = useState("");
  const [hits, setHits] = useState<Contact[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [searching, setSearching] = useState(false);
  const queryField = useRef<HTMLInputElement>(null);
  // Opening the search puts the cursor in its field.
  useEffect(() => {
    if (picking) queryField.current?.focus();
  }, [picking]);

  async function search() {
    if (!contacts || !query.trim()) return;
    setSearching(true);
    setFailed(false);
    try {
      setHits((await contacts(query)).contacts);
    } catch {
      setFailed(true);
    } finally {
      setSearching(false);
    }
  }
  function stopPicking() {
    setPicking(false);
    setQuery("");
    setHits(null);
    setFailed(false);
  }
  function choose(contact: Contact) {
    setRecipient({ id: contact.id, name: contact.display_name });
    stopPicking();
  }

  return (
    <div
      className="shopping-recipient"
      role="group"
      aria-labelledby={labelId}
      data-picking={picking ? "" : undefined}
    >
      <span id={labelId} className="shopping-recipient-label">
        {t.recipient}
      </span>
      <input
        type="hidden"
        name="recipient_contact_id"
        value={recipient?.id ?? ""}
      />
      {recipient && !picking ? (
        <div className="shopping-recipient-current">
          <span className="shopping-recipient-name">{recipient.name}</span>
          {contacts ? (
            <button
              type="button"
              className="sk-btn--quiet"
              onClick={() => setPicking(true)}
            >
              {t.changeRecipient}
            </button>
          ) : null}
          <button
            type="button"
            className="sk-btn--quiet"
            onClick={() => setRecipient(null)}
          >
            {t.removeRecipient}
          </button>
        </div>
      ) : null}
      {!recipient && !picking && contacts ? (
        <button
          type="button"
          className="sk-btn--secondary shopping-recipient-choose"
          onClick={() => setPicking(true)}
        >
          {t.chooseContact}
        </button>
      ) : null}
      {picking ? (
        <div className="shopping-recipient-search">
          <div className="shopping-recipient-query">
            <label>
              {t.contactQuery}
              <input
                value={query}
                maxLength={200}
                ref={queryField}
                onChange={(event) => setQuery(event.target.value)}
                onKeyDown={(event) => onEnterKey(event, () => void search())}
              />
            </label>
            <button
              type="button"
              disabled={searching || !query.trim()}
              onClick={() => void search()}
            >
              {t.searchContact}
            </button>
          </div>
          {failed ? (
            <ErrorNotice
              placement="row"
              locale={t.dateLocale}
              message={t.contactSearchFailed}
              retrying={searching}
              onRetry={() => void search()}
            />
          ) : null}
          {hits?.length === 0 && !failed ? <p>{t.noContactFound}</p> : null}
          {hits && hits.length > 0 ? (
            <ul className="shopping-recipient-hits">
              {hits.map((contact) => (
                <li key={contact.id}>
                  <button
                    type="button"
                    className="sk-btn--secondary"
                    onClick={() => choose(contact)}
                  >
                    {contact.display_name}
                  </button>
                </li>
              ))}
            </ul>
          ) : null}
          <button type="button" className="sk-btn--quiet" onClick={stopPicking}>
            {t.close}
          </button>
        </div>
      ) : null}
    </div>
  );
}
