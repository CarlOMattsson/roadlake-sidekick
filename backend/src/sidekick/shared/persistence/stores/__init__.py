"""Store pieces every context shares: `StoreBase`, keyset paging, task parents and work tags.

Each context's store lives in `<context>/persistence` and is built on `StoreBase`;
`sidekick.composition` wires the stores to each other.
"""
