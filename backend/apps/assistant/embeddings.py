"""Text embeddings behind a small interface.

HashingEmbedder is deterministic and offline: unigrams and bigrams are hashed into a
fixed-size signed vector and L2-normalized, so cosine similarity measures lexical
overlap. It keeps CI and the mock eval free of model downloads and API keys. A
semantic embedding model can replace it by implementing `embed` with the same
dimension (or by migrating the vector column).
"""

import hashlib
import math
import re

from .models import EMBEDDING_DIM

STOPWORDS = frozenset(
    "a an and are as at be by can could do does for from have how i if in is it its me my "
    "of on or our so that the their there this to was we what when where which will with "
    "would you your yours i'm im it's there's".split()
)
TOKEN = re.compile(r"[a-z0-9]+")


def normalize_token(tok: str) -> str:
    # Light stemming so "pets"/"pet" and "fees"/"fee" share a feature.
    if len(tok) > 4 and tok.endswith("ies"):
        return tok[:-3] + "y"
    if len(tok) > 3 and tok.endswith("s") and not tok.endswith("ss"):
        return tok[:-1]
    return tok


def tokens(text: str) -> list[str]:
    return [normalize_token(t) for t in TOKEN.findall(text.lower()) if t not in STOPWORDS]


class HashingEmbedder:
    name = "hashing-v1"

    def __init__(self, dim: int = EMBEDDING_DIM):
        self.dim = dim

    def _bucket(self, feature: str) -> tuple[int, float]:
        digest = hashlib.blake2b(feature.encode(), digest_size=8).digest()
        value = int.from_bytes(digest, "big")
        return value % self.dim, 1.0 if (value >> 63) & 1 else -1.0

    def embed(self, text: str) -> list[float]:
        toks = tokens(text)
        vec = [0.0] * self.dim
        features = toks + [f"{a}_{b}" for a, b in zip(toks, toks[1:], strict=False)]
        for feature in features:
            idx, sign = self._bucket(feature)
            vec[idx] += sign
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        return [v / norm for v in vec]


def get_embedder() -> HashingEmbedder:
    return HashingEmbedder()
