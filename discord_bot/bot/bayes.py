"""Self-learning spam filter — the old email trick, pointed at Discord.

Naive Bayes over message tokens (Graham/Robinson style), trained continuously
by the moderation pipeline's own *verified* outcomes. Over time it learns what
spam "feels like" on this particular server — and because a lookup costs
microseconds, it runs happily on a Pi 1 and slots in *before* the LLM: the
more it learns, the fewer LLM calls you pay for.

Feedback-loop safety: the filter never trains on its own catches. Teachers are
  * LLM-confirmed harmful verdicts
  * owner-approved DM actions (and denials train the other way — false
    positives correct themselves)
  * deterministic profanity/scam hits
  * manual ``!mod trainspam`` / ``trainham``
plus a light random sample of untouched messages as ham so the corpus stays
balanced.

Persistence is a token-count table in SQLite; the whole vocabulary is held in
memory (capped and pruned) so classification is pure dict math.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

WORD_RE = re.compile(r"[a-z0-9']{2,}")
URL_RE = re.compile(r"https?://|discord\.gg/", re.IGNORECASE)
MENTION_RE = re.compile(r"<@[!&]?\d+>")
INVITE_RE = re.compile(r"discord\.(gg|com/invite)", re.IGNORECASE)

# combine at most this many most-interesting tokens (Graham's trick: extremes
# carry the signal, the mushy middle is noise)
MAX_INTERESTING = 20


def tokenize(text: str) -> set[str]:
    """Words plus a few 'shape' markers so the filter can learn a *feel*
    (screaming, link-with-pings, wall-of-text) and not just vocabulary."""
    toks = set(WORD_RE.findall(text.lower()))
    if URL_RE.search(text):
        toks.add("<url>")
    if INVITE_RE.search(text):
        toks.add("<invite>")
    n_mentions = len(MENTION_RE.findall(text))
    if n_mentions >= 3:
        toks.add("<manymentions>")
    if "@everyone" in text or "@here" in text:
        toks.add("<atall>")
    # judge shouting on the prose only — lowercase URLs shouldn't dilute it
    prose = re.sub(r"https?://\S+", "", text)
    letters = [c for c in prose if c.isalpha()]
    if len(letters) >= 8 and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        toks.add("<shouting>")
    if len(text) > 400:
        toks.add("<wall>")
    return toks


@dataclass
class BayesConfig:
    enabled: bool = True
    # act (delete) at/above this learned-spam probability
    spam_threshold: float = 0.92
    # at/above this, force an LLM escalation even if shape suspicion is low
    escalate_threshold: float = 0.7
    # don't classify until it has seen at least this many of each class
    min_spam: int = 10
    min_ham: int = 10
    # probability of sampling an untouched message as ham (keeps corpus balanced)
    auto_ham_rate: float = 0.02
    # vocabulary cap — singletons get pruned past this (RAM is precious)
    vocab_cap: int = 30000


class BayesFilter:
    def __init__(self, cfg: BayesConfig, db=None) -> None:
        self.cfg = cfg
        self.db = db  # None = memory-only (tests)
        self.spam_tokens: dict[str, int] = {}
        self.ham_tokens: dict[str, int] = {}
        self.spam_msgs = 0
        self.ham_msgs = 0
        # metrics
        self.catches = 0
        self.trainings = 0

    # -- persistence -------------------------------------------------------- #
    async def load(self) -> None:
        if self.db is None:
            return
        for row in await self.db.fetchall("SELECT token, spam, ham FROM bayes_tokens"):
            if row["spam"]:
                self.spam_tokens[row["token"]] = row["spam"]
            if row["ham"]:
                self.ham_tokens[row["token"]] = row["ham"]
        for row in await self.db.fetchall("SELECT key, value FROM bayes_meta"):
            if row["key"] == "spam_msgs":
                self.spam_msgs = row["value"]
            elif row["key"] == "ham_msgs":
                self.ham_msgs = row["value"]

    @property
    def ready(self) -> bool:
        return self.spam_msgs >= self.cfg.min_spam and self.ham_msgs >= self.cfg.min_ham

    @property
    def vocab_size(self) -> int:
        return len(self.spam_tokens.keys() | self.ham_tokens.keys())

    # -- classify ------------------------------------------------------------ #
    def score(self, text: str) -> float | None:
        """P(spam) in [0,1], or None if untrained / no evidence."""
        if not self.cfg.enabled or not self.ready or not text:
            return None
        probs: list[float] = []
        for tok in tokenize(text):
            sc = self.spam_tokens.get(tok, 0)
            hc = self.ham_tokens.get(tok, 0)
            n = sc + hc
            if n == 0:
                continue
            ps = sc / self.spam_msgs
            ph = hc / self.ham_msgs
            p = ps / (ps + ph) if (ps + ph) > 0 else 0.5
            # Robinson's correction: shrink rare tokens toward 0.5 so one
            # coincidence can't dominate
            p = (0.5 + n * p) / (1 + n)
            probs.append(min(0.99, max(0.01, p)))
        if not probs:
            return None
        probs.sort(key=lambda x: abs(x - 0.5), reverse=True)
        probs = probs[:MAX_INTERESTING]
        log_s = sum(math.log(p) for p in probs)
        log_h = sum(math.log(1.0 - p) for p in probs)
        m = max(log_s, log_h)
        es, eh = math.exp(log_s - m), math.exp(log_h - m)
        return es / (es + eh)

    # -- learn ---------------------------------------------------------------- #
    async def train(self, text: str, is_spam: bool) -> None:
        toks = tokenize(text)
        if not toks:
            return
        target = self.spam_tokens if is_spam else self.ham_tokens
        for t in toks:
            target[t] = target.get(t, 0) + 1
        if is_spam:
            self.spam_msgs += 1
        else:
            self.ham_msgs += 1
        self.trainings += 1

        if self.db is not None:
            rows = [(t, 1 if is_spam else 0, 0 if is_spam else 1) for t in toks]
            await self.db.executemany(
                "INSERT INTO bayes_tokens (token, spam, ham) VALUES (?, ?, ?) "
                "ON CONFLICT(token) DO UPDATE SET "
                "spam = spam + excluded.spam, ham = ham + excluded.ham",
                rows,
            )
            key = "spam_msgs" if is_spam else "ham_msgs"
            await self.db.execute(
                "INSERT INTO bayes_meta (key, value) VALUES (?, 1) "
                "ON CONFLICT(key) DO UPDATE SET value = value + 1",
                (key,),
            )
        if self.vocab_size > self.cfg.vocab_cap:
            await self._prune()

    async def _prune(self) -> None:
        """Drop singleton tokens — they're noise and they're most of the RAM."""
        for d in (self.spam_tokens, self.ham_tokens):
            other = self.ham_tokens if d is self.spam_tokens else self.spam_tokens
            for tok in [t for t, c in d.items() if c <= 1 and other.get(t, 0) == 0]:
                del d[tok]
        if self.db is not None:
            await self.db.execute("DELETE FROM bayes_tokens WHERE spam + ham <= 1")

    def top_spam_tokens(self, n: int = 10) -> list[tuple[str, int]]:
        return sorted(self.spam_tokens.items(), key=lambda kv: kv[1], reverse=True)[:n]
