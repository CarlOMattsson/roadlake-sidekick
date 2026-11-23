"""The check-in domain names no result, sets no threshold and carries no support text.

By design nothing in Sidekick reacts to a value, and the card carries no crisis or helpline
text. These checks fail when a name or a text that would start that is added.
"""

import ast
import re
from pathlib import Path

from sidekick.checkins.domain import consent

DOMAIN = Path(str(consent.__file__)).parent
# A word in an identifier that would make a value mean something: a grade, a limit, a label.
FORBIDDEN_NAME_WORDS = {
    "threshold",
    "cutoff",
    "severity",
    "risk",
    "score",
    "grade",
    "label",
    "better",
    "worse",
    "good",
    "bad",
    "crisis",
    "alert",
    "warning",
    "diagnosis",
    "notify",
}
SUPPORT_TEXT = re.compile(
    r"\b(1177|112|90101|kris|helpline|hotline|crisis|suicid|självmord|emergency|nödläge)", re.I
)


def _identifiers(path: Path) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.FunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.arg | ast.keyword) and node.arg:
            names.add(node.arg)
    return names


def test_no_identifier_in_the_domain_names_a_judgement_or_an_action() -> None:
    found = {
        (path.name, name)
        for path in DOMAIN.glob("*.py")
        for name in _identifiers(path)
        if FORBIDDEN_NAME_WORDS & set(name.lower().split("_"))
    }
    assert not found


def test_no_text_in_the_domain_carries_support_numbers_or_crisis_wording() -> None:
    texts: list[str] = []
    for path in DOMAIN.glob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                texts.append(node.value)
    assert texts
    assert not [text for text in texts if SUPPORT_TEXT.search(text)]
