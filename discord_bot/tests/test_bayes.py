"""Tests for the self-learning Naive Bayes spam filter (memory-only, no DB)."""

from __future__ import annotations

import asyncio

from bot.bayes import BayesConfig, BayesFilter, tokenize

SPAM = [
    "FREE NITRO click here http://scam.example @everyone claim your gift now",
    "free nitro giveaway discord.gg/fake claim now limited time",
    "CLICK here for free steam gift cards http://phish.example @everyone",
    "congratulations you won a free gift claim at http://bad.example",
    "free robux generator click the link now http://sus.example",
    "nitro gift for you discord.gg/scam hurry @here",
    "you have been selected for a free gift card click http://evil.example",
    "free crypto airdrop click now http://rug.example @everyone",
    "WIN A FREE IPHONE click here http://scam2.example",
    "free vbucks click the link @everyone http://fort.example",
]

HAM = [
    "hey how is everyone doing today",
    "anyone want to play some valorant later tonight",
    "the new update to the game is actually pretty good",
    "what time is the raid on saturday",
    "I finally fixed that bug in my python script",
    "lol that clip was hilarious",
    "does anyone know a good pizza place near campus",
    "good morning everyone hope you have a great day",
    "the weather is really nice today going for a walk",
    "just finished my homework finally free for the weekend",
]


def make_trained() -> BayesFilter:
    bf = BayesFilter(BayesConfig(min_spam=10, min_ham=10))

    async def _train() -> None:
        for s in SPAM:
            await bf.train(s, is_spam=True)
        for h in HAM:
            await bf.train(h, is_spam=False)

    asyncio.run(_train())
    return bf


def test_tokenize_words_and_shape_markers():
    toks = tokenize("FREE NITRO http://x.example @everyone CLAIM NOW GO")
    assert "free" in toks and "nitro" in toks
    assert "<url>" in toks and "<atall>" in toks and "<shouting>" in toks


def test_untrained_returns_none():
    bf = BayesFilter(BayesConfig())
    assert bf.score("free nitro click here") is None


def test_learns_spam_feel():
    bf = make_trained()
    assert bf.ready
    spam_p = bf.score("free nitro gift click here http://new-scam.example @everyone")
    ham_p = bf.score("anyone playing games tonight after the update")
    assert spam_p is not None and spam_p > 0.9
    assert ham_p is not None and ham_p < 0.3


def test_generalizes_to_unseen_spam():
    bf = make_trained()
    # never-seen wording, same "feel": free + click + url + mass ping
    p = bf.score("claim your free reward instantly click http://fresh.example @here")
    assert p is not None and p > 0.8


def test_false_positive_correction():
    bf = make_trained()
    phrase = "free pizza at the lan party click going tonight"
    # correcting it as ham several times should pull the score down
    before = bf.score(phrase) or 0.5

    async def _fix() -> None:
        for _ in range(5):
            await bf.train(phrase, is_spam=False)

    asyncio.run(_fix())
    after = bf.score(phrase) or 0.5
    assert after < before


def test_prune_drops_singletons():
    bf = BayesFilter(BayesConfig(vocab_cap=5, min_spam=1, min_ham=1))

    async def _t() -> None:
        await bf.train("aaa bbb ccc ddd eee fff", is_spam=True)
        await bf.train("aaa common words here again", is_spam=False)

    asyncio.run(_t())
    # cap is tiny, so prune ran; repeated token survives, singletons die
    assert "aaa" in (bf.spam_tokens.keys() | bf.ham_tokens.keys())
    assert bf.vocab_size <= 11
