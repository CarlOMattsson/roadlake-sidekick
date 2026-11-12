# Frequently asked questions

[Svenska](faq.sv.md)

<!-- description: Short answers about what Sidekick is, what Claude sees, license and price, operations and the Android app, with links to the page that explains more. -->

Short answers to what people usually wonder before they install. Each answer links to the page that explains more.

## The product

### What is Sidekick?

Sidekick is a personal assistant that you run on your own server. You manage tasks, a journal, contacts and shopping by talking to Claude, and the rooms open in the conversation when you want to tap things yourself. [Read how the conversation and the rooms fit together](guide/README.md).

### Do I need Claude?

Yes. Sidekick has no web interface of its own. Claude is the interface, and the Android app is a second surface for work, the journal and shopping. [Read what the Android app does](guide/android-app.md).

### Which Claude plan do I need?

A plan that supports custom connectors, meaning links to your own servers. On Team and Enterprise, an organisation owner adds the connector first. [Read how to connect Claude](operate/connect-claude.md).

### Is Sidekick finished?

No. Version 0.1.0 is the first version and is not released yet. From the first release on, every release has a signed container image and a signed Android APK; until then you build both from the source code. It is in daily use with Claude, with the Android app on a real phone and on Linux; macOS has not been tried yet. [See what has been tried](maintainers/release.md).

### Why are the rooms in Swedish?

Swedish is the default. Set `SIDEKICK_MCP_APP_LOCALE=en` on the server for English labels. [Read more about languages](reference/languages.md).

## Data and privacy

### Where is my data?

In PostgreSQL on your own server. Sidekick sends no telemetry and has no central service. [Read who sees what](explanation/security-and-privacy.md).

### Does Claude read my journal?

Only if you give the connector the `journal:read` permission. Claude can then read the entries, including the text itself, and what Claude reads is shared with Claude. The example configuration gives no access to the journal. [Read what Claude sees](explanation/security-and-privacy.md#what-claude-sees).

### Is my data sent to an AI provider?

Sidekick calls no language model on its own. Claude sees what its permissions allow. If you turn memory on, text is sent to the model provider you configured yourself. [Read about memory](guide/control-and-memory.md).

### Can I delete something for good?

Not from Claude or the rooms, where everything goes to the trash and can be restored. Whoever runs the server empties the trash with a command. Journal entries and shopping items cannot be deleted for good at all. [Read how to empty the trash](operate/empty-trash.md).

## License and price

### What does Sidekick cost?

Nothing. Every feature is there without a license key. An optional key removes the reminder that this is the free version, and its prices are listed. [See the pricing table](explanation/licensing.md#prices).

### What happens when the key expires?

The reminder comes back. Nothing else changes: your data and every feature stay as they were. [Read what the key does](explanation/licensing.md).

### How do I get the key after buying?

The key is sent by email once the payment is complete. Payment happens in Polar's checkout. Keys are not on sale yet. [Read how buying works](explanation/licensing.md#how-to-buy).

### Is it open source?

No. Sidekick is source available: you can read and change the code, but the license limits distribution and sale. The license text governs, and the summary is not the license. [Read the license in plain words](explanation/licensing.md).

### May a consultant install it for me?

Yes. A consultant or agency may install, adapt and maintain Sidekick on your own installation and charge for the work. They may not charge for the software, for keys or for access, and they may not offer Sidekick as a hosted service. [Read what the license allows](explanation/licensing.md).

## Operations

### Can I run it without a public address?

Yes, in two ways: the work package runs Sidekick on a laptop against Claude Desktop locally. As a developer you can also let Claude Desktop start Sidekick on your own computer. Claude on the web and on a phone needs a public HTTPS address. [Choose your path](start/README.md).

### How do I update?

Take a backup first. Then update either from source or to a signed image with `update.sh`, which only prints the plan until you add `--apply`. No image is published yet, so for now the source route applies. [Read how to update](operate/update.md).

### How do I move my data?

Take a backup in the old installation, start the new one from an empty database and import the backup with the same key. Phones, sign-ins and the license key do not come along and have to be set up again. [Read how to move data](operate/move-data.md).

## Android

### Is there an iOS app?

No. There is an Android app. From the first release on you download a signed APK from the release on GitHub, and you can also build it yourself from the source code. [Read about the Android app](guide/android-app.md).

### Does the app need Google services?

No. Reminders travel through UnifiedPush and the ntfy app, with no Firebase. [Read about the widget and reminders](guide/today-widget.md).

### Can I create tasks in the app?

Not in the Android app. There you read and check off work, write and edit journal entries by hand, and create shopping lists and add items. You create tasks in Claude, by asking or with + in the Work room; projects you create by asking Claude. [Read what the app does and does not do](guide/android-app.md).
