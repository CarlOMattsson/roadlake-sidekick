/**
 * Work App command contract. Views see only these typed reads and writes; the MCP adapter maps
 * them to tools/call and reads structuredContent. Types follow contracts/mcp-tools.generated.json
 * through the generated tool types. Extra fields are allowed.
 *
 * This file only re-exports, so importers keep one import path. The parts:
 *  - transport-records.ts: the record types (Task, Project, Step, Contact and so on)
 *  - transport-frames.ts: navigation frames and the board and agenda filters
 *  - transport-api.ts: the WorkTransport type (every read and write)
 *  - root-from-result.ts: the frame a tool result opens, with the guards of result-guards.ts
 */
export * from "./transport-records";
export * from "./transport-frames";
export type { WorkTransport } from "./transport-api";
export { isWorkItemRecord } from "./result-guards";
export { journalEntriesOf, rootFromToolResult } from "./root-from-result";
export {
  isForbidden,
  writeFailure,
  type WriteFailure,
} from "../../../lib/mcp/errors";
