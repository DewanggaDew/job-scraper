from __future__ import annotations

import os
from typing import List, Optional

import numpy as np
from sentence_transformers import SentenceTransformer
from sklearn.metrics.pairwise import cosine_similarity

# ─── Model config ─────────────────────────────────────────────────────────────
# all-MiniLM-L6-v2:
#   • ~80 MB download (cached after first run)
#   • Fast inference — ideal for GitHub Actions
#   • Strong semantic understanding of tech / job-description text
#   • Understands that "React developer" ≈ "Frontend engineer with React experience"

MODEL_NAME = "all-MiniLM-L6-v2"

# Honour a custom cache dir so GitHub Actions can cache the model between runs
# (set via env var SENTENCE_TRANSFORMERS_HOME pointing to a cached directory)
_CACHE_DIR: Optional[str] = os.environ.get("SENTENCE_TRANSFORMERS_HOME")

# Module-level singleton — loaded once per process
_model: Optional[SentenceTransformer] = None


# ─── Model loading ────────────────────────────────────────────────────────────


def get_model() -> SentenceTransformer:
    """
    Return the shared SentenceTransformer model, loading it on first call.

    The model is intentionally kept as a module-level singleton to avoid
    reloading it for every job scored in a single scrape run.
    """
    global _model
    if _model is None:
        print(f"📦  Loading embedding model: {MODEL_NAME} …")
        _model = SentenceTransformer(MODEL_NAME, cache_folder=_CACHE_DIR)
        print("✅  Embedding model loaded.")
    return _model


# ─── Core similarity helpers ─────────────────────────────────────────────────


def embed(texts: List[str]) -> np.ndarray:
    """
    Return an (N, D) array of L2-normalised sentence embeddings.

    Args:
        texts: List of strings to embed.  Empty strings are replaced with
               a single space so the model always receives valid input.

    Returns:
        numpy float32 array of shape (len(texts), embedding_dim).
    """
    safe_texts = [t if t and t.strip() else " " for t in texts]
    model = get_model()
    return model.encode(safe_texts, convert_to_numpy=True, normalize_embeddings=True)


def compute_similarity(text_a: str, text_b: str) -> float:
    """
    Compute semantic cosine similarity between two free-form texts.

    Returns a float in [0.0, 1.0] where 1.0 means identical meaning.

    Examples
    --------
    compute_similarity("React developer", "Frontend engineer with React experience")
    → ~0.82

    compute_similarity("Product Manager", "Software Engineer")
    → ~0.41
    """
    if not text_a or not text_b:
        return 0.0

    embeddings = embed([text_a, text_b])  # shape (2, D)
    score = float(cosine_similarity([embeddings[0]], [embeddings[1]])[0][0])
    # Clamp to [0, 1] — cosine can return tiny negatives due to float precision
    return max(0.0, min(1.0, score))


def compute_skills_similarity(cv_skills: List[str], job_skills: List[str]) -> float:
    """
    Compare a CV's skill set against a job's required skills using embeddings.

    Strategy: encode both lists as a single comma-joined string so the model
    captures the *combination* of skills rather than scoring each pair
    independently (which would miss complementary / synonym relationships).

    Args:
        cv_skills:  Skills extracted from the candidate's CV.
        job_skills: Skills extracted from the job description.

    Returns:
        Similarity score in [0.0, 1.0].
    """
    if not cv_skills or not job_skills:
        return 0.0

    cv_text = ", ".join(cv_skills)
    job_text = ", ".join(job_skills)
    return compute_similarity(cv_text, job_text)


def compute_bulk_similarity(
    reference_text: str,
    candidate_texts: List[str],
) -> List[float]:
    """
    Efficiently compute cosine similarity between one reference text and many
    candidate texts in a single batch encoding call.

    Useful for comparing a job description against multiple CV sections at once.

    Args:
        reference_text:   The anchor text (e.g. joined job skills).
        candidate_texts:  List of texts to compare against the reference.

    Returns:
        List of float similarity scores, one per candidate text.
    """
    if not reference_text or not candidate_texts:
        return [0.0] * len(candidate_texts)

    all_texts = [reference_text] + candidate_texts
    embeddings = embed(all_texts)  # (1 + N, D)
    ref_emb = embeddings[0:1]  # (1, D)
    cand_embs = embeddings[1:]  # (N, D)

    scores = cosine_similarity(ref_emb, cand_embs)[0]  # (N,)
    return [max(0.0, min(1.0, float(s))) for s in scores]


def title_similarity(job_title: str, preferred_titles: List[str]) -> float:
    """
    Return the *best* similarity score between a job title and a list of
    the candidate's preferred titles.

    Uses bulk embedding for efficiency when many preferred titles are given.

    Args:
        job_title:        Title of the scraped job posting.
        preferred_titles: Titles from the CV / config (e.g. "Software Engineer").

    Returns:
        Best match similarity in [0.0, 1.0].
    """
    if not job_title or not preferred_titles:
        return 0.0

    scores = compute_bulk_similarity(job_title, preferred_titles)
    return max(scores) if scores else 0.0
