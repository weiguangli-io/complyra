"""Qdrant vector database integration.

Provides collection management, document upsert, and tenant-scoped
similarity search against a Qdrant instance. Supports hybrid search
(dense + BM25 sparse vectors with RRF fusion) when enabled.
"""

import logging
import uuid
from functools import lru_cache
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from langsmith import traceable

from app.core.config import settings
from app.services.embeddings import embed_texts, get_embedder


@lru_cache(maxsize=1)
def get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=settings.qdrant_url)


def _collection_has_sparse_vectors() -> bool:
    """Check if the existing collection has sparse vector config."""
    try:
        client = get_qdrant_client()
        info = client.get_collection(settings.qdrant_collection)
        sparse_config = info.config.params.sparse_vectors
        return sparse_config is not None and "sparse" in sparse_config
    except Exception:
        return False


def _collection_has_named_vectors() -> bool:
    """Check if the existing collection uses named vectors (dict config)."""
    try:
        client = get_qdrant_client()
        info = client.get_collection(settings.qdrant_collection)
        vectors = info.config.params.vectors
        return isinstance(vectors, dict)
    except Exception:
        return False


def ensure_collection() -> None:
    """Create the Qdrant collection if it does not exist.

    When hybrid_search_enabled, creates collection with both dense (named)
    and sparse vector configs. Otherwise, creates with flat dense vectors only.

    Logs a warning if the existing collection has a different vector dimension
    than the current embedding provider.
    """
    client = get_qdrant_client()
    embedder = get_embedder()
    dim = embedder.get_dimension()

    if client.collection_exists(settings.qdrant_collection):
        info = client.get_collection(settings.qdrant_collection)
        vectors = info.config.params.vectors
        # Handle both named vectors (dict) and flat VectorParams
        if isinstance(vectors, dict):
            existing_dim = vectors.get("dense", qmodels.VectorParams(size=0, distance=qmodels.Distance.COSINE)).size
        else:
            existing_dim = vectors.size
        if existing_dim != dim:
            logger.warning(
                "Qdrant collection '%s' has dimension %d but current embedding provider "
                "produces dimension %d. Recreate the collection to avoid errors.",
                settings.qdrant_collection,
                existing_dim,
                dim,
            )
    else:
        if settings.hybrid_search_enabled:
            client.create_collection(
                collection_name=settings.qdrant_collection,
                vectors_config={
                    "dense": qmodels.VectorParams(
                        size=dim, distance=qmodels.Distance.COSINE
                    )
                },
                sparse_vectors_config={
                    "sparse": qmodels.SparseVectorParams()
                },
            )
        else:
            client.create_collection(
                collection_name=settings.qdrant_collection,
                vectors_config=qmodels.VectorParams(
                    size=dim, distance=qmodels.Distance.COSINE
                ),
            )


def upsert_chunks(
    chunks: List[str],
    source: str,
    tenant_id: str,
    page_numbers: Optional[List[List[int]]] = None,
) -> str:
    """Embed and upsert text chunks into Qdrant, returning the document ID.

    When hybrid search is enabled and the collection supports it, both dense
    and sparse vectors are stored per point.

    Args:
        chunks: List of text chunks to upsert.
        source: Source filename for the document.
        tenant_id: Tenant identifier for multi-tenant filtering.
        page_numbers: Optional list of page number lists, one per chunk.
    """
    ensure_collection()
    client = get_qdrant_client()
    dense_vectors = embed_texts(chunks)
    document_id = str(uuid.uuid4())

    # Determine if we should store sparse vectors
    use_sparse = settings.hybrid_search_enabled and _collection_has_sparse_vectors()
    sparse_vectors = None
    if use_sparse:
        from app.services.sparse_embed import compute_sparse_vectors
        sparse_vectors = compute_sparse_vectors(chunks)

    # Determine if collection uses named vectors
    use_named = _collection_has_named_vectors()

    points = []
    for idx, (text, dense_vec) in enumerate(zip(chunks, dense_vectors)):
        payload = {
            "text": text,
            "source": source,
            "document_id": document_id,
            "chunk_index": idx,
            "tenant_id": tenant_id,
        }
        if page_numbers is not None and idx < len(page_numbers):
            payload["page_numbers"] = page_numbers[idx]

        if use_named:
            vector: dict = {"dense": dense_vec}
            if use_sparse and sparse_vectors is not None:
                vector["sparse"] = sparse_vectors[idx]
            points.append(
                qmodels.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=vector,
                    payload=payload,
                )
            )
        else:
            points.append(
                qmodels.PointStruct(
                    id=str(uuid.uuid4()),
                    vector=dense_vec,
                    payload=payload,
                )
            )

    client.upsert(collection_name=settings.qdrant_collection, points=points)
    return document_id


def list_documents(tenant_id: str) -> List[dict]:
    """List all documents for a tenant by aggregating chunks from Qdrant."""
    ensure_collection()
    client = get_qdrant_client()
    tenant_filter = qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="tenant_id",
                match=qmodels.MatchValue(value=tenant_id),
            )
        ]
    )

    documents: dict[str, dict] = {}
    offset = None
    while True:
        results, next_offset = client.scroll(
            collection_name=settings.qdrant_collection,
            scroll_filter=tenant_filter,
            limit=100,
            offset=offset,
            with_payload=True,
            with_vectors=False,
        )
        for point in results:
            payload = point.payload or {}
            doc_id = payload.get("document_id", "")
            if doc_id not in documents:
                documents[doc_id] = {
                    "document_id": doc_id,
                    "source": payload.get("source", ""),
                    "chunk_count": 0,
                }
            documents[doc_id]["chunk_count"] += 1

        if next_offset is None:
            break
        offset = next_offset

    return list(documents.values())


def delete_document(document_id: str, tenant_id: str) -> int:
    """Delete all chunks for a document within a tenant. Returns deleted count."""
    ensure_collection()
    client = get_qdrant_client()
    doc_filter = qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="document_id",
                match=qmodels.MatchValue(value=document_id),
            ),
            qmodels.FieldCondition(
                key="tenant_id",
                match=qmodels.MatchValue(value=tenant_id),
            ),
        ]
    )

    # Count points before deletion
    count_result = client.count(
        collection_name=settings.qdrant_collection,
        count_filter=doc_filter,
        exact=True,
    )
    deleted_count = count_result.count

    if deleted_count > 0:
        client.delete(
            collection_name=settings.qdrant_collection,
            points_selector=qmodels.FilterSelector(filter=doc_filter),
        )

    return deleted_count


@traceable(name="search_chunks", run_type="retriever")
def search_chunks(query: str, top_k: int, tenant_id: str) -> List[Tuple[str, float, str, List[int]]]:
    """Search for similar chunks in Qdrant.

    When hybrid search is enabled and the collection supports sparse vectors,
    uses Qdrant's prefetch + RRF fusion to combine dense and sparse results.
    Otherwise, falls back to dense-only search.

    Returns a list of tuples: (text, score, source, page_numbers).
    """
    ensure_collection()
    client = get_qdrant_client()
    dense_vector = embed_texts([query])[0]
    tenant_filter = qmodels.Filter(
        must=[
            qmodels.FieldCondition(
                key="tenant_id",
                match=qmodels.MatchValue(value=tenant_id),
            )
        ]
    )

    use_hybrid = settings.hybrid_search_enabled and _collection_has_sparse_vectors()

    if use_hybrid:
        from app.services.sparse_embed import compute_sparse_vectors
        sparse_vector = compute_sparse_vectors([query])[0]

        results = client.query_points(
            collection_name=settings.qdrant_collection,
            prefetch=[
                qmodels.Prefetch(
                    query=dense_vector,
                    using="dense",
                    limit=top_k * 2,
                    filter=tenant_filter,
                ),
                qmodels.Prefetch(
                    query=sparse_vector,
                    using="sparse",
                    limit=top_k * 2,
                    filter=tenant_filter,
                ),
            ],
            query=qmodels.FusionQuery(fusion=qmodels.Fusion.RRF),
            limit=top_k,
            with_payload=True,
        )
    else:
        # Dense-only search (flat or named vectors)
        use_named = _collection_has_named_vectors()
        if use_named:
            results = client.query_points(
                collection_name=settings.qdrant_collection,
                query=dense_vector,
                using="dense",
                limit=top_k,
                with_payload=True,
                query_filter=tenant_filter,
            )
        else:
            results = client.query_points(
                collection_name=settings.qdrant_collection,
                query=dense_vector,
                limit=top_k,
                with_payload=True,
                query_filter=tenant_filter,
            )

    matches: List[Tuple[str, float, str, List[int]]] = []
    for res in results.points:
        payload = res.payload or {}
        matches.append((
            payload.get("text", ""),
            res.score,
            payload.get("source", ""),
            payload.get("page_numbers", []),
        ))
    return matches
