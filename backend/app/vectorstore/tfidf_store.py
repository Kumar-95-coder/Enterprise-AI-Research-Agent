"""
TfidfVectorStore: the EMBEDDING_MODEL=tfidf backend.

A real, working semantic-search index using scikit-learn TF-IDF vectors and
cosine similarity. No model weights to download, no GPU, no external
service -- fully local and deterministic, which is why it's what actually
runs in this sandbox (no route to huggingface.co or any embedding API).

Swap-in path: EMBEDDING_MODEL=sentence-transformers (or an API embedding
model) for real dense semantic vectors with better recall on paraphrase --
see docs/architecture.md. The interface (`fit`, `search`) is unchanged, so
swapping only touches this file plus the two call sites that instantiate it.
"""
from typing import List, Tuple
import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


class TfidfVectorStore:
    def __init__(self, min_df: int = 1):
        self.vectorizer = TfidfVectorizer(stop_words="english", max_features=8000, min_df=min_df)
        self.ids: List[str] = []
        self.texts: List[str] = []
        self.matrix = None
        self.fitted = False

    def fit(self, id_text_pairs: List[Tuple[str, str]]):
        pairs = [(i, t) for i, t in id_text_pairs if t and t.strip()]
        self.ids = [i for i, _ in pairs]
        self.texts = [t for _, t in pairs]
        if len(self.texts) >= 1:
            try:
                self.matrix = self.vectorizer.fit_transform(self.texts)
                self.fitted = True
            except ValueError:
                # e.g. vocabulary is empty after stop-word removal on tiny input
                self.fitted = False
        return self

    def search(self, query: str, k: int = 5, min_similarity: float = 0.0) -> List[Tuple[str, float]]:
        if not self.fitted or not self.texts:
            return []
        qv = self.vectorizer.transform([query])
        sims = cosine_similarity(qv, self.matrix)[0]
        order = np.argsort(-sims)[:k]
        return [(self.ids[i], float(sims[i])) for i in order if sims[i] >= min_similarity]

    def pairwise_similarity(self, text_a: str, text_b: str) -> float:
        """Standalone similarity between two arbitrary strings (used for
        claim clustering / contradiction candidate detection), independent
        of whatever corpus is currently `fit`."""
        try:
            local = TfidfVectorizer(stop_words="english").fit([text_a, text_b])
            v = local.transform([text_a, text_b])
            return float(cosine_similarity(v[0], v[1])[0][0])
        except ValueError:
            return 0.0
