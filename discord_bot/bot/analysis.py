"""Deterministic text analysis: message "shapes", profanity, escalation.

This is the brain that decides *cheaply* whether a message is obviously fine,
obviously bad, or ambiguous-and-worth-asking-the-LLM. The whole point on a Pi
is to answer as many messages as possible here, for free, and only spend an
LLM inference on the genuinely uncertain middle.

Design:
  * Pure-Python/regex feature extraction always works (no deps).
  * If NLTK is installed *and* enabled, we add VADER sentiment as one more
    feature. Everything still works without it.
  * ``analyze()`` returns a :class:`Shape` with a normalized ``suspicion``
    score in [0, 1] plus the raw features, so a cog can decide what to do.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

# --------------------------------------------------------------------------- #
# Regexes (compiled once)                                                      #
# --------------------------------------------------------------------------- #
URL_RE = re.compile(r"https?://\S+|discord\.gg/\S+", re.IGNORECASE)
MENTION_RE = re.compile(r"<@[!&]?\d+>")
CUSTOM_EMOJI_RE = re.compile(r"<a?:\w+:\d+>")
WORD_RE = re.compile(r"\w+", re.UNICODE)
REPEAT_RUN_RE = re.compile(r"(.)\1{4,}")  # 5+ of the same char in a row

# Unicode ranges that cover the common standalone emoji blocks.
_EMOJI_RANGES = (
    (0x1F300, 0x1FAFF),
    (0x2600, 0x27BF),
    (0x1F000, 0x1F0FF),
)

# Leetspeak / obfuscation normalization map.
_LEET = str.maketrans(
    {
        "0": "o", "1": "i", "3": "e", "4": "a", "5": "s", "7": "t",
        "8": "b", "9": "g", "@": "a", "$": "s", "!": "i", "|": "i",
    }
)

# A deliberately small built-in seed list. Real deployments should supply their
# own via BOT_PROFANITY_WORDLIST — moderation wordlists are community-specific.
# Kept minimal on purpose; these are matched after leet-normalization.
_DEFAULT_PROFANITY = {
    "fuck", "shit", "bitch", "asshole", "bastard", "dick", "cunt",
    "slut", "whore", "faggot", "nigger", "retard", "twat", "wanker",
}


def _emoji_count(text: str) -> int:
    count = 0
    for ch in text:
        cp = ord(ch)
        for lo, hi in _EMOJI_RANGES:
            if lo <= cp <= hi:
                count += 1
                break
    return count


def _shannon_entropy(text: str) -> float:
    if not text:
        return 0.0
    freq: dict[str, int] = {}
    for ch in text:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(text)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def normalize_leet(text: str) -> str:
    """Fold obfuscation so ``f.u.c.k`` / ``fu*ck`` / ``f4ck`` collapse together."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))  # strip zalgo
    text = text.lower().translate(_LEET)
    # remove separators commonly used to dodge filters
    text = re.sub(r"[\s\.\-_*~`'\"]+", "", text)
    return text


@dataclass
class Shape:
    length: int = 0
    words: int = 0
    caps_ratio: float = 0.0
    punct_ratio: float = 0.0
    digit_ratio: float = 0.0
    url_count: int = 0
    mention_count: int = 0
    emoji_count: int = 0
    max_repeat_run: int = 0
    entropy: float = 0.0
    unique_word_ratio: float = 0.0
    sentiment: float | None = None  # VADER compound, if NLTK enabled
    profanity_hits: list[str] = field(default_factory=list)
    suspicion: float = 0.0

    @property
    def has_profanity(self) -> bool:
        return bool(self.profanity_hits)


class TextAnalyzer:
    def __init__(self, enable_nltk: bool = False, wordlist_path: str = "") -> None:
        self.profanity = set(_DEFAULT_PROFANITY)
        if wordlist_path:
            self._load_wordlist(wordlist_path)
        # pre-normalize the wordlist for matching against normalized text
        self._norm_profanity = {normalize_leet(w) for w in self.profanity if w}
        self._sia = None
        if enable_nltk:
            self._sia = self._try_load_vader()

    # -- setup helpers ----------------------------------------------------- #
    def _load_wordlist(self, path: str) -> None:
        p = Path(path)
        if not p.exists():
            return
        for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            word = line.strip().lower()
            if word and not word.startswith("#"):
                self.profanity.add(word)

    @staticmethod
    def _try_load_vader():
        """Load VADER lazily; return None if NLTK/data unavailable."""
        try:
            import nltk
            from nltk.sentiment import SentimentIntensityAnalyzer

            try:
                return SentimentIntensityAnalyzer()
            except LookupError:
                nltk.download("vader_lexicon", quiet=True)
                return SentimentIntensityAnalyzer()
        except Exception:
            return None

    @property
    def nltk_active(self) -> bool:
        return self._sia is not None

    # -- profanity --------------------------------------------------------- #
    def find_profanity(self, text: str) -> list[str]:
        norm = normalize_leet(text)
        found: list[str] = []
        for raw in self.profanity:
            nw = normalize_leet(raw)
            if nw and nw in norm:
                found.append(raw)
        return found

    # -- main -------------------------------------------------------------- #
    def analyze(self, text: str) -> Shape:
        s = Shape(length=len(text))
        if not text:
            return s

        letters = [c for c in text if c.isalpha()]
        s.caps_ratio = (sum(c.isupper() for c in letters) / len(letters)) if letters else 0.0
        s.punct_ratio = sum(not c.isalnum() and not c.isspace() for c in text) / len(text)
        s.digit_ratio = sum(c.isdigit() for c in text) / len(text)
        s.url_count = len(URL_RE.findall(text))
        s.mention_count = len(MENTION_RE.findall(text))
        s.emoji_count = _emoji_count(text) + len(CUSTOM_EMOJI_RE.findall(text))
        run = REPEAT_RUN_RE.search(text)
        s.max_repeat_run = len(run.group(0)) if run else 0
        s.entropy = _shannon_entropy(text)

        words = WORD_RE.findall(text.lower())
        s.words = len(words)
        s.unique_word_ratio = (len(set(words)) / len(words)) if words else 0.0

        if self._sia is not None:
            try:
                s.sentiment = self._sia.polarity_scores(text)["compound"]
            except Exception:
                s.sentiment = None

        s.profanity_hits = self.find_profanity(text)
        s.suspicion = self._suspicion(s)
        return s

    @staticmethod
    def _suspicion(s: Shape) -> float:
        """Blend features into a single [0, 1] "worth a closer look" score.

        This is heuristic and tunable — it is NOT a verdict. Its only job is to
        decide whether to bother the LLM. Deliberately conservative so the vast
        majority of normal chatter scores near zero.
        """
        score = 0.0
        # obfuscated near-profanity: normalization already caught exact hits, so
        # any residual profanity here is a strong signal.
        if s.profanity_hits:
            score += 0.5
        # shouting
        if s.length >= 8 and s.caps_ratio > 0.7:
            score += 0.2
        # symbol soup / obfuscation attempts
        if s.punct_ratio > 0.4:
            score += 0.15
        # keysmash / repeated-char flooding
        if s.max_repeat_run >= 8:
            score += 0.15
        # low information but long (copy-paste spam)
        if s.length > 40 and s.unique_word_ratio < 0.35:
            score += 0.2
        # link + mention combo (classic raid/scam shape)
        if s.url_count and s.mention_count >= 3:
            score += 0.25
        # strongly negative sentiment (if VADER is on)
        if s.sentiment is not None and s.sentiment <= -0.6:
            score += 0.2
        return max(0.0, min(1.0, score))
