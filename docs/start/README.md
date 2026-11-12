# Choose your path

[Svenska](README.sv.md)

<!-- description: Four ways to start with Sidekick – your own server, a work laptop, your first day, or development – and what each one needs. -->

There are four ways to start. Choose by where Sidekick will run and what you want to do.

:::note[First release]
Sidekick 0.1.0 is the first version. It is in daily use with Claude, with the Android app on a real phone and on Linux. macOS has not been tried yet.
:::

## What you need for your own server

- **A Claude plan that supports custom connectors.** A connector is the link that lets Claude use the tools on your server.
- **A public HTTPS address for the server.** It can be a domain or a tunnel. Claude reaches the server from Anthropic's cloud, so an address that only exists on your home network is not enough.
- **A GitHub account.** It is used to sign in.
- **Linux x86_64 with Docker and Docker Compose.**

These requirements apply only to the server path. The simplest way to start is the work laptop path: everything runs locally in Docker and you use it from Claude Desktop, with no public address, domain, TLS or GitHub account. The developer path is local too.

## Four paths

### Your own server

For you who want to self-host, meaning run Sidekick on a machine you control: a VPS or an always-on home computer. You need everything in the list above. This is the path if you want to use Sidekick from Claude on several devices and pair the Android app.

[Go to First start on a server](self-hosted-server.md)

### Work laptop

For you who want to use Sidekick at work without a public address. The work package runs Sidekick in Docker on your laptop and talks to Claude Desktop locally. The memory is optional and off by default; if you turn it on, the containers reach only your company's model server. What Claude Desktop reads is shared with Claude. You need Ubuntu with Docker and Claude Desktop, and the address of your company's own model server only if you want the memory. This package has no route to a phone.

[Go to Sidekick on a work laptop](work-laptop.md)

### Your first day

For you who already have a server running and Claude connected. The guide takes you through all four rooms in one conversation.

[Go to Your first day with Sidekick](first-day.md)

### Develop and contribute

For you who want to run Sidekick locally, read the code or propose a change. You need your own computer with Python 3.13 and `uv`, Node.js 22 and Docker. Claude Desktop can start Sidekick locally, with no public address.

[Go to Run Sidekick locally as a developer](first-contribution.md)

## Once you are running

The user guide describes the rooms one at a time. The operations guides cover updates, backups and the Android app.

- [Read the user guide](../guide/README.md)
- [Read the operations overview](../operate/README.md)
- [Read who sees what](../explanation/security-and-privacy.md)
