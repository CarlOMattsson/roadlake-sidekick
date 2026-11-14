"""``--local-images``: two api images built from this checkout, behind a throw-away registry, so that they have real
digests (``update.sh`` pulls by digest). The registry image is pinned by digest like every other image of the
repository.

The signature step of ``update.sh`` needs a cosign that answers; a locally built image has no signature to verify. The
stand-in only checks the shape of the call (verify, a local drill image, the drill identity and an issuer). The real
signature check is the drill with released images.
"""

from __future__ import annotations

import re
from pathlib import Path

from . import drillpolicy
from .drillsteps import Run, Step, StepFailed

REGISTRY_IMAGE = "registry:2@sha256:a3d8aaa63ed8681a604f1dea0aa03f100d5895b6a58ace528858a7b332415373"
REGISTRY_WAIT_SECONDS = 30
COSIGN_STANDIN = """#!/usr/bin/env bash
[ "${1:-}" = verify ] || exit 1
[[ "${2:-}" =~ ^127\\.0\\.0\\.1:[0-9]+/sidekick@sha256:[0-9a-f]{64}$ ]] || exit 1
shift 2
[ "${1:-}" = --certificate-identity ] && [ "${2:-}" = "IDENTITY" ] || exit 1
[ "${3:-}" = --certificate-oidc-issuer ] && [ -n "${4:-}" ]
"""


def cosign_standin(identity: str) -> str:
    return COSIGN_STANDIN.replace("IDENTITY", identity)


def registry_compose(port: int) -> str:
    return f'services:\n  registry:\n    image: {REGISTRY_IMAGE}\n    ports:\n      - "127.0.0.1:{port}:5000"\n'


def newest_migration(migrations: Path) -> str:
    """The name (without ``.py``) of the newest migration: the schema head the release workflow gives the image."""
    names = sorted(path.name for path in migrations.glob("[0-9]*.py"))
    return names[-1].removesuffix(".py") if names else ""


def build_images(step: Step, shared: Run, *, project: str, address: str, refs: list[str]) -> None:
    """Start the registry at ``address`` (``127.0.0.1:PORT``), build and push both images and record their digests in
    ``shared.kv`` (``from_image``, ``to_image``). Every reference that is made is added to ``refs`` before it exists, so
    that the cleanup removes it."""
    port = int(address.rsplit(":", 1)[1])
    registry = shared.tmp / "registry"
    registry.mkdir(parents=True, exist_ok=True)
    (registry / "compose.yaml").write_text(registry_compose(port), encoding="utf-8")
    compose = ["docker", "compose", "-p", project, "-f", str(registry / "compose.yaml")]
    step.sh([*compose, "up", "-d", "--wait", "--wait-timeout", "120"])
    for _ in range(REGISTRY_WAIT_SECONDS):
        if shared.host.port_open(port):
            break
        shared.host.sleep(1)
    # The release workflow's inputs, from the same files: the version of the source, the newest migration and the
    # stepping stone.
    version, following = drillpolicy.release_versions(shared.repo / "backend" / "pyproject.toml")
    head = newest_migration(shared.repo / "migrations")
    minimum = "".join(
        (shared.repo / "deploy" / "selfhost" / "min-upgrade-from.txt").read_text(encoding="utf-8").split()
    )
    if not head or not minimum:
        raise StepFailed("no migration or min-upgrade-from found")
    for role, built in (("from", version), ("to", following)):
        tag = f"{address}/sidekick:{role}"
        refs.append(tag)  # removed again by the cleanup
        build = ["docker", "build", "-q", "-f", str(shared.repo / "backend" / "Dockerfile"), "-t", tag]
        args = {
            "SIDEKICK_MIGRATION_CLASS": "expand",
            "SIDEKICK_SCHEMA_HEAD": head,
            "SIDEKICK_MIN_UPGRADE_FROM": minimum,
        }
        for name, value in args.items():
            build += ["--build-arg", f"{name}={value}"]
        step.read_bytes([*build, "--label", f"org.opencontainers.image.version={built}", str(shared.repo)])
        pushed = step.call(["docker", "push", tag], merge=True)
        text = pushed.out.decode("utf-8", errors="replace")
        digest = drillpolicy.pushed_digest(text) if pushed.rc == 0 else None
        if digest is None:
            step.note(text)
            raise StepFailed(f"no digest from the push of {tag}")
        reference = f"{address}/sidekick@{digest}"
        refs.append(reference)
        shared.kv[f"{role}_image"] = reference
        step.note(f"built {tag} as version {built}: {reference}")
    if shared.kv["from_image"] == shared.kv["to_image"]:
        raise StepFailed("both builds have the same digest")


def is_local_reference(reference: str) -> bool:
    """A reference of an image ``--local-images`` built: the throw-away registry on 127.0.0.1, repository sidekick."""
    return re.fullmatch(r"127\.0\.0\.1:[0-9]+/sidekick[:@][A-Za-z0-9:._-]+", reference) is not None
