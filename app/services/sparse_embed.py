"""BM25-like sparse embedding using Qdrant's fastembed SparseTextEmbedding.

Provides a cached singleton sparse embedder and batch encoding utility
for hybrid search support.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import List

from qdrant_client.http.models import SparseVector

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def get_sparse_embedder():
    """Return a cached singleton sparse text embedding model."""
    from fastembed import SparseTextEmbedding

    logger.info("Loading sparse embedding model (Qdrant/bm25)")
    return SparseTextEmbedding(model_name="Qdrant/bm25")


def compute_sparse_vectors(texts: List[str]) -> List[SparseVector]:
    """Batch encode texts into sparse vectors for Qdrant.

    Args:
        texts: List of text strings to encode.

    Returns:
        List of SparseVector objects with indices and values.
    """
    embedder = get_sparse_embedder()
    results: List[SparseVector] = []
    for embedding in embedder.embed(texts):
        results.append(
            SparseVector(
                indices=embedding.indices.tolist(),
                values=embedding.values.tolist(),
            )
        )
    return results
