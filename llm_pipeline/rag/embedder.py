"""공유 SentenceTransformer 싱글턴 — cluster_tracker + RAG 모듈에서 재사용."""
from __future__ import annotations

import logging

import numpy as np

logger = logging.getLogger(__name__)

_model = None
MODEL_NAME = "jhgan/ko-sroberta-multitask"


def get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        logger.info("[Embedder] 모델 로드: %s", MODEL_NAME)
        _model = SentenceTransformer(MODEL_NAME)
        logger.info("[Embedder] 모델 로드 완료")
    return _model


def embed_text(text: str) -> np.ndarray:
    model = get_model()
    vec = model.encode(text, normalize_embeddings=True)
    return np.array(vec, dtype=np.float32)


def embed_batch(texts: list[str], batch_size: int = 64) -> np.ndarray:
    model = get_model()
    vecs = model.encode(texts, normalize_embeddings=True, batch_size=batch_size)
    return np.array(vecs, dtype=np.float32)
