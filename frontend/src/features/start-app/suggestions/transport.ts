import type { RoomTransport } from "../../mcp-apps/room-types";
import { toolOffered } from "../../mcp-apps/tool-support";
import type { DecisionsResult, SuggestionPage, UndoResult } from "./model";
import type { ToolResults } from "@/lib/mcp/tool-results.generated";

/** One decision as decide_suggestions takes it. */
export type DecisionInput = {
  suggestion_id: string;
  expected_version: number;
  decision: "approve" | "dismiss";
  /** The owner approved a flagged card after seeing why (the app only). */
  confirmed?: boolean;
};

/**
 * The inbox's reads and writes, each an existing tool called through the room's transport (the host's tools/call): the
 * app holds no credential and makes no request of its own. Approving a whole group and undoing are offered only where
 * the host has those tools; without them the inbox decides card by card and offers no Ångra.
 */
export type SuggestionTransport = {
  list: (cursor?: string) => Promise<SuggestionPage>;
  get: (id: string) => Promise<ToolResults["get_suggestion"]>;
  decide: (items: DecisionInput[], key: string) => Promise<DecisionsResult>;
  approveGroup?: (
    digest: string,
    ids: string[],
    key: string,
  ) => Promise<DecisionsResult>;
  undo?: (id: string, version: number, key: string) => Promise<UndoResult>;
};

export const PAGE_SIZE = 25;

export function createSuggestionTransport(
  transport: RoomTransport,
): SuggestionTransport {
  const { call } = transport;
  return {
    list: (cursor) =>
      call<SuggestionPage>("list_suggestions", {
        limit: PAGE_SIZE,
        ...(cursor ? { cursor } : {}),
      }),
    get: (id) =>
      call<ToolResults["get_suggestion"]>("get_suggestion", {
        suggestion_id: id,
      }),
    decide: (items, key) =>
      call<DecisionsResult>("decide_suggestions", {
        items,
        idempotency_key: key,
      }),
    ...(toolOffered(transport, "approve_suggestion_group")
      ? {
          approveGroup: (digest: string, ids: string[], key: string) =>
            call<DecisionsResult>("approve_suggestion_group", {
              group_digest: digest,
              suggestion_ids: ids,
              idempotency_key: key,
            }),
        }
      : {}),
    ...(toolOffered(transport, "undo_suggestion")
      ? {
          undo: (id: string, version: number, key: string) =>
            call<UndoResult>("undo_suggestion", {
              suggestion_id: id,
              expected_version: version,
              idempotency_key: key,
            }),
        }
      : {}),
  };
}
