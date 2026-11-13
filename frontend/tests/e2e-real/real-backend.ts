import { randomUUID } from "node:crypto";
import type { Page } from "@playwright/test";
import {
  deliverToolResult,
  openSimulatedApp,
  readBuiltApp,
  waitForAppInitialized,
} from "../e2e/mcp-host-fixture";

// The pieces the real-backend specs share. The host is still simulated (mcp-host-fixture.ts), but its tools/call goes
// to the real server started by server-setup.ts, with the one-run token, exactly as a host that proxies the app's
// tool calls does. The specs therefore prove the contract between the built app and the server's tools, not a fixture.

/** The result of one tools/call as the MCP server answers it. */
export type ToolResult = {
  isError?: boolean;
  content?: { type: string; text?: string }[];
  structuredContent?: Record<string, unknown>;
};

/** Calls one tool on the real server over MCP's streamable HTTP, the way a host forwards the app's call. */
export async function callTool(
  name: string,
  args: Record<string, unknown> = {},
): Promise<ToolResult> {
  const response = await fetch(`${process.env.E2E_BACKEND_URL}/mcp/`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${process.env.E2E_BACKEND_TOKEN}`,
      "Content-Type": "application/json",
      Accept: "application/json, text/event-stream",
    },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "tools/call",
      params: { name, arguments: args },
    }),
  });
  const body = await response.text();
  // The server answers one event ("data: {...}") or, with json_response, the bare JSON-RPC message.
  const data = body.startsWith("{")
    ? body
    : body
        .split("\n")
        .find((line) => line.startsWith("data:"))
        ?.slice("data:".length);
  if (!response.ok || data === undefined)
    throw new Error(`MCP ${name} failed: HTTP ${response.status}`);
  const message = JSON.parse(data) as {
    result?: ToolResult;
    error?: { message: string };
  };
  if (message.error) throw new Error(`MCP ${name}: ${message.error.message}`);
  return message.result ?? {};
}

/** A tool call that must succeed, for the setup and the checks of a spec; returns its structured content. */
export async function seed<T = Record<string, unknown>>(
  name: string,
  args: Record<string, unknown> = {},
): Promise<T> {
  const result = await callTool(name, {
    idempotency_key: randomUUID(),
    ...args,
  });
  if (result.isError)
    throw new Error(`${name} was refused: ${result.content?.[0]?.text}`);
  return result.structuredContent as T;
}

/** The task of exactly this title as the server lists it, for a spec that made it through the app. */
export async function findTaskByTitle(
  title: string,
): Promise<{ id: string; status: string; version: number } | undefined> {
  const read = await callTool("list_tasks", { limit: 100 });
  const tasks = (read.structuredContent?.tasks ?? []) as {
    id: string;
    title: string;
    status: string;
    version: number;
  }[];
  return tasks.find((task) => task.title === title);
}

/** A title no other spec (and no earlier run) uses, so a spec finds exactly its own records. */
export function uniqueTitle(label: string): string {
  return `${label} ${randomUUID().slice(0, 8)}`;
}

/**
 * Opens the app on the real server the way Claude does: the host calls `tool`, the server answers, and the host
 * hands that answer to the app. Later tool calls of the app go to the server as well.
 */
export async function openRealApp(
  page: Page,
  options: {
    tool: string;
    args?: Record<string, unknown>;
    locale?: "sv" | "en";
  },
) {
  const locale = options.locale ?? "sv";
  const opening = await callTool(options.tool, options.args ?? {});
  const opened = await openSimulatedApp(page, {
    resource: readBuiltApp("sidekick", locale),
    width: 390,
    height: 780,
    hostContext: {
      locale,
      theme: "light",
      displayMode: "fullscreen",
      availableDisplayModes: ["inline", "fullscreen"],
      toolInfo: { id: 1, tool: { name: options.tool } },
    },
    hostCapabilities: { serverTools: {}, message: {} },
    replies: {},
    forwardToolCall: callTool,
  });
  await waitForAppInitialized(page);
  await deliverToolResult(page, opening.structuredContent);
  return opened;
}
