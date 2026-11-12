"""Swedish phonetic key for finding a name that voice input misheard ("Shell" for "Kjell").

Pure functions, no I/O. The key is only a fallback for name search: a caller uses it after the
normal name, alias and typo-tolerant matches find nothing, never instead of them.

Rules, applied per letter-run (a word; digits, spaces and punctuation split words and are dropped):

1. Lowercase; é, è, ê and ë become e. å, ä and ö are kept as they are.
2. Word start: dj, gj, hj and lj become j (`Djurgården` -> `jurgården`, `Ljus` -> `jus`).
3. The sj-sound and the tj-sound share one code, the capital X, which no lowercased input produces:
   sj, skj, stj, sch, sh, ch, kj, tj, and sk before e/i/y/ä/ö. The two sounds share a code on
   purpose: Swedish speakers and voice input often hear "kj" and "sj" alike (Kjell, Shell, Tjell,
   Chell). Consequence: Kjell, Tjell, Chell and Shell all give the key "Xel".
4. k before e/i/y/ä/ö becomes X (the tj-sound, Kerstin -> Xerstin).
5. c before e/i/y becomes s; any other c becomes k (Cecilia -> sesilia, Carl -> karl).
6. z becomes s (Zara -> sara).
7. ph becomes f, q becomes k, w becomes v, x becomes ks (Philip -> filip, Axel -> aksel).
8. h after a vowel is dropped (Johan -> joan, Joanna -> joanna).
9. Doubled letters become single letters (Anna -> ana, Kaffe -> kafe).

The keys of a whole name are the keys of its words joined together, so "Kjell Hansson" and
"Shell Hansson" match as a whole, and a single word in a multi-word name matches on its own.
"""

from __future__ import annotations

import re

_ACCENTS = str.maketrans({"é": "e", "è": "e", "ê": "e", "ë": "e"})
_LETTER_RUN = re.compile(r"[^\W\d_]+")
_WORD_START = re.compile(r"^(dj|gj|hj|lj)")
# Longer spellings come first so that the longest match at a position wins (skj before sj).
_SJ_TJ = re.compile(r"skj|stj|sch|sj|sh|ch|kj|tj|sk(?=[eiyäö])")
_SOFT_K = re.compile(r"k(?=[eiyäö])")
_SOFT_C = re.compile(r"c(?=[eiy])")
_HARD_C = re.compile(r"c")
_H_AFTER_VOWEL = re.compile(r"(?<=[aeiouyåäö])h")
_DOUBLED = re.compile(r"(.)\1+")


def _word_key(word: str) -> str:
    word = word.casefold().translate(_ACCENTS)
    word = _WORD_START.sub("j", word)
    word = _SJ_TJ.sub("X", word)
    word = _SOFT_K.sub("X", word)
    word = _SOFT_C.sub("s", word)
    word = _HARD_C.sub("k", word)
    word = word.replace("z", "s")
    word = word.replace("ph", "f").replace("q", "k").replace("w", "v").replace("x", "ks")
    word = _H_AFTER_VOWEL.sub("", word)
    return _DOUBLED.sub(r"\1", word)


def swedish_phonetic_key(text: str) -> str:
    """Return the Swedish phonetic key of `text`, or "" when it contains no letters.

    Keys are for comparison only and are never shown to the user or stored as names.
    """
    return "".join(_word_key(word) for word in _LETTER_RUN.findall(text))


def phonetic_match(query: str, name: str) -> bool:
    """True when `query` has the same phonetic key as the whole `name` or as one of its words."""
    wanted = swedish_phonetic_key(query)
    if not wanted:
        return False
    candidates = [name, *_LETTER_RUN.findall(name)]
    return any(swedish_phonetic_key(candidate) == wanted for candidate in candidates)
