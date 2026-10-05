"""Knowledge-base retrieval over the clinic's own articles (clinic/kb/*.md).

Each article has a front-matter header (title, topics) and the same content in Arabic and
English ([ar] / [en] blocks). Search is TF-IDF over *character* n-grams of normalised text:
it copes with dialect spelling (ابي / أبي, عياده / عيادة), typos and mixed Arabic-English
messages far better than word n-grams, and needs no model download.

The best score is also the bot's "do I actually know this?" signal: below
config.ANSWER_THRESHOLD the agent hands off to a human instead of guessing.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

from clinic import config
from clinic.text import normalize


@dataclass(frozen=True)
class Article:
    slug: str
    title: str
    topics: tuple[str, ...]
    ar: str = field(repr=False)
    en: str = field(repr=False)

    def text(self, lang: str) -> str:
        return self.ar if lang == "ar" else self.en


def _parse(path: Path) -> Article:
    text = path.read_text(encoding="utf-8")
    _, header, body = text.split("---", 2)
    meta = dict(line.split(":", 1) for line in header.strip().splitlines())
    topics = tuple(t.strip() for t in meta["topics"].split(",") if t.strip())
    ar, en = body.split("[en]", 1)
    return Article(path.stem, meta["title"].strip(), topics, ar.replace("[ar]", "").strip(), en.strip())


@lru_cache(maxsize=1)
def load_articles(kb_dir: Path = config.KB_DIR) -> tuple[Article, ...]:
    return tuple(_parse(p) for p in sorted(kb_dir.glob("*.md")))


_PREFIXES = ("وال", "بال", "لل", "ال", "و", "ب")
_STOPWORDS = {normalize(w) for w in (
    "عندكم في من الى إلى على عن هل شنو شو كم متى وين ابي ابغى اللي هذا هذي انا انتم يوم فيه "
    "what how do does you is are the a an of to for your and in i my me can").split()}


def word_tokens(text: str) -> list[str]:
    """Content words with the glued Arabic prefix removed: 'بالليزر' → 'ليزر'."""
    out = []
    for word in re.findall(r"\w+", normalize(text)):
        if word in _STOPWORDS:
            continue
        for prefix in _PREFIXES:
            if word.startswith(prefix) and len(word) - len(prefix) >= 3:
                word = word[len(prefix):]
                break
        out.append(word)
    return out


class Retriever:
    """Score = mean of two cosine similarities:
    - character n-grams: robust to spelling variants and typos
    - content words: an unrelated message ("do you sell perfume?") shares no words with the
      knowledge base and scores ~0, which makes the "do I know this?" threshold much sharper."""

    def __init__(self, articles: tuple[Article, ...] | None = None):
        self.articles = articles or load_articles()
        # title and topics are repeated so they weigh more than the body
        docs = [normalize(" ".join([a.title, *a.topics] * 2 + [a.ar, a.en])) for a in self.articles]
        self.chars = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 4), sublinear_tf=True)
        self.words = TfidfVectorizer(analyzer=word_tokens, sublinear_tf=True)
        self.char_matrix = self.chars.fit_transform(docs)
        self.word_matrix = self.words.fit_transform(docs)

    def search(self, query: str, k: int = 2) -> list[tuple[Article, float]]:
        char_scores = (self.char_matrix @ self.chars.transform([normalize(query)]).T).toarray().ravel()
        word_scores = (self.word_matrix @ self.words.transform([query]).T).toarray().ravel()
        scores = (char_scores + word_scores) / 2
        top = np.argsort(-scores)[:k]
        return [(self.articles[i], float(scores[i])) for i in top]
