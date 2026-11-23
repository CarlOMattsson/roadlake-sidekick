import type { RoomTransport } from "../../mcp-apps/room-types";
import { toolOffered } from "../../mcp-apps/tool-support";
import type {
  ApproveArguments,
  AutomationPage,
  AutomationRecord,
  AutomationReport,
} from "./model";
import type { ToolResults } from "@/lib/mcp/tool-results.generated";

/** The most automations one read lists (list_automations' own limit). */
export const AUTOMATION_PAGE = 50;
/** The most highlights the report gives (MAX_HIGHLIGHTS on the server). */
export const REPORT_HIGHLIGHTS = 10;

/**
 * The automations' reads and the approval, each an existing tool called through the room's transport (the host's
 * tools/call): no credential and no request of the app's own. `offered` is false where the host cannot answer the
 * reads, and the room then shows no way to the automations. The report and the approval are offered only where the
 * host has those tools; approve_automation is app-only and the host asks the person again before it runs.
 */
export type AutomationTransport = {
  offered: boolean;
  list: () => Promise<AutomationPage>;
  get: (id: string) => Promise<AutomationRecord>;
  report?: () => Promise<AutomationReport>;
  approve?: (args: ApproveArguments) => Promise<AutomationRecord>;
};

export function createAutomationTransport(
  transport: RoomTransport,
): AutomationTransport {
  const { call } = transport;
  return {
    offered:
      toolOffered(transport, "list_automations") &&
      toolOffered(transport, "get_automation"),
    list: () =>
      call<AutomationPage>("list_automations", { limit: AUTOMATION_PAGE }),
    get: (id) =>
      call<ToolResults["get_automation"]>("get_automation", {
        automation_id: id,
      }).then((result) => result.automation),
    ...(toolOffered(transport, "get_automation_report")
      ? {
          report: () =>
            call<AutomationReport>("get_automation_report", {
              limit: REPORT_HIGHLIGHTS,
            }),
        }
      : {}),
    ...(toolOffered(transport, "approve_automation")
      ? {
          approve: (args: ApproveArguments) =>
            call<ToolResults["approve_automation"]>(
              "approve_automation",
              args,
            ).then((result) => result.automation),
        }
      : {}),
  };
}
