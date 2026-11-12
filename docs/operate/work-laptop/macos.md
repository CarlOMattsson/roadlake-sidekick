# macOS

[Svenska](macos.sv.md)

<!-- description: The work package is written for macOS with Docker Desktop but has never been run there. This page lists what differs from Linux. -->

The work package is written for macOS with Docker Desktop but has never been run there. This page lists what differs from Linux.

Docker Desktop provides the internal networks and the published port, so the closed network should work the same way
(there is no host firewall involved). The gateway trusts the macOS keychain certificates for an https model server
(exported to `deploy/work/generated/ca-bundle.pem`). None of this has been run on a Mac: the macOS paths (the launchd
agent, the keychain export, the Claude Desktop configuration folder and the `docker exec` entry, which only assumes that
`docker` exists at an absolute path) were written from the documentation. Treat macOS as untested.
