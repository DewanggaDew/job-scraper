from __future__ import annotations

import os
from typing import Dict, List, Optional

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

# ─── Model config ─────────────────────────────────────────────────────────────

MODEL_NAME = "all-MiniLM-L6-v2"
_CACHE_DIR: Optional[str] = os.environ.get("SENTENCE_TRANSFORMERS_HOME")
_model: Optional[SentenceTransformer] = None


# ─── Model loading ────────────────────────────────────────────────────────────


def get_model() -> SentenceTransformer:
    """Return the shared SentenceTransformer model, loading it on first call."""
    global _model
    if _model is None:
        print(f"📦  Loading embedding model: {MODEL_NAME} …")
        _model = SentenceTransformer(MODEL_NAME, cache_folder=_CACHE_DIR)
        print("✅  Embedding model loaded.")
    return _model


# ─── Core similarity helpers ─────────────────────────────────────────────────


def embed(texts: List[str]) -> np.ndarray:
    """Return an (N, D) array of L2-normalised sentence embeddings."""
    safe_texts = [t if t and t.strip() else " " for t in texts]
    model = get_model()
    return model.encode(safe_texts, convert_to_numpy=True, normalize_embeddings=True)


def compute_similarity(text_a: str, text_b: str) -> float:
    """Compute semantic cosine similarity between two free-form texts."""
    if not text_a or not text_b:
        return 0.0

    embeddings = embed([text_a, text_b])
    score = float(cosine_similarity([embeddings[0]], [embeddings[1]])[0][0])
    return max(0.0, min(1.0, score))


def compute_skills_similarity(cv_skills: List[str], job_skills: List[str]) -> float:
    """Compare a CV's skill set against a job's required skills using embeddings."""
    if not cv_skills or not job_skills:
        return 0.0

    cv_text = ", ".join(cv_skills)
    job_text = ", ".join(job_skills)
    return compute_similarity(cv_text, job_text)


def compute_bulk_similarity(
    reference_text: str,
    candidate_texts: List[str],
) -> List[float]:
    """Compute cosine similarity between one reference text and many candidates."""
    if not reference_text or not candidate_texts:
        return [0.0] * len(candidate_texts)

    all_texts = [reference_text] + candidate_texts
    embeddings = embed(all_texts)
    ref_emb = embeddings[0:1]
    cand_embs = embeddings[1:]

    scores = cosine_similarity(ref_emb, cand_embs)[0]
    return [max(0.0, min(1.0, float(s))) for s in scores]


def title_similarity(job_title: str, preferred_titles: List[str]) -> float:
    """Return the best similarity score between a job title and preferred titles."""
    if not job_title or not preferred_titles:
        return 0.0

    scores = compute_bulk_similarity(job_title, preferred_titles)
    return max(scores) if scores else 0.0


# ─── Batch Embedding Cache ────────────────────────────────────────────────────


class EmbeddingCache:
    """
    Pre-computes embeddings for all texts in a single model.encode() call,
    then serves lookups by text key. Replaces hundreds of individual encode()
    calls with one batched call.
    """

    def __init__(self) -> None:
        self._vectors: Dict[str, np.ndarray] = {}

    @property
    def size(self) -> int:
        return len(self._vectors)

    def warm(self, texts: List[str], batch_size: int = 128) -> None:
        """
        Encode all *texts* that are not already cached in a single batch.
        Duplicate / empty strings are handled gracefully.
        """
        new_texts = []
        for t in texts:
            key = t if t and t.strip() else " "
            if key not in self._vectors:
                new_texts.append(key)

        if not new_texts:
            return

        unique_texts = list(dict.fromkeys(new_texts))
        print(f"  📦  Batch-encoding {len(unique_texts)} unique texts …")
        vecs = embed(unique_texts)  # (N, D) — uses the singleton model
        for text, vec in zip(unique_texts, vecs):
            self._vectors[text] = vec

    def get(self, text: str) -> Optional[np.ndarray]:
        key = text if text and text.strip() else " "
        return self._vectors.get(key)

    def cosine(self, text_a: str, text_b: str) -> float:
        """Look up pre-computed vectors and return cosine similarity."""
        va = self.get(text_a)
        vb = self.get(text_b)
        if va is None or vb is None:
            return 0.0
        score = float(cosine_similarity([va], [vb])[0][0])
        return max(0.0, min(1.0, score))

    def best_cosine(self, text: str, candidates: List[str]) -> float:
        """Return the highest cosine similarity between text and any candidate."""
        v = self.get(text)
        if v is None or not candidates:
            return 0.0
        cand_vecs = [self.get(c) for c in candidates]
        valid = [cv for cv in cand_vecs if cv is not None]
        if not valid:
            return 0.0
        scores = cosine_similarity([v], np.array(valid))[0]
        return max(0.0, min(1.0, float(scores.max())))
