"""Search text normalisation and query words (WP-027, ADR-029). Pure Python, no I/O.

The same normalisation runs in the database as `sx_search_normalize(text)` (migration 0020), on
the stored text when it is indexed; this module applies it to what people type. A database test
checks the two agree on a corpus of English, Arabic and Urdu text.

What it does, in order:
1. Unicode NFKD: letters with hamza or madda split into the bare letter and a
   mark (alef with hamza becomes alef plus hamza),
   Arabic presentation forms become the letters they show, accented Latin letters split too;
2. drop the marks people leave out when typing: Arabic and Urdu diacritics (harakat, tanween,
   shadda, sukun, superscript alef, Quranic marks), Latin accents, tatweel and zero-width joiners;
3. lower case;
4. one letter for the letters people mix up: alef wasla → alef; alef maksura, Farsi/Urdu yeh and
   yeh barree → yeh; keheh → kaf; heh goal, heh doachashmee, ae and teh marbuta → heh;
   Arabic-Indic and Eastern (Urdu) digits → 0-9.

So "أحْمد", "احمد" and "إحمد" are one word, and "کمپیوٹر" typed with Arabic kaf and yeh finds the
Urdu spelling. Word forms are matched later: Arabic and English by PostgreSQL's stemmers, Urdu
(no stemmer exists, in PostgreSQL or OpenSearch) by word prefix.
"""

import re
import unicodedata

# Marks removed after NFKD. The same ranges are in the database function (migration 0020).
MARKS = (
    "\u0300-\u036f"  # combining diacritical marks (Latin accents after NFKD)
    "\u0610-\u061a"  # Arabic signs above and below
    "\u064b-\u065f"  # harakat, tanween, shadda, sukun, hamza above/below, ...
    "\u0670"  # superscript alef
    "\u06d6-\u06ed"  # Quranic annotation marks
    "\u0640"  # tatweel (kashida)
    "\u200b-\u200f"  # zero-width space, non-joiner, joiner, LRM, RLM
)
_MARKS = re.compile(f"[{MARKS}]")

# from → to, one character each. The same two strings are in the database function.
LETTERS_FROM = (
    "\u0671"  # alef wasla
    "\u0649\u06cc\u06d2"  # alef maksura, Farsi yeh (Urdu choti ye), yeh barree (bari ye)
    "\u06a9\u06aa"  # keheh (Urdu kaf), swash kaf
    "\u06c1\u06be\u06d5\u0629\u06c3"  # heh goal, heh doachashmee, ae, teh marbuta, teh marbuta goal
    "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"  # Arabic-Indic digits
    "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9"  # Eastern (Urdu) digits
)
LETTERS_TO = (
    "\u0627\u064a\u064a\u064a\u0643\u0643\u0647\u0647\u0647\u0647\u064701234567890123456789"
)
_LETTERS = str.maketrans(LETTERS_FROM, LETTERS_TO)

# What people type is cut to this many words, each to this many characters.
MAX_WORDS = 8
MAX_WORD_LENGTH = 50
MAX_QUERY_LENGTH = 200
_WORD = re.compile(r"[^\W_]+")


def normalize(text: str) -> str:
    """Search form of `text` (see the module docstring)."""
    decomposed = unicodedata.normalize("NFKD", text)
    return _MARKS.sub("", decomposed).lower().translate(_LETTERS)


def words(query: str) -> list[str]:
    """The distinct words of a typed query, normalised, in order (at most MAX_WORDS)."""
    found: list[str] = []
    for word in _WORD.findall(normalize(query[:MAX_QUERY_LENGTH])):
        cut = word[:MAX_WORD_LENGTH]
        if cut not in found:
            found.append(cut)
        if len(found) == MAX_WORDS:
            break
    return found
