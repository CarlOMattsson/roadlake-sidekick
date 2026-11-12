#!/usr/bin/env python3
"""Generate and check THIRD_PARTY_NOTICES.md: the third-party components that ship with Sidekick.

    python3 tools/third_party_notices.py --write [--venv backend/.venv]   regenerate THIRD_PARTY_NOTICES.md and the
                                                                          Android license asset
    python3 tools/third_party_notices.py --check                          fail when either file lags the lock files

Sources, all offline:
  * Python runtime dependencies: the closure of [project].dependencies in backend/uv.lock (dev group excluded);
    licenses and authors come from the installed package metadata (importlib.metadata) in a backend venv.
  * npm runtime dependencies: frontend/package-lock.json packages that are not dev-only (the `license` field there).
  * Android: the releaseRuntimeClasspath entries of frontend/android/gradle/locks/*.lockfile. Gradle cannot be
    queried offline, so the licenses come from the table GRADLE_LICENSES below, checked by hand against each
    artifact's published POM and marked as such in the output.
  * Container images: CONTAINERS below. --check also fails when a deploy file or Dockerfile uses an image that
    is not listed.
  * The Android license asset (frontend/android/app/src/main/assets/licenses/third-party-licenses.txt): the npm and
    Gradle runtime components with their notices and the full texts of the licenses they use (Apache-2.0 from
    licenses/Apache-2.0.txt, the short ones below). --check fails when it lags the lock files, and when a runtime
    npm package has no copyright line in NPM_NOTICES.

--check needs no venv and no network: it compares package names and versions in the file with the lock files.
Licenses that may need action (GPL, AGPL, LGPL, MPL, unknown) are collected in a "Needs attention" section.
"""

from __future__ import annotations

import argparse
import importlib.metadata as md
from email.header import decode_header, make_header
import json
import re
import sys
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
OUTPUT = REPO / "THIRD_PARTY_NOTICES.md"
LICENSE_TEXTS = REPO / "licenses"
ANDROID_LICENSES = (
    REPO
    / "frontend"
    / "android"
    / "app"
    / "src"
    / "main"
    / "assets"
    / "licenses"
    / "third-party-licenses.txt"
)
# Files the API image copies to /usr/share/doc/sidekick (backend/Dockerfile); --check fails when one is missing.
IMAGE_LICENSE_FILES = [
    REPO / "LICENSE.md",
    REPO / "licenses" / "SOURCES.md",
    REPO / "licenses" / "GPL-3.0.txt",
    REPO / "licenses" / "LGPL-3.0.txt",
    REPO / "licenses" / "LGPL-2.1.txt",
    REPO / "licenses" / "Apache-2.0.txt",
]
UV_LOCK = REPO / "backend" / "uv.lock"
NPM_LOCK = REPO / "frontend" / "package-lock.json"
GRADLE_LOCKS = REPO / "frontend" / "android" / "gradle" / "locks"
DEPLOY_FILES = [
    *sorted((REPO / "deploy" / "selfhost").glob("compose*.yaml")),
    *sorted((REPO / "deploy" / "work").glob("compose*.yaml")),
    REPO / "deploy" / "compose.test.yaml",
    REPO / "deploy" / "compose.dev.yaml",
    REPO / "backend" / "Dockerfile",
]
MARKER = "<!-- section:{} -->"
REVIEW_PATTERN = re.compile(
    r"GPL|AGPL|LGPL|MPL|EUPL|CDDL|EPL|SSPL|UNKNOWN|UNLICENSED|SEE LICENSE", re.I
)

# Why a flagged license is acceptable (or what to watch). A flag without a note here is printed as "unreviewed".
FLAG_NOTES = {
    "psycopg": "LGPL-3.0: used unmodified as a dynamically imported library; replacing it stays possible.",
    "psycopg-binary": "LGPL-3.0: unmodified wheel loaded by psycopg; replacing it stays possible.",
    "certifi": "MPL-2.0: unmodified CA bundle file; MPL obligations apply only to changes to that file.",
    "python": "Debian base of the API image we publish: contains GPL/LGPL packages, unmodified; licenses/SOURCES.md says where the source is.",
    "binwiederhier/ntfy": "Dual-licensed Apache-2.0 OR GPL-2.0: run as an unmodified separate container; take Apache-2.0.",
    "haproxy": "GPL-2.0 (core) with LGPL-2.1 parts: run as an unmodified separate container, not linked.",
    "postgres": "Alpine base contains GPL components (busybox): unmodified image pulled by the operator, not distributed by us.",
}

MATERIAL_ICON_NOTICE = (
    'The "refresh" glyph of the Material Design icons (`ic_widget_refresh.xml` in the Android app), Copyright Google LLC,'
    " Apache-2.0, https://github.com/google/material-design-icons."
)

# group:name prefix -> (license, source). Longest matching prefix wins. Checked by hand 2026-11-11 against the POMs.
GRADLE_LICENSES = [
    ("androidx.", "Apache-2.0", "https://developer.android.com/jetpack/androidx"),
    # Glance's repackaged protobuf runtime keeps protobuf's license (its POM and META-INF/LICENSE.txt say BSD-3).
    (
        "androidx.glance:glance-appwidget-external-protobuf",
        "BSD-3-Clause",
        "https://github.com/protocolbuffers/protobuf",
    ),
    ("org.jetbrains.kotlin:", "Apache-2.0", "https://kotlinlang.org"),
    (
        "org.jetbrains.kotlinx:",
        "Apache-2.0",
        "https://github.com/Kotlin/kotlinx.coroutines",
    ),
    (
        "org.jetbrains:annotations",
        "Apache-2.0",
        "https://github.com/JetBrains/java-annotations",
    ),
    ("org.jspecify:", "Apache-2.0", "https://jspecify.dev"),
    ("org.apache.cordova:", "Apache-2.0", "https://cordova.apache.org"),
    (
        "org.unifiedpush.android:",
        "Apache-2.0",
        "https://github.com/UnifiedPush/android-connector",
    ),
    (
        "com.google.code.findbugs:jsr305",
        "Apache-2.0",
        "https://code.google.com/archive/p/jsr-305/",
    ),
    ("com.google.code.gson:", "Apache-2.0", "https://github.com/google/gson"),
    (
        "com.google.crypto.tink:",
        "Apache-2.0",
        "https://github.com/tink-crypto/tink-java",
    ),
    ("com.google.errorprone:", "Apache-2.0", "https://github.com/google/error-prone"),
    (
        "com.google.guava:listenablefuture",
        "Apache-2.0",
        "https://github.com/google/guava",
    ),
    (
        "com.google.protobuf:",
        "BSD-3-Clause",
        "https://github.com/protocolbuffers/protobuf",
    ),
]

# name -> (tag as used, license, source, role). The tag is informative; --check only compares the image names.
CONTAINERS = {
    "python": (
        "3.13-slim",
        "PSF-2.0 (CPython); the Debian base carries GPL/LGPL packages",
        "https://hub.docker.com/_/python",
        "API image base",
    ),
    "postgres": (
        "18-alpine",
        "PostgreSQL; the Alpine base carries GPL components (busybox)",
        "https://hub.docker.com/_/postgres",
        "database",
    ),
    "binwiederhier/ntfy": (
        "v2",
        "Apache-2.0 OR GPL-2.0",
        "https://github.com/binwiederhier/ntfy",
        "push distributor",
    ),
    "caddy": (
        "2-alpine",
        "Apache-2.0",
        "https://github.com/caddyserver/caddy",
        "TLS reverse proxy",
    ),
    "ghcr.io/vectorize-io/hindsight": (
        "pinned digest",
        "MIT (per upstream repository; re-check on a digest bump)",
        "https://github.com/vectorize-io/hindsight",
        "memory service",
    ),
    "haproxy": (
        "3.4-alpine",
        "GPL-2.0-or-later (core), LGPL-2.1 (libraries)",
        "https://www.haproxy.org",
        "egress gateway",
    ),
}

# Components that are in no lock file. Rendered at the end of THIRD_PARTY_NOTICES.md.
OTHER_ATTRIBUTIONS = [
    "## Libraries bundled in the psycopg-binary wheel",
    "",
    "The wheel carries its own shared libraries (`psycopg_binary.libs/`): libpq (PostgreSQL license), OpenSSL 3",
    "(Apache-2.0), MIT Kerberos, Cyrus SASL, OpenLDAP, PCRE, libselinux, and libkeyutils and libcrypt",
    "(LGPL-2.1-or-later). The versions are in the wheel's own SBOM; the sources are listed in",
    "[licenses/SOURCES.md](licenses/SOURCES.md).",
    "",
    "## Other attributions",
    "",
    f"- {MATERIAL_ICON_NOTICE}",
    "- CODE_OF_CONDUCT.md is adapted from the Contributor Covenant 2.1 (CC BY 4.0), see the notice in that file.",
]

CONTAINER_SKIP = re.compile(r"roadlake-sidekick|SIDEKICK_")  # our own image


def rel(path: Path) -> str:
    return str(path.relative_to(REPO)) if path.is_relative_to(REPO) else path.name


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def esc(text: str) -> str:
    return " ".join(str(text).split()).replace("|", "\\|")


def python_closure() -> dict[str, str]:
    """name -> version for the Linux runtime closure of the project in uv.lock."""
    lock = tomllib.loads(UV_LOCK.read_text())
    pkgs = {norm(p["name"]): p for p in lock["package"]}
    root = next(
        p for p in lock["package"] if p.get("source", {}).get("editable") == "."
    )
    seen: dict[str, str] = {}
    todo = list(root.get("dependencies", []))
    while todo:
        dep = todo.pop()
        if re.fullmatch(r"sys_platform == '(win32|emscripten)'", dep.get("marker", "")):
            continue  # Windows- and Pyodide-only; the Linux image never installs them
        name = norm(dep["name"])
        pkg = pkgs[name]
        if "extra" in dep:
            for extra in dep["extra"]:
                todo.extend(pkg.get("optional-dependencies", {}).get(extra, []))
        if name in seen:
            continue
        seen[name] = pkg["version"]
        todo.extend(pkg.get("dependencies", []))
    return dict(sorted(seen.items()))


def npm_runtime() -> dict[str, tuple[str, str]]:
    lock = json.loads(NPM_LOCK.read_text())
    out: dict[str, tuple[str, str]] = {}
    for path, meta in lock["packages"].items():
        if not path or meta.get("dev") or meta.get("devOptional"):
            continue
        name = path.split("node_modules/")[-1]
        out[name] = (meta["version"], meta.get("license") or "UNKNOWN")
    return dict(sorted(out.items()))


def gradle_runtime() -> dict[str, str]:
    """group:name -> comma-joined versions, from releaseRuntimeClasspath in the lock files."""
    found: dict[str, set[str]] = {}
    for lockfile in sorted(GRADLE_LOCKS.glob("*.lockfile")):
        for line in lockfile.read_text().splitlines():
            if line.startswith("#") or "=" not in line:
                continue
            coord, configs = line.split("=", 1)
            if "releaseRuntimeClasspath" not in configs.split(","):
                continue
            group, name, version = coord.split(":")
            found.setdefault(f"{group}:{name}", set()).add(version)
    return {k: ", ".join(sorted(v)) for k, v in sorted(found.items())}


def gradle_license(coord: str) -> tuple[str, str] | None:
    best = max(
        (r for r in GRADLE_LICENSES if coord.startswith(r[0])),
        key=lambda r: len(r[0]),
        default=None,
    )
    return (best[1], best[2]) if best else None


def deploy_images() -> set[str]:
    images: set[str] = set()
    for path in DEPLOY_FILES:
        if not path.exists():
            continue
        for line in path.read_text().splitlines():
            match = re.match(r"\s*(?:image:|FROM)\s+(\S+)", line)
            if match and not CONTAINER_SKIP.search(match.group(1)):
                images.add(re.split(r"[:@]", match.group(1))[0])
    return images


def python_metadata(
    venv: Path, wanted: dict[str, str]
) -> list[tuple[str, str, str, str]]:
    sites = sorted(venv.glob("lib/python*/site-packages")) + sorted(
        venv.glob("Lib/site-packages")
    )
    dists = {
        norm(d.metadata["Name"]): d
        for d in md.distributions(path=[str(s) for s in sites])
    }
    rows = []
    for name, version in wanted.items():
        dist = dists.get(name)
        if dist is None:
            raise SystemExit(
                f"{name} is not installed in {venv}; run `uv sync --project backend` first"
            )
        if dist.version != version:
            raise SystemExit(
                f"{name}: venv has {dist.version}, uv.lock has {version}; sync the venv"
            )
        meta = dist.metadata
        lic = (meta.get("License-Expression") or "").strip()
        if not lic:
            raw = (meta.get("License") or "").strip()
            if raw and "\n" not in raw and len(raw) <= 60:
                lic = raw
        if not lic:
            classes = [
                c.split("::")[-1].strip()
                for c in meta.get_all("Classifier") or []
                if c.startswith("License ::")
            ]
            lic = " / ".join(c for c in classes if c != "OSI Approved") or "UNKNOWN"
        author = str(make_header(decode_header(meta.get("Author") or ""))).strip()
        if not author:
            email = meta.get("Author-email") or meta.get("Maintainer-email") or ""
            author = (
                re.sub(
                    r"\s*<[^>]*>",
                    "",
                    str(make_header(decode_header(email.split(",")[0]))),
                )
                .strip()
                .strip('"')
            )
        urls = {
            u.split(",")[0].strip().lower(): u.split(",", 1)[1].strip()
            for u in meta.get_all("Project-URL") or []
        }
        link = meta.get("Home-page") or next(
            (
                urls[k]
                for k in ("homepage", "source", "repository", "source code", "home")
                if k in urls
            ),
            next(iter(urls.values()), f"https://pypi.org/project/{name}/"),
        )
        rows.append((name, version, lic, f"{author or 'see project'} ({link})"))
    return rows


def render(venv: Path) -> str:
    py_rows = python_metadata(venv, python_closure())
    npm = npm_runtime()
    gradle = gradle_runtime()
    flags: list[tuple[str, str, str]] = []

    def flag(kind: str, name: str, lic: str) -> None:
        if REVIEW_PATTERN.search(lic):
            flags.append((kind, name, lic))

    out = [
        "# Third-party notices",
        "",
        "Sidekick itself is licensed under the Roadlake Sidekick Source Available License ([LICENSE.md](LICENSE.md)).",
        "The components below ship with it or run next to it, and keep their own licenses and copyright notices.",
        "The full license text of each component is in its package (`*.dist-info/`, `node_modules/<name>/`) and in",
        "the project linked from the table.",
        "",
        "Third-party components are governed solely by their own licenses. Nothing in LICENSE.md, including Additional",
        "Terms section 2, restricts any right those licenses give you. See [licenses/SOURCES.md](licenses/SOURCES.md)",
        "for source locations and the written offer.",
        "",
        "This file is generated by `python3 tools/third_party_notices.py --write` from the lock files and installed",
        "package metadata; do not edit it by hand. `--check` (part of `tools/check-all.sh`) fails when the lock files",
        "move and this file does not.",
        "",
        "## Python runtime dependencies (backend)",
        "",
        MARKER.format("python"),
        "| Package | Version | License | Author and project |",
        "| --- | --- | --- | --- |",
    ]
    for name, version, lic, who in py_rows:
        out.append(f"| {esc(name)} | {version} | {esc(lic)} | {esc(who)} |")
        flag("python", name, lic)
    out += [
        "",
        "## npm runtime dependencies (MCP app and Android web part)",
        "",
        MARKER.format("npm"),
        "| Package | Version | License | Source |",
        "| --- | --- | --- | --- |",
    ]
    for name, (version, lic) in npm.items():
        out.append(
            f"| {esc(name)} | {version} | {esc(lic)} | https://www.npmjs.com/package/{name} |"
        )
        flag("npm", name, lic)
    out += [
        "",
        "## Android runtime dependencies (Gradle releaseRuntimeClasspath)",
        "",
        "Licenses are checked by hand against each artifact's published POM (Gradle cannot be queried offline).",
        "",
        MARKER.format("gradle"),
        "| Artifact | Version | License (manually checked) | Source |",
        "| --- | --- | --- | --- |",
    ]
    for coord, versions in gradle.items():
        found = gradle_license(coord)
        if found is None:
            raise SystemExit(
                f"no license entry for Gradle artifact {coord}; add it to GRADLE_LICENSES"
            )
        out.append(f"| {coord} | {versions} | {found[0]} | {found[1]} |")
        flag("gradle", coord, found[0])
    out += [
        "",
        "## Container images",
        "",
        "Pulled unmodified by the operator's Docker; they are not distributed by us, with one exception: `python` is the",
        "Debian-based image under the API image we publish on GHCR. That image carries LICENSE.md, this file and",
        "[licenses/](licenses/) (license texts and [SOURCES.md](licenses/SOURCES.md)) under `/usr/share/doc/sidekick/`.",
        "",
        MARKER.format("containers"),
        "| Image | Tag | License | Source | Role |",
        "| --- | --- | --- | --- | --- |",
    ]
    for name, (tag, lic, src, role) in CONTAINERS.items():
        out.append(f"| {name} | {tag} | {esc(lic)} | {src} | {role} |")
        flag("container", name, lic)
    out += [
        "",
        "## Needs attention",
        "",
        "Licenses that can carry obligations (GPL, AGPL, LGPL, MPL, or unknown), with why they are acceptable here.",
        "",
    ]
    if flags:
        out += ["| Kind | Component | License | Note |", "| --- | --- | --- | --- |"]
        for kind, name, lic in flags:
            note = FLAG_NOTES.get(
                name.split(":")[0] if kind == "gradle" else name,
                "UNREVIEWED: decide before release",
            )
            out.append(f"| {kind} | {esc(name)} | {esc(lic)} | {esc(note)} |")
    else:
        out.append("None.")
    out += ["", *OTHER_ATTRIBUTIONS]
    return "\n".join(out) + "\n"


# npm runtime package -> copyright notice (from the package's LICENSE file). A runtime package missing here fails --check:
# the license asset in the Android app must name every notice. preact is only in the MCP App bundle, not in the APK.
NPM_NOTICES = {
    "react": "Copyright (c) Meta Platforms, Inc. and affiliates.",
    "react-dom": "Copyright (c) Meta Platforms, Inc. and affiliates.",
    "scheduler": "Copyright (c) Meta Platforms, Inc. and affiliates.",
    "@capacitor/core": "Copyright (c) 2017-present Drifty Co.",
    "@capacitor/android": "Copyright (c) 2017-present Drifty Co.",
    "@capacitor/app": "Copyright 2020-present Ionic (https://ionic.io)",
    "preact": "Copyright (c) 2015-present Jason Miller",
    "tslib": "Copyright (c) Microsoft Corporation.",
}
NPM_NOT_IN_APK = {"preact"}

KOTLIN_NOTICE = """\
   =========================================================================
   ==  NOTICE file corresponding to the section 4 d of                    ==
   ==  the Apache License, Version 2.0,                                   ==
   ==  in this case for the Kotlin Compiler distribution.                 ==
   =========================================================================

   Kotlin Compiler
   Copyright 2010-2024 JetBrains s.r.o and respective authors and developers
"""

MIT_TEXT = """\
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""

ZERO_BSD_TEXT = """\
Permission to use, copy, modify, and/or distribute this software for any
purpose with or without fee is hereby granted.

THE SOFTWARE IS PROVIDED "AS IS" AND THE AUTHOR DISCLAIMS ALL WARRANTIES WITH
REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY
AND FITNESS. IN NO EVENT SHALL THE AUTHOR BE LIABLE FOR ANY SPECIAL, DIRECT,
INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES WHATSOEVER RESULTING FROM
LOSS OF USE, DATA OR PROFITS, WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR
OTHER TORTIOUS ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR
PERFORMANCE OF THIS SOFTWARE.
"""

# protobuf-java and Glance's repackaged protobuf runtime (androidx.glance:glance-appwidget-external-protobuf).
BSD3_PROTOBUF_TEXT = """\
Copyright 2008 Google Inc.  All rights reserved.

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are
met:

    * Redistributions of source code must retain the above copyright
notice, this list of conditions and the following disclaimer.
    * Redistributions in binary form must reproduce the above
copyright notice, this list of conditions and the following disclaimer
in the documentation and/or other materials provided with the
distribution.
    * Neither the name of Google Inc. nor the names of its
contributors may be used to endorse or promote products derived from
this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
"AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
(INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

Code generated by the Protocol Buffer compiler is owned by the owner
of the input file used when generating it.  This code is not
standalone and requires a support library to be linked with it.  This
support library is itself covered by the above license.
"""


def render_android_licenses() -> str:
    """The text shown for "third-party licenses" in the Android app (bundled as an asset)."""
    npm = {n: v for n, v in npm_runtime().items() if n not in NPM_NOT_IN_APK}
    gradle = gradle_runtime()
    texts: dict[str, str] = {}
    rule = "=" * 78

    def need(lic: str) -> None:
        if lic not in {"MIT", "0BSD", "Apache-2.0", "BSD-3-Clause"}:
            raise SystemExit(
                f"the Android license asset has no text for {lic}; add it to render_android_licenses"
            )
        texts[lic] = ""

    out = [
        "Third-party licenses of Roadlake Sidekick for Android",
        rule,
        "",
        "Sidekick itself is licensed under the Roadlake Sidekick Source Available License (LICENSE.md in the",
        "repository https://github.com/CarlOMattsson/roadlake-sidekick). The app contains the components below, which keep",
        "their own licenses and copyright notices. This file is generated by tools/third_party_notices.py from the lock",
        "files; the same list for every part of Sidekick is THIRD_PARTY_NOTICES.md in the repository.",
        "",
        "Web part (React, Capacitor)",
        rule,
    ]
    for name, (version, lic) in npm.items():
        need(lic)
        notice = NPM_NOTICES.get(name)
        if notice is None:
            raise SystemExit(
                f"no copyright notice for npm package {name}; add it to NPM_NOTICES"
            )
        out.append(f"{name} {version} ({lic}): {notice}")
    out += [
        "",
        "Native part (AndroidX, Kotlin, protobuf and others, from the Gradle release classpath)",
        rule,
    ]
    for coord, versions in gradle.items():
        found = gradle_license(coord)
        if found is None:
            raise SystemExit(
                f"no license entry for Gradle artifact {coord}; add it to GRADLE_LICENSES"
            )
        need(found[0])
        out.append(f"{coord} {versions} ({found[0]}): {found[1]}")
    out += ["", "Other", rule, MATERIAL_ICON_NOTICE.replace("`", ""), ""]
    texts.update(
        {
            "MIT": MIT_TEXT,
            "0BSD": ZERO_BSD_TEXT,
            "Apache-2.0": (LICENSE_TEXTS / "Apache-2.0.txt").read_text().strip("\n")
            + "\n",
            "BSD-3-Clause": BSD3_PROTOBUF_TEXT,
        }
    )
    out += [
        "Notice of the Kotlin libraries (Apache License 2.0, section 4(d))",
        rule,
        KOTLIN_NOTICE,
    ]
    headings = {
        "MIT": "MIT License (the web components above; each has the copyright line listed there)",
        "0BSD": "BSD Zero Clause License (tslib; Copyright (c) Microsoft Corporation.)",
        "Apache-2.0": "Apache License 2.0 (AndroidX, Kotlin, Gson, Tink and the other Apache-2.0 components above)",
        "BSD-3-Clause": "BSD 3-Clause License (protobuf-java and Glance's protobuf runtime)",
    }
    for lic in ("MIT", "0BSD", "BSD-3-Clause", "Apache-2.0"):
        out += [headings[lic], rule, texts[lic].rstrip("\n"), ""]
    return "\n".join(out).rstrip("\n") + "\n"


# Every generated file: path -> render function. --write rewrites all of them, --check fails when one lags.
def generated_files(venv: Path | None) -> dict[Path, str]:
    files = {ANDROID_LICENSES: render_android_licenses()}
    if venv is not None:
        files[OUTPUT] = render(venv)
    return files


def section_rows(text: str, section: str) -> dict[str, str]:
    """First two columns (name, version) of the table that follows a section marker."""
    rows: dict[str, str] = {}
    lines = text.splitlines()
    try:
        start = lines.index(MARKER.format(section))
    except ValueError:
        return rows
    for line in lines[start + 3 :]:
        if not line.startswith("|"):
            break
        cells = [c.strip() for c in line.strip("|").split(" | ")]
        rows[cells[0]] = cells[1]
    return rows


def check() -> list[str]:
    if not OUTPUT.exists():
        return [
            f"{OUTPUT.name} is missing; run python3 tools/third_party_notices.py --write"
        ]
    text = OUTPUT.read_text()
    expected = {
        "python": python_closure(),
        "npm": {n: v for n, (v, _) in npm_runtime().items()},
        "gradle": gradle_runtime(),
    }
    problems = []
    for section, want in expected.items():
        have = section_rows(text, section)
        for name in sorted(set(want) | set(have)):
            if want.get(name) != have.get(name):
                problems.append(
                    f"{section}: {name} is {have.get(name, 'missing')} in the file, {want.get(name, 'gone')} in the lock file"
                )
    for coord in gradle_runtime():
        if gradle_license(coord) is None:
            problems.append(f"gradle: no license entry for {coord} in GRADLE_LICENSES")
    for image in sorted(deploy_images() - set(CONTAINERS)):
        problems.append(
            f"containers: {image} is used in deploy/ or the Dockerfile but missing from CONTAINERS"
        )
    have_images = set(section_rows(text, "containers"))
    for image in sorted(set(CONTAINERS) ^ have_images):
        problems.append(f"containers: {image} differs between CONTAINERS and the file")
    for path in IMAGE_LICENSE_FILES:
        if not path.exists():
            problems.append(
                f"image licenses: {path.relative_to(REPO)} is missing (the Dockerfile copies it)"
            )
    for name in sorted(set(npm_runtime()) - set(NPM_NOTICES)):
        problems.append(
            f"android licenses: no copyright notice for npm package {name} in NPM_NOTICES"
        )
    if not ANDROID_LICENSES.exists():
        problems.append(f"{rel(ANDROID_LICENSES)} is missing")
    elif ANDROID_LICENSES.read_text() != render_android_licenses():
        problems.append(f"{rel(ANDROID_LICENSES)} lags the lock files")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--write",
        action="store_true",
        help="regenerate THIRD_PARTY_NOTICES.md and the Android license asset",
    )
    mode.add_argument(
        "--check", action="store_true", help="fail when the file lags the lock files"
    )
    parser.add_argument(
        "--venv",
        type=Path,
        default=REPO / "backend" / ".venv",
        help="backend virtualenv (for --write)",
    )
    args = parser.parse_args()
    if args.write:
        for path, text in generated_files(args.venv).items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
            print(f"wrote {path.relative_to(REPO)}")
        return 0
    problems = check()
    for problem in problems:
        print(f"third-party notices: {problem}", file=sys.stderr)
    if problems:
        print("run: python3 tools/third_party_notices.py --write", file=sys.stderr)
        return 1
    print("third-party notices: up to date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
