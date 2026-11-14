import { describe, expect, it } from "vitest";
import { dirtyDomains } from "@/features/mcp-apps/dirty-domains";

// Journal entries show Contact and Project names, so writes to them mark the Journal stale too.
describe("dirtyDomains marks the Journal after Contact and Project writes", () => {
  it.each([
    "update_contact",
    "create_contact",
    "archive_contact",
    "update_project",
    "create_project",
  ])("%s marks the journal", (tool) => {
    expect(dirtyDomains(tool)).toContain("journal");
  });

  it("update_contact marks contacts, work and journal", () => {
    expect(dirtyDomains("update_contact")).toEqual([
      "contacts",
      "work",
      "journal",
      "control",
    ]);
  });

  it("update_project marks work, contacts and journal", () => {
    expect(dirtyDomains("update_project")).toEqual([
      "work",
      "contacts",
      "journal",
      "control",
    ]);
  });

  it("a Task write does not mark the journal", () => {
    expect(dirtyDomains("update_task")).not.toContain("journal");
    expect(dirtyDomains("update_task")).toEqual([
      "work",
      "contacts",
      "control",
    ]);
  });

  it.each(["get_contact", "list_projects"])(
    "the read %s marks nothing",
    (tool) => {
      expect(dirtyDomains(tool)).toEqual([]);
    },
  );
});
