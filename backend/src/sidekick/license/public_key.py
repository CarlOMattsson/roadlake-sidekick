"""The licensor's license public key (D-081): the one value that decides which keys are valid.

`DEFAULT_LICENSE_PUBLIC_KEY` below holds the licensor's public key (base64 of a raw 32-byte
Ed25519 key, on one line), so a build from this repository verifies the keys the licensor issues.
Making the key pair and issuing license keys is the licensor's own private process and its tooling
is not part of this repository. A public key is not a secret. `SIDEKICK_LICENSE_PUBLIC_KEY` on an
instance takes precedence over this default. Were the default ever the placeholder, no key would
verify and every license key would be "unlicensed".

The release image workflow refuses to build while the default is the placeholder
(tools/check-license-public-key.py).
"""

from typing import Final

# Not valid base64 of a 32-byte key on purpose: it can never verify anything.
PLACEHOLDER_PUBLIC_KEY: Final = "UNSET-OWNER-PUBLIC-KEY"

# The base64 raw Ed25519 public key; keep it on one line.
DEFAULT_LICENSE_PUBLIC_KEY: Final = "Yj6Q+9OWZHksPqi1LD2BMt4bhrd+DVGoOy11Gc+xRyE="
