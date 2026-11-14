"""User documentation exists in English and Swedish with the same structure.

For every (English, Swedish) pair: the same sequence of heading levels, the same code blocks apart
from comments and `<placeholders>`, the same mermaid diagrams by node id (labels are prose and may
be translated), a link to the other language, and relative links in both files that resolve (file
and, for Markdown targets, anchor).

A checkout may stage reviewed copies of these documents in a directory named by
DOCS_PARITY_STAGING; paths are looked up there first and then from the repository root.

The pairs are discovered, not listed: every published `*.sv.md` has an English twin and every
published English document outside EN_ONLY has a Swedish one. "Published" is what the export
allowlist and denylist let through (everything, in a checkout that has neither), plus the staged
copies. The website under `website/` has its own checks at the end of this module: the same pages
in both languages, the same structure, and the same UI string keys.
"""

import importlib.util
import json
import os
import posixpath
import re
import sys
from pathlib import Path, PurePosixPath
from types import ModuleType

import pytest

pytestmark = pytest.mark.policy

ROOT = Path(__file__).resolve().parents[3]
# Optional directory with reviewed copies of the documents, set by a checkout that stages them.
OVERLAY = Path(os.environ.get("DOCS_PARITY_STAGING", ROOT / ".docs-staging-unset"))

# English-only documents (patterns from the repository root, matched with full_match). Some are
# generated or normative English sources.
EN_ONLY = (
    "AGENTS.md",
    "CHANGELOG.md",
    "CLA.md",
    "LICENSE.md",
    "THIRD_PARTY_NOTICES.md",
    "docs/reference/**",
    "docs/decisions/**",
    "docs/explanation/architecture/**",
    "docs/explanation/threat-model.md",
)
# Where documents are looked for: the repository root files and these folders.
DOCUMENT_DIRS = ("docs", "deploy")
SKIPPED_PARTS = {"node_modules", ".git", ".astro", "dist"}
EXPORT_CONFIG = ROOT / "tools" / "export"
WEBSITE = ROOT / "website"
WEBSITE_DOCS = WEBSITE / "src" / "content" / "docs"
WEBSITE_UI = WEBSITE / "src" / "content" / "i18n"
# website/src/content/docs/<lang>/docs/ is generated from the documents above (git-ignored).
GENERATED_WEBSITE_DIR = "docs"


def _export_filter() -> ModuleType | None:
    """The export's own select logic, or None in a checkout without tools/export."""
    path = EXPORT_CONFIG / "export_filter.py"
    if not path.exists():
        return None
    spec = importlib.util.spec_from_file_location("sidekick_export_filter", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(spec.name, module)
    spec.loader.exec_module(module)
    return module


def _markdown_under(base: Path) -> set[str]:
    """Markdown files in the document locations below base, as paths relative to base."""
    found = {path.name for path in base.glob("*.md")}
    for folder in DOCUMENT_DIRS:
        if not (base / folder).is_dir():
            continue
        for path in (base / folder).rglob("*.md"):
            relative = path.relative_to(base)
            if not SKIPPED_PARTS & set(relative.parts):
                found.add(relative.as_posix())
    return found


def _published_documents() -> set[str]:
    """Documents of the published repository: the export selection plus the staged copies."""
    selected = _markdown_under(ROOT)
    export_filter = _export_filter()
    if export_filter is not None:
        allow = export_filter.load_patterns(EXPORT_CONFIG / "allowlist.txt")
        deny = export_filter.load_patterns(EXPORT_CONFIG / "denylist.txt")
        selected = {
            rel
            for rel in selected
            if export_filter.matches(allow, rel) and not export_filter.matches(deny, rel)
        }
    if OVERLAY.is_dir():
        selected |= _markdown_under(OVERLAY)
    return selected


def _english_only(relative: str) -> bool:
    return any(PurePosixPath(relative).full_match(pattern) for pattern in EN_ONLY)


def _swedish_twin(english: str) -> str:
    return english[: -len(".md")] + ".sv.md"


def _pairs_and_gaps(documents: set[str]) -> tuple[list[tuple[str, str]], list[str]]:
    """The (English, Swedish) pairs among documents, and a message for every missing twin."""
    pairs: list[tuple[str, str]] = []
    gaps: list[str] = []
    for name in sorted(documents):
        if name.endswith(".sv.md"):
            english = name[: -len(".sv.md")] + ".md"
            if english not in documents:
                gaps.append(f"{name}: the English twin {english} is missing")
        elif _swedish_twin(name) in documents:
            pairs.append((name, _swedish_twin(name)))
        elif not _english_only(name):
            gaps.append(f"{name}: the Swedish twin {_swedish_twin(name)} is missing")
    return pairs, gaps


_DISCOVERED_PAIRS, _DISCOVERY_GAPS = _pairs_and_gaps(_published_documents())
PAIRS = _DISCOVERED_PAIRS

FENCE = re.compile(r"^\s*```")
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*$")
LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
EXPLICIT_ID = re.compile(r"<a\s+(?:id|name)=\"([^\"]+)\"")
EXTERNAL = re.compile(r"^[a-z][a-z0-9+.-]*:")
TRAILING_COMMENT = re.compile(r"(^|\s+)#.*$")
PLACEHOLDER = re.compile(r"<[^<>\n]*>")
MERMAID_QUOTED = re.compile(r"\"[^\"]*\"")
MERMAID_NODE = re.compile(r"([A-Za-z_][\w-]*)\s*\[")


def _resolve(relative: str) -> Path:
    """The file for a repository path: a staged copy if there is one."""
    overlaid = OVERLAY / relative
    return overlaid if overlaid.exists() else ROOT / relative


def _is_mermaid(block: list[str]) -> bool:
    return block[0] == "```mermaid"


def _mermaid_node_ids(block: list[str]) -> set[str]:
    """The identifiers before `[` in a diagram, with quoted labels ignored."""
    ids: set[str] = set()
    for line in block[1:]:
        ids.update(MERMAID_NODE.findall(MERMAID_QUOTED.sub('""', line)))
    return ids


class _Doc:
    def __init__(self, relative: str, text: str | None = None) -> None:
        self.relative = relative
        self.path = _resolve(relative)
        self.text = self.path.read_text(encoding="utf-8") if text is None else text
        self.headings: list[tuple[int, str]] = []
        self.code_blocks: list[list[str]] = []
        self.links: list[str] = []
        self.ids: set[str] = set()
        block: list[str] | None = None
        for line in self.text.splitlines():
            if FENCE.match(line):
                if block is None:
                    block = [line.strip()]  # the opening fence carries the language
                else:
                    self.code_blocks.append(block)
                    block = None
                continue
            if block is not None:
                code = PLACEHOLDER.sub("<>", TRAILING_COMMENT.sub("", line)).strip()
                if code:
                    block.append(code)
                continue
            heading = HEADING.match(line)
            if heading:
                self.headings.append((len(heading.group(1)), heading.group(2)))
            self.links.extend(LINK.findall(line))
            self.ids.update(EXPLICIT_ID.findall(line))
        assert block is None, f"{relative}: unclosed code block"

    def anchors(self) -> set[str]:
        """GitHub's heading anchors plus explicit `<a id>` targets."""
        slugs = set(self.ids)
        for _, title in self.headings:
            plain = re.sub(r"[`*_]", "", title).lower()
            slugs.add(re.sub(r"[^\w\- ]", "", plain).replace(" ", "-"))
        return slugs

    def dead_links(self) -> list[str]:
        dead = []
        for target in self.links:
            if EXTERNAL.match(target):
                continue
            path, _, anchor = target.partition("#")
            if not path:
                if anchor not in self.anchors():
                    dead.append(target)
                continue
            linked = posixpath.normpath(posixpath.join(posixpath.dirname(self.relative), path))
            resolved = _resolve(linked)
            anchored = anchor and resolved.suffix == ".md"
            if not resolved.exists() or (anchored and anchor not in _Doc(linked).anchors()):
                dead.append(target)
        return dead


@pytest.fixture(params=PAIRS, ids=[english for english, _ in PAIRS])
def pair(request: pytest.FixtureRequest) -> tuple[_Doc, _Doc]:
    english, swedish = request.param
    for relative in (english, swedish):
        if not _resolve(relative).exists():
            pytest.skip(f"{relative} is not in this checkout (set DOCS_PARITY_STAGING to stage it)")
    return _Doc(english), _Doc(swedish)


def test_both_languages_have_the_same_heading_levels(pair: tuple[_Doc, _Doc]) -> None:
    english, swedish = pair
    assert english.headings
    assert [level for level, _ in swedish.headings] == [level for level, _ in english.headings]


def test_both_languages_have_the_same_code_blocks(pair: tuple[_Doc, _Doc]) -> None:
    english, swedish = pair
    assert len(swedish.code_blocks) == len(english.code_blocks)
    blocks = zip(swedish.code_blocks, english.code_blocks, strict=True)
    for number, (ours, theirs) in enumerate(blocks, 1):
        assert _is_mermaid(ours) == _is_mermaid(theirs), (
            f"code block {number}: mermaid in one language only"
        )
        if _is_mermaid(ours):
            continue  # checked by test_both_languages_have_the_same_mermaid_node_ids
        assert ours == theirs, f"code block {number} differs beyond comments and placeholders"


def test_both_languages_have_the_same_mermaid_node_ids(pair: tuple[_Doc, _Doc]) -> None:
    english, swedish = pair
    ours = [block for block in swedish.code_blocks if _is_mermaid(block)]
    theirs = [block for block in english.code_blocks if _is_mermaid(block)]
    assert len(ours) == len(theirs)
    for number, (sv_block, en_block) in enumerate(zip(ours, theirs, strict=True), 1):
        assert _mermaid_node_ids(sv_block) == _mermaid_node_ids(en_block), (
            f"mermaid diagram {number}: node ids differ"
        )


def test_each_language_links_to_the_other(pair: tuple[_Doc, _Doc]) -> None:
    english, swedish = pair
    assert Path(swedish.relative).name in english.links
    assert Path(english.relative).name in swedish.links


def test_relative_links_resolve(pair: tuple[_Doc, _Doc]) -> None:
    if not OVERLAY.is_dir() and not (ROOT / "README.sv.md").exists():
        pytest.skip(
            "root documents are not in this checkout; set DOCS_PARITY_STAGING to stage them"
        )
    for doc in pair:
        assert not doc.dead_links(), f"{doc.relative}: {doc.dead_links()}"


# --- discovery ---------------------------------------------------------------------------------


def test_every_published_document_has_its_twin() -> None:
    assert _DISCOVERED_PAIRS, "no document pairs were discovered"
    assert not _DISCOVERY_GAPS, "\n".join(_DISCOVERY_GAPS)


def test_discovery_fails_for_an_invented_pair_without_a_swedish_file() -> None:
    documents = {"docs/guide.md", "docs/guide.sv.md", "docs/invented.md", "docs/reference/x.md"}
    pairs, gaps = _pairs_and_gaps(documents)
    assert pairs == [("docs/guide.md", "docs/guide.sv.md")]
    assert gaps == ["docs/invented.md: the Swedish twin docs/invented.sv.md is missing"]


def test_discovery_fails_for_a_swedish_file_without_an_english_twin() -> None:
    _, gaps = _pairs_and_gaps({"docs/only.sv.md"})
    assert gaps == ["docs/only.sv.md: the English twin docs/only.md is missing"]


def test_code_placeholders_and_comments_do_not_count_as_differences() -> None:
    english = "# T\n\n```bash\nrun <your-host>  # explain\n```\n"
    swedish = "# T\n\n```bash\nrun <din-värd>  # förklara\n```\n"
    assert _Doc("a.md", english).code_blocks == _Doc("a.sv.md", swedish).code_blocks
    other = "# T\n\n```bash\nrun --other\n```\n"
    assert _Doc("a.md", english).code_blocks != _Doc("a.sv.md", other).code_blocks


# --- the website -------------------------------------------------------------------------------

MDX_FENCE = re.compile(r"^\s*(```|:::)")
MDX_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
MDX_COMPONENT = re.compile(r"<([A-Z][A-Za-z0-9]*)\b")
MDX_RAW_HEADING = re.compile(r"<h([1-6])\b")
MDX_ASIDE = re.compile(r"^:::\w+|<Aside\b", re.MULTILINE)
website_present = pytest.mark.skipif(
    not WEBSITE_DOCS.is_dir(), reason="website/ is not in this checkout"
)


def _website_pages(language: str) -> set[str]:
    base = WEBSITE_DOCS / language
    return {
        path.relative_to(base).as_posix()
        for path in base.rglob("*")
        if path.is_file() and path.relative_to(base).parts[0] != GENERATED_WEBSITE_DIR
    }


class _Page:
    """The structure of one hand-written website page (.mdx) that both languages share."""

    def __init__(self, text: str) -> None:
        match = MDX_FRONTMATTER.match(text)
        self.frontmatter_keys = (
            sorted(re.findall(r"^([A-Za-z][\w-]*):", match.group(1), re.MULTILINE)) if match else []
        )
        body = text[match.end() :] if match else text
        self.headings: list[int] = []
        self.code_blocks: list[list[str]] = []
        self.components: list[str] = []
        self.asides = len(MDX_ASIDE.findall(body))
        block: list[str] | None = None
        for line in body.splitlines():
            if line.lstrip().startswith("```"):
                if block is None:
                    block = [line.strip()]
                else:
                    self.code_blocks.append(block)
                    block = None
                continue
            if block is not None:
                code = PLACEHOLDER.sub("<>", line).strip()
                if code:
                    block.append(code)
                continue
            heading = HEADING.match(line)
            if heading:
                self.headings.append(len(heading.group(1)))
            self.headings.extend(int(level) for level in MDX_RAW_HEADING.findall(line))
            self.components.extend(MDX_COMPONENT.findall(line))


@website_present
def test_website_pages_exist_in_both_languages() -> None:
    swedish, english = _website_pages("sv"), _website_pages("en")
    assert swedish, "no Swedish website pages"
    only_sv, only_en = sorted(swedish - english), sorted(english - swedish)
    assert swedish == english, f"only sv: {only_sv}, only en: {only_en}"


@website_present
def test_website_page_structure() -> None:
    for name in sorted(_website_pages("sv") & _website_pages("en")):
        if not name.endswith(".mdx"):
            continue
        swedish = _Page((WEBSITE_DOCS / "sv" / name).read_text(encoding="utf-8"))
        english = _Page((WEBSITE_DOCS / "en" / name).read_text(encoding="utf-8"))
        assert swedish.frontmatter_keys == english.frontmatter_keys, f"{name}: frontmatter keys"
        assert swedish.headings == english.headings, f"{name}: heading levels"
        assert swedish.code_blocks == english.code_blocks, f"{name}: code blocks"
        assert swedish.asides == english.asides, f"{name}: aside blocks"
        assert swedish.components == english.components, f"{name}: components or their order"


def test_website_page_structure_notices_a_missing_component() -> None:
    with_tiers = _Page("---\ntitle: A\n---\n\n## H\n\n<PriceTiers />\n")
    without = _Page("---\ntitle: A\n---\n\n## H\n\n")
    assert with_tiers.components == ["PriceTiers"] != without.components


def _flatten(value: object, prefix: str = "") -> dict[str, object]:
    if isinstance(value, dict):
        flat: dict[str, object] = {}
        for key, inner in value.items():
            flat.update(_flatten(inner, f"{prefix}.{key}" if prefix else str(key)))
        return flat
    return {prefix: value}


def _ui_file(language: str) -> Path:
    return WEBSITE_UI / f"{language}.json"


def _filled(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


@website_present
def test_website_ui_strings() -> None:
    strings = {
        language: _flatten(json.loads(_ui_file(language).read_text(encoding="utf-8")))
        for language in ("sv", "en")
    }
    assert strings["sv"].keys() == strings["en"].keys()
    for language, values in strings.items():
        empty = [key for key, value in values.items() if not _filled(value)]
        assert not empty, f"{language}.json has empty values: {empty}"
