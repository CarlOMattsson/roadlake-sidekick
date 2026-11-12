#!/usr/bin/env python3
"""Check that the website prices have not drifted from the licensing documents (stdlib only).

Compares src/data/pricing.json with the price tables in docs/explanation/licensing(.sv).md, checks that longer
personal periods are strictly cheaper per month, checks the shape of the buy URLs, and checks that the app's
LICENSE_BUY_URL agrees with the site.

Usage: check-pricing.py [--repo-root DIR] [--pricing FILE] [--docs-root DIR]
Exit code 0 when everything agrees, 1 with one line per differing row otherwise.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

LICENSING_DOC = "docs/explanation/licensing"
APP_FILE = "frontend/src/features/mcp-apps/license-state.ts"
UNIT_MONTHS = {"month": 1, "months": 1, "månad": 1, "månader": 1, "year": 12, "years": 12, "år": 12}
POLAR_HOSTS = ("polar.sh",)


def parse_table(text: str) -> dict:
    """Return {'personal': {(months, amount): cell}, 'org': {...}, 'currencies': set} from the price table."""
    personal: set[tuple[int, int]] = set()
    org: dict[str, int] = {}
    currencies: set[str] = set()
    for line in text.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) != 3 or not line.lstrip().startswith("|"):
            continue
        kind, length, price = cells
        m_len = re.match(r"(\d+)\s+(\w+)$", length, re.IGNORECASE)
        m_price = re.match(r"(\d+)\s+([A-Z]{3})\b(.*)$", price)
        if not (m_len and m_price and m_len.group(2).lower() in UNIT_MONTHS):
            continue
        months = int(m_len.group(1)) * UNIT_MONTHS[m_len.group(2).lower()]
        amount = int(m_price.group(1))
        currencies.add(m_price.group(2))
        if re.match(r"organi[sz]", kind, re.IGNORECASE):
            org = {"months": months, "amount": amount}
            per = re.search(r"\b(\d+)\s+(?:employees|anställda)", m_price.group(3))
            if per:
                org["perEmployees"] = int(per.group(1))
        else:
            personal.add((months, amount))
    return {"personal": personal, "org": org, "currencies": currencies}


def org_custom_above(text: str) -> int | None:
    m = re.search(r"(?:more than|fler än|över)\s+(\d+)\s+(?:employees|anställda)", text, re.IGNORECASE)
    return int(m.group(1)) if m else None


def find_doc(root: Path, suffix: str) -> Path | None:
    path = root / f"{LICENSING_DOC}{suffix}.md"
    return path if path.is_file() else None


def polar_ok(url: str) -> bool:
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    return parts.scheme == "https" and any(host == h or host.endswith("." + h) for h in POLAR_HOSTS)


def app_buy_url(root: Path) -> str | None:
    path = root / APP_FILE
    if not path.is_file():
        return None
    m = re.search(r'export\s+const\s+LICENSE_BUY_URL\s*(?::[^=]+)?=\s*"([^"]*)"', path.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def main() -> int:
    here = Path(__file__).resolve().parent
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-root", default=str(here.parents[1]))
    ap.add_argument("--pricing", default=str(here.parent / "src/data/pricing.json"))
    ap.add_argument("--docs-root", default=None, help="where the licensing documents are (default: the repo root)")
    args = ap.parse_args()
    repo = Path(args.repo_root)
    docs_root = Path(args.docs_root) if args.docs_root else repo

    pricing = json.loads(Path(args.pricing).read_text(encoding="utf-8"))
    problems: list[str] = []

    site_personal = {(int(r["months"]), int(r["amount"])) for r in pricing["personal"]}
    site_org = pricing["org"]

    for suffix, lang in ((".sv", "sv"), ("", "en")):
        doc = find_doc(docs_root, suffix)
        if doc is None:
            problems.append(f"licensing document ({lang}) not found under {docs_root}")
            continue
        text = doc.read_text(encoding="utf-8")
        table = parse_table(text)
        label = f"{doc.relative_to(docs_root)}"
        if not table["personal"] or not table["org"]:
            problems.append(f"{label}: no price table found")
            continue
        if table["currencies"] != {pricing["currency"]}:
            problems.append(f"{label}: currency {sorted(table['currencies'])} differs from pricing.json {pricing['currency']}")
        for months, amount in sorted(table["personal"] - site_personal):
            problems.append(f"{label}: Personal {months} month(s) {amount} {pricing['currency']} is not in pricing.json")
        for months, amount in sorted(site_personal - table["personal"]):
            problems.append(f"pricing.json: Personal {months} month(s) {amount} {pricing['currency']} differs from {label}")
        expected_org = {**table["org"], "customAbove": org_custom_above(text)}
        for key in ("months", "amount", "perEmployees", "customAbove"):
            if expected_org.get(key) != site_org.get(key):
                problems.append(
                    f"pricing.json: org.{key} is {site_org.get(key)} but {label} says {expected_org.get(key)}"
                )

    # Longer personal periods must cost strictly less per month and strictly more in total.
    tiers = sorted((int(r["months"]), int(r["amount"])) for r in pricing["personal"])
    for (m_a, p_a), (m_b, p_b) in zip(tiers, tiers[1:]):
        if p_b <= p_a:
            problems.append(f"pricing.json: Personal {m_b} months ({p_b}) must cost more in total than {m_a} month(s) ({p_a})")
        if p_b * m_a >= p_a * m_b:
            problems.append(
                f"pricing.json: Personal {m_b} months ({p_b / m_b:.2f}/month) must cost strictly less per month than {m_a} month(s) ({p_a / m_a:.2f}/month)"
            )

    urls = [("storeUrl", pricing.get("storeUrl", ""))]
    urls += [(f"personal[{r['months']} months].buyUrl", r.get("buyUrl", "")) for r in pricing["personal"]]
    for name, url in urls:
        if url and not polar_ok(url):
            problems.append(f"pricing.json: {name} must be empty or an https:// URL on Polar ({', '.join(POLAR_HOSTS)}), got {url!r}")

    app_url = app_buy_url(repo)
    if app_url is None:
        problems.append(f"{APP_FILE}: LICENSE_BUY_URL not found")
    else:
        site_url = pricing.get("storeUrl", "")
        buy_urls = {u for _, u in urls if u}
        if bool(app_url) != bool(site_url or buy_urls):
            problems.append(f"LICENSE_BUY_URL ({app_url!r}) and the site's shop URL ({site_url or sorted(buy_urls) or ''!r}) must be both empty or both set")
        elif app_url and app_url != site_url and not re.search(r"/buy/?$", app_url):
            problems.append(f"LICENSE_BUY_URL {app_url!r} must equal storeUrl {site_url!r} or point to the site's /buy/ page")

    if problems:
        print(f"check-pricing: {len(problems)} difference(s)", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    print("check-pricing: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
