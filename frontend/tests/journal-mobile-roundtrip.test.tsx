import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { journalSv } from "@/features/journal-app/labels";
import { CompanionRoomTransport } from "@/mobile/companion-transport";
import { MobileApp } from "@/mobile/mobile-app";
import type { MobilePlatform } from "@/mobile/platform";
import type { NativeRequest } from "@/mobile/sidekick-native";
import { fakeNative, ok } from "./helpers/fake-native";
import {
  phoneJournalServer,
  type PhoneJournalServer,
} from "./helpers/phone-journal-server";

const TITLE = "Promenad på Södermalm";
const TEXT =
  "Gick längs vattnet och funderade på nästa vecka.\nÅ, vilken kväll!";

const platform: MobilePlatform = {
  onBack: () => () => undefined,
  launchSearch: () => "",
  onLaunchSearch: () => () => undefined,
  onResume: () => () => undefined,
  safeAreaInsets: () => undefined,
};

/** One start of the app: a new transport and a new native plugin over the same server, as after a restart. */
function startApp(server: PhoneJournalServer) {
  const native = fakeNative((request: NativeRequest) =>
    request.path === "/companion/v1/work/agenda"
      ? ok({ items: [], filters: {}, next_cursor: null })
      : server.request(request),
  );
  // The plugin refuses what the phone would refuse; its refusal reaches the transport as "no answer came".
  native.request.mockImplementation((request: NativeRequest) =>
    request.path === "/companion/v1/work/agenda"
      ? Promise.resolve(ok({ items: [], filters: {}, next_cursor: null }))
      : server.request(request),
  );
  return render(
    <MobileApp
      transport={new CompanionRoomTransport(native)}
      platform={platform}
      locale="sv"
    />,
  );
}

async function openDagbok(user: ReturnType<typeof userEvent.setup>) {
  await user.click(await screen.findByRole("button", { name: "Dagbok" }));
}

afterEach(cleanup);

describe("a hand-written journal entry on the phone", () => {
  it("is written, saved, opened again after a restart and its text read back", async () => {
    const user = userEvent.setup();
    const server = phoneJournalServer();
    startApp(server);

    // Write.
    await openDagbok(user);
    await user.click(
      await screen.findByRole("button", { name: journalSv.addEntry }),
    );
    await user.type(screen.getByLabelText(journalSv.titleLabel), TITLE);
    await user.type(
      screen.getByLabelText(journalSv.entryTextLabel),
      TEXT.replaceAll("\n", "{Enter}"),
    );
    await user.click(screen.getByRole("button", { name: journalSv.saveEntry }));

    // Save: the server holds the words in the source; the entry itself has no summary.
    const row = await screen.findByRole("button", {
      name: new RegExp(TITLE),
    });
    expect(server.entries()).toHaveLength(1);
    expect(server.entries()[0]?.entry.summary).toBeNull();
    expect(server.entries()[0]?.text).toBe(TEXT);

    // Read back at once ...
    await user.click(row);
    await user.click(
      await screen.findByRole("button", { name: journalSv.showOriginal }),
    );
    const original = await screen.findByRole("article");
    expect(
      within(original).getByRole("heading", {
        name: journalSv.originalHeading,
      }),
    ).toBeInTheDocument();
    expect(original.textContent).toContain("Gick längs vattnet");
    expect(original.textContent).toContain("Å, vilken kväll!");

    // ... and after a restart: a new app, a new transport, the same server.
    cleanup();
    startApp(server);
    await openDagbok(user);
    await user.click(
      await screen.findByRole("button", { name: new RegExp(TITLE) }),
    );
    await user.click(
      await screen.findByRole("button", { name: journalSv.showOriginal }),
    );
    expect((await screen.findByRole("article")).textContent).toContain(
      "Gick längs vattnet och funderade på nästa vecka.",
    );
    // Only the journal's own routes were asked; the text came from the source route, with a UUID in its path.
    const paths = server.served.map((r) => r.path);
    expect(paths.filter((p) => p.includes("/journal/sources/"))).toHaveLength(
      2,
    );
    expect(paths.every((p) => p.startsWith("/companion/v1/"))).toBe(true);
  });
});
