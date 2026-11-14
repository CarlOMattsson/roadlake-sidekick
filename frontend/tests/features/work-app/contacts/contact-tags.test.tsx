import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { TagChips, TagField, TagFilter } from "@/features/mcp-apps/ui/tags";
import { tagEn, tagSv } from "@/features/mcp-apps/ui/tag-labels";
import type { TagRecord } from "@/features/mcp-apps/ui/tag-vocabulary";
import { WorkView } from "@/features/work-app/view/work-view";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import {
  rootFromToolResult,
  type WorkContactSummary,
} from "@/features/work-app/transport/transport";
import {
  KEY,
  anna,
  contactRoot,
  transport,
} from "@tests/helpers/work-app-fixtures";

function tag(slug: string, contact: number, label = slug): TagRecord {
  return {
    id: `019f0000-0000-7000-8000-${String(contact).padStart(12, "0")}`,
    slug,
    archived_at: null,
    label,
    created_at: "2026-11-01T10:00:00Z",
    updated_at: "2026-11-01T10:00:00Z",
    version: 1,
    usage: {
      contact,
      domain: null,
      journal_entry: null,
      process: null,
      project: null,
      task: null,
    },
  };
}

const vocabulary = [tag("familj", 3), tag("viktig", 5), tag("styrelse", 0)];

afterEach(() => vi.restoreAllMocks());

describe("TagChips", () => {
  it("draws two tags and +N, and reads them once as one sentence", () => {
    const { container } = render(
      <TagChips
        tags={["viktig", "familj", "styrelse"]}
        max={2}
        locale="sv-SE"
      />,
    );
    expect(container.textContent).toContain(
      `${tagSv.tags}: viktig, familj och 1 till`,
    );
    const drawn = container.querySelectorAll('.sk-tag[aria-hidden="true"]');
    expect([...drawn].map((pill) => pill.textContent)).toEqual([
      "viktig",
      "familj",
      "+1",
    ]);
  });

  it("reads English with its own list words and draws nothing without tags", () => {
    const { container, rerender } = render(
      <TagChips tags={["a", "b", "c", "d"]} max={2} locale="en-GB" />,
    );
    expect(container.textContent).toContain(`${tagEn.tags}: a, b and 2 more`);
    rerender(<TagChips tags={[]} locale="en-GB" />);
    expect(container.textContent).toBe("");
  });
});

describe("TagField", () => {
  it("adds a typed tag with Enter as the whole new set, and keeps the text until it is stored", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <TagField
        tags={["viktig"]}
        editable
        busy={false}
        name="Anna"
        onChange={onChange}
        locale="en-GB"
      />,
    );
    await user.click(
      screen.getByRole("button", { name: tagEn.editFor("Anna") }),
    );
    const field = screen.getByRole("textbox", { name: tagEn.input });
    expect(field).toHaveFocus();
    await user.type(field, "Bokklubb Vänner{Enter}");
    expect(onChange).toHaveBeenCalledWith(
      ["viktig", "bokklubb-vänner"],
      expect.any(Function),
    );
    expect(field).toHaveValue("Bokklubb Vänner");
    const [, done] = onChange.mock.calls[0] as [string[], () => void];
    done();
    await waitFor(() => expect(field).toHaveValue(""));
  });

  it("lists the suggestions most used first, equal use in the locale's collation (Swedish: viktig before vänta)", async () => {
    const user = userEvent.setup();
    const suggestions = ["vänta", "kund", "viktig", "åska"].map((label) => ({
      slug: label,
      label,
      count: 2,
    }));
    render(
      <TagField
        tags={[]}
        suggestions={suggestions}
        editable
        busy={false}
        name="Anna"
        onChange={vi.fn()}
        locale="sv-SE"
      />,
    );
    await user.click(screen.getByRole("button", { name: tagSv.add }));
    const list = screen.getByRole("list", { name: tagSv.suggested });
    expect(
      within(list)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["kund", "viktig", "vänta", "åska"]);
  });

  it("removes a tag, adds a suggestion with one tap and closes with Escape", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <TagField
        tags={["viktig", "familj"]}
        suggestions={[
          { slug: "familj", label: "familj", count: 3 },
          { slug: "styrelse", label: "styrelse", count: 0 },
        ]}
        editable
        busy={false}
        name="Anna"
        onChange={onChange}
        locale="sv-SE"
      />,
    );
    await user.click(
      screen.getByRole("button", { name: tagSv.editFor("Anna") }),
    );
    await user.click(
      screen.getByRole("button", { name: tagSv.remove("viktig") }),
    );
    expect(onChange).toHaveBeenLastCalledWith(["familj"], expect.any(Function));
    // A tag already on the record is not offered again.
    expect(
      screen.queryByRole("button", { name: tagSv.suggest("familj") }),
    ).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: tagSv.suggest("styrelse") }),
    );
    expect(onChange).toHaveBeenLastCalledWith(
      ["viktig", "familj", "styrelse"],
      expect.any(Function),
    );
    await user.keyboard("{Escape}");
    expect(
      screen.getByRole("button", { name: tagSv.editFor("Anna") }),
    ).toHaveFocus();
  });

  it("refuses a tag over 60 characters and an eleventh tag, and shows pills only when not editable", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const { rerender } = render(
      <TagField
        tags={[]}
        editable
        busy={false}
        name="Anna"
        onChange={onChange}
        locale="en-GB"
      />,
    );
    await user.click(screen.getByRole("button", { name: tagEn.add }));
    await user.type(
      screen.getByRole("textbox", { name: tagEn.input }),
      `${"x".repeat(61)}{Enter}`,
    );
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(tagEn.tooLong(60));

    const ten = Array.from({ length: 10 }, (_, n) => `t${n}`);
    rerender(
      <TagField
        tags={ten}
        editable
        busy={false}
        name="Anna"
        onChange={onChange}
        locale="en-GB"
      />,
    );
    expect(screen.getByRole("textbox", { name: tagEn.input })).toBeDisabled();
    expect(screen.getByRole("alert")).toHaveTextContent(tagEn.full(10));

    rerender(
      <TagField
        tags={["viktig"]}
        editable={false}
        busy={false}
        name="Anna"
        onChange={onChange}
        locale="en-GB"
      />,
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(screen.getByText(`${tagEn.tags}: viktig`)).toBeInTheDocument();
  });
});

describe("TagFilter", () => {
  it("toggles tags, clears them, allows five at once and draws nothing without tags", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    const options = ["a", "b", "c", "d", "e", "f"].map((slug) => ({
      slug,
      label: slug,
      count: 1,
    }));
    const { rerender, container } = render(
      <TagFilter
        options={options}
        selected={["a"]}
        onChange={onChange}
        locale="en-GB"
      />,
    );
    const group = screen.getByRole("group", { name: tagEn.filter });
    expect(within(group).getByRole("button", { name: "a" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(within(group).getByRole("button", { name: "b" }));
    expect(onChange).toHaveBeenLastCalledWith(["a", "b"]);
    await user.click(within(group).getByRole("button", { name: "a" }));
    expect(onChange).toHaveBeenLastCalledWith([]);
    await user.click(
      within(group).getByRole("button", { name: tagEn.clear(1) }),
    );
    expect(onChange).toHaveBeenLastCalledWith([]);

    rerender(
      <TagFilter
        options={options}
        selected={["a", "b", "c", "d", "e"]}
        onChange={onChange}
        locale="en-GB"
      />,
    );
    expect(screen.getByRole("button", { name: "f" })).toBeDisabled();

    rerender(
      <TagFilter
        options={[]}
        selected={[]}
        onChange={onChange}
        locale="en-GB"
      />,
    );
    expect(container.textContent).toBe("");
  });

  it("names the chips, counts the chosen tags on Clear and sorts Swedish tags with å, ä, ö last", () => {
    const options = ["vänta", "viktig", "åska", "kund", "zebra"].map(
      (label) => ({ slug: label, label, count: 1 }),
    );
    const { rerender } = render(
      <TagFilter
        options={options}
        selected={["kund", "viktig"]}
        onChange={vi.fn()}
        locale="sv-SE"
      />,
    );
    const group = screen.getByRole("group", { name: tagSv.filter });
    expect(within(group).getByText(tagSv.tags)).toBeVisible();
    expect(
      within(group)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["kund", "viktig", "vänta", "zebra", "åska", "Rensa (2)"]);
    rerender(
      <TagFilter
        options={options}
        selected={["kund"]}
        onChange={vi.fn()}
        locale="en-GB"
      />,
    );
    expect(
      screen.getByRole("button", { name: tagEn.clear(1) }),
    ).toHaveTextContent("Clear (1)");
    expect(screen.getByText(tagEn.tags)).toBeVisible();
  });
  it("puts the chosen chips first, keeps the focus on a chip that moved and puts the order back when the tags are cleared", async () => {
    const user = userEvent.setup();
    const options = ["a", "b", "c", "d"].map((slug) => ({
      slug,
      label: slug,
      count: 1,
    }));
    function Filter() {
      const [selected, setSelected] = useState<string[]>([]);
      return (
        <TagFilter
          options={options}
          selected={selected}
          onChange={setSelected}
          locale="en-GB"
        />
      );
    }
    render(<Filter />);
    const group = screen.getByRole("group", { name: tagEn.filter });
    const names = () =>
      within(group)
        .getAllByRole("button")
        .map((button) => button.textContent);
    await user.click(within(group).getByRole("button", { name: "c" }));
    expect(names()).toEqual(["c", "a", "b", "d", tagEn.clear(1)]);
    // Moving the chip did not drop the keyboard focus.
    expect(within(group).getByRole("button", { name: "c" })).toHaveFocus();
    await user.click(within(group).getByRole("button", { name: "d" }));
    expect(names()).toEqual(["c", "d", "a", "b", tagEn.clear(2)]);
    await user.click(
      within(group).getByRole("button", { name: tagEn.clear(2) }),
    );
    expect(names()).toEqual(["a", "b", "c", "d"]);
  });
});

describe("Contacts: tags in the list and the room", () => {
  const tagged: WorkContactSummary = {
    id: anna.id,
    display_name: anna.display_name,
    archived: false,
    relationship: "Kollega",
    tags: ["viktig", "familj", "styrelse"],
  };

  it("filters the list by tag (every tag must match) and shows two tags and +N on the row", async () => {
    const user = userEvent.setup();
    const listContacts = vi.fn().mockResolvedValue({
      items: [tagged],
      next_cursor: null,
    });
    const listTags = vi.fn().mockResolvedValue(vocabulary);
    const work = transport({ listContacts, listTags });
    render(
      <WorkView
        transport={work}
        initial={rootFromToolResult({ contacts: [tagged], next_cursor: null })}
        labels={workSv}
      />,
    );
    const row = await screen.findByRole("button", {
      name: new RegExp(`^${anna.display_name}`),
    });
    expect(row).toHaveTextContent(`${tagSv.tags}: viktig, familj och 1 till`);
    const group = await screen.findByRole("group", { name: tagSv.filter });
    // In use on Contacts only, most used first; "styrelse" marks none.
    expect(
      within(group)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["viktig", "familj"]);
    await user.click(within(group).getByRole("button", { name: "familj" }));
    await user.click(within(group).getByRole("button", { name: "viktig" }));
    await waitFor(() =>
      expect(listContacts).toHaveBeenLastCalledWith({
        q: "",
        includeArchived: false,
        tags: ["familj", "viktig"],
      }),
    );
    expect(listTags).toHaveBeenCalledTimes(1);
  });

  it("reads no vocabulary and draws no filter when the host has no list_tags", async () => {
    const listTags = vi.fn().mockResolvedValue(vocabulary);
    const work = transport({
      listTags,
      supportsTool: (name: string) => name !== "list_tags",
    });
    render(
      <WorkView
        transport={work}
        initial={rootFromToolResult({ contacts: [tagged], next_cursor: null })}
        labels={workEn}
      />,
    );
    await screen.findByRole("button", {
      name: new RegExp(`^${anna.display_name}`),
    });
    expect(listTags).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("group", { name: tagEn.filter }),
    ).not.toBeInTheDocument();
  });

  it("adds a tag in the Contact's room with one update_contact of the whole set", async () => {
    const user = userEvent.setup();
    const withTags = { ...anna, tags: ["viktig"] };
    const updateContact = vi.fn().mockResolvedValue({
      contact: { ...withTags, tags: ["viktig", "familj"], version: 2 },
    });
    const work = transport({
      getContactContext: vi.fn().mockResolvedValue({
        contact: withTags,
        projects: { items: [], next_cursor: null },
        tasks: { items: [], next_cursor: null },
      }),
      listTags: vi.fn().mockResolvedValue(vocabulary),
      updateContact,
    });
    render(contactRoot(work));
    await user.click(
      await screen.findByRole("button", {
        name: tagEn.editFor(anna.display_name),
      }),
    );
    await user.click(
      await screen.findByRole("button", { name: tagEn.suggest("familj") }),
    );
    expect(updateContact).toHaveBeenCalledWith(
      anna.id,
      1,
      { tags: ["viktig", "familj"] },
      expect.stringMatching(KEY),
    );
    expect(
      await screen.findByRole("button", { name: tagEn.remove("familj") }),
    ).toBeInTheDocument();
  });

  it("shows an archived Contact's tags without a way to change them", async () => {
    const work = transport({
      getContactContext: vi.fn().mockResolvedValue({
        contact: { ...anna, archived: true, tags: ["viktig"] },
        projects: { items: [], next_cursor: null },
        tasks: { items: [], next_cursor: null },
      }),
    });
    render(contactRoot(work));
    expect(
      await screen.findByText(`${tagEn.tags}: viktig`),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: tagEn.editFor(anna.display_name) }),
    ).not.toBeInTheDocument();
  });
});
