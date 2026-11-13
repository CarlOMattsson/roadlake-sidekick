import type { JournalLabels } from "../labels";
import type { JournalDraft } from "../transport";
import {
  MAX_RELATIONS,
  RELATION_KINDS,
  linkKey,
  optionsFor,
  type Picked,
  type RelationKind,
} from "./decisions";
import { Disclosure } from "./disclosure";
import { RelationCheck } from "./relation-check";

/** The link candidates by kind, the AI's suggestions first, as one disclosure. */
export function RelationsSection({
  id,
  draft,
  count,
  open,
  onToggle,
  picked,
  declined,
  locked,
  onPick,
  onDeclinedChange,
  labels: t,
}: {
  id: string;
  draft: JournalDraft;
  count: number;
  open: boolean;
  onToggle: () => void;
  picked: Picked;
  declined: Record<string, boolean>;
  /** Busy or awaiting confirmation: no row can change. */
  locked: boolean;
  onPick: (kind: RelationKind, value: string, on: boolean) => void;
  onDeclinedChange: (key: string, value: boolean) => void;
  labels: JournalLabels;
}) {
  return (
    <Disclosure
      id={id}
      title={t.relations}
      foldTitle={t.relationsFold}
      count={count}
      open={open}
      onToggle={onToggle}
    >
      <p className="journal-muted">{t.relationsNote}</p>
      {RELATION_KINDS.every(
        (kind) => optionsFor(draft, kind, "").length === 0,
      ) && <p>{t.noRelations}</p>}
      {RELATION_KINDS.map((kind) => {
        const options = optionsFor(draft, kind, t.unknownCandidate);
        if (options.length === 0) return null;
        return (
          <fieldset key={kind} className="journal-fieldset">
            <legend>{t[kind]}</legend>
            {options.map((option) => (
              <RelationCheck
                key={option.id}
                option={option}
                checked={picked[kind].includes(option.id)}
                declined={declined[linkKey(kind, option.id)] === true}
                onDeclinedChange={(value) =>
                  onDeclinedChange(linkKey(kind, option.id), value)
                }
                disabled={
                  locked ||
                  (!picked[kind].includes(option.id) &&
                    picked[kind].length >= MAX_RELATIONS)
                }
                onChange={(on) => onPick(kind, option.id, on)}
                labels={t}
              />
            ))}
          </fieldset>
        );
      })}
    </Disclosure>
  );
}
