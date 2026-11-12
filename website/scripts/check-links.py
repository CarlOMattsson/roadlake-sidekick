#!/usr/bin/env python3
"""Check the built site: internal links, anchors, hreflang and plain http links (stdlib only).

Usage: check-links.py [dist] [--base /path] [--site https://host] [--external]

* Every internal href/src must resolve to a file in dist/ (the base path is honoured, directories need a trailing slash).
* Every #fragment must exist as an id (or <a name>) on the target page.
* Every page except 404.html must declare <link rel="alternate" hreflang> for both sv and en.
* No http: link or resource is allowed (https only).
* --external prints the external https links as a report. It never fails the run.

Exit code: 0 when clean, 1 on any problem. The base path and site URL default to SITE_BASE / SITE_URL, as the build uses them.
"""
from __future__ import annotations

import argparse
import os
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

LINK_ATTRS = {
    "a": ("href",),
    "link": ("href",),
    "script": ("src",),
    "img": ("src",),
    "source": ("src",),
    "iframe": ("src",),
    "audio": ("src",),
    "video": ("src", "poster"),
    "use": ("href", "xlink:href"),
    "form": ("action",),
    "area": ("href",),
    "embed": ("src",),
    "track": ("src",),
}
IGNORED_SCHEMES = ("mailto:", "tel:", "data:", "javascript:", "blob:", "sms:")
REQUIRED_HREFLANGS = ("sv", "en")


class Page(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: set[str] = set()
        self.links: list[tuple[str, str, str]] = []  # (tag, attribute, value)
        self.hreflangs: set[str] = set()
        self.ignore_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: (v or "") for k, v in attrs}
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "a" and "name" in a:
            self.ids.add(a["name"])
        if tag == "link" and a.get("rel", "").lower() == "alternate" and a.get("hreflang"):
            self.hreflangs.add(a["hreflang"].lower())
        for attr in LINK_ATTRS.get(tag, ()):
            if attr in a:
                self.links.append((tag, attr, a[attr]))
        if tag == "meta" and a.get("http-equiv", "").lower() == "refresh" and "url=" in a.get("content", "").lower():
            self.links.append((tag, "refresh", a["content"].split("=", 1)[1].strip()))


def parse(path: Path) -> Page:
    page = Page()
    page.feed(path.read_text(encoding="utf-8"))
    return page


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dist", nargs="?", default="dist")
    ap.add_argument("--base", default=os.environ.get("SITE_BASE", ""))
    ap.add_argument("--site", default=os.environ.get("SITE_URL", "https://roadlake.com"))
    ap.add_argument("--external", action="store_true", help="report external https links (never fails)")
    args = ap.parse_args()

    dist = Path(args.dist).resolve()
    if not dist.is_dir():
        print(f"check-links: {dist} is not a directory (run the build first)", file=sys.stderr)
        return 2
    base = "/" + args.base.strip("/") if args.base.strip("/") else ""
    site_host = urlsplit(args.site).netloc

    cache: dict[Path, Page] = {}

    def page_of(path: Path) -> Page:
        if path not in cache:
            cache[path] = parse(path)
        return cache[path]

    def resolve(url_path: str) -> Path | None:
        """Map a site path (already stripped of the base) to a file under dist/, or None."""
        rel = unquote(url_path).lstrip("/")
        target = (dist / rel).resolve()
        if dist not in target.parents and target != dist:
            return None
        if url_path.endswith("/") or rel == "":
            index = target / "index.html"
            return index if index.is_file() else None
        return target if target.is_file() else None

    problems: list[str] = []
    external: dict[str, set[str]] = {}
    pages = sorted(dist.rglob("*.html"))

    for file in pages:
        rel_file = file.relative_to(dist).as_posix()
        page = page_of(file)
        # The URL path of this page, with the base, for resolving relative links.
        page_url = "/" + (rel_file[: -len("index.html")] if rel_file.endswith("index.html") else rel_file)
        page_url = base + page_url if base else page_url
        label = rel_file

        if rel_file != "404.html":
            missing = [lang for lang in REQUIRED_HREFLANGS if lang not in page.hreflangs]
            if missing:
                problems.append(f"{label}: missing hreflang for {', '.join(missing)}")

        for tag, attr, value in page.links:
            value = value.strip()
            if not value or value.startswith(IGNORED_SCHEMES):
                continue
            where = f"{label}: <{tag} {attr}=\"{value}\">"
            if value.startswith("http:") or value.startswith("//http:"):
                problems.append(f"{where} uses http:, only https is allowed")
                continue
            parts = urlsplit(value)
            if parts.scheme or value.startswith("//"):
                if parts.scheme == "https" and parts.netloc == site_host:
                    pass  # An absolute URL on our own site (canonical, hreflang, sitemap): check it like an internal link.
                else:
                    if parts.scheme not in ("https", ""):
                        problems.append(f"{where} has the scheme {parts.scheme}:")
                    external.setdefault(value, set()).add(label)
                    continue
            url_path = parts.path
            if not url_path:
                target_file, target_label = file, label  # fragment-only link
            else:
                if not url_path.startswith("/"):
                    # Relative to the page's directory.
                    directory = page_url if page_url.endswith("/") else page_url.rsplit("/", 1)[0] + "/"
                    segments: list[str] = []
                    for seg in (directory + url_path).split("/"):
                        if seg == "..":
                            if segments:
                                segments.pop()
                        elif seg != ".":
                            segments.append(seg)
                    url_path = "/".join(segments)
                    if not url_path.startswith("/"):
                        url_path = "/" + url_path
                if base:
                    if url_path != base and not url_path.startswith(base + "/"):
                        problems.append(f"{where} is outside the base path {base}")
                        continue
                    url_path = url_path[len(base):] or "/"
                resolved = resolve(url_path)
                if resolved is None:
                    hint = ""
                    if not url_path.endswith("/") and resolve(url_path + "/") is not None:
                        hint = " (missing trailing slash)"
                    problems.append(f"{where} does not resolve to a file in dist/{hint}")
                    continue
                target_file, target_label = resolved, resolved.relative_to(dist).as_posix()
            fragment = unquote(parts.fragment)
            if fragment and fragment != "top" and target_file.suffix == ".html":
                if fragment not in page_of(target_file).ids:
                    problems.append(f"{where} points to a missing anchor #{fragment} on {target_label}")

    if args.external:
        print(f"External links ({len(external)}), report only:")
        for url in sorted(external):
            print(f"  {url}   [{len(external[url])} page(s), e.g. {sorted(external[url])[0]}]")

    if problems:
        print(f"check-links: {len(problems)} problem(s) in {len(pages)} page(s)", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    print(f"check-links: OK ({len(pages)} pages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
