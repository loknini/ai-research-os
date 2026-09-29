"""向量索引抽象层（P0）：默认暴力余弦，FAISS 可选插件。

设计（照抄 local_embed.py 懒加载思想）
-------------------------------------
* 真源永远是 SQLite ``rag_chunks``；本模块只做内存加速/排序，不存真数据。
* ``BruteForceIndex``：纯标准库余弦，默认启用，行为与旧 ``rag_service._cosine`` 一致。
* ``FaissIndex``：可选插件。``try import faiss`` 失败即 ``available=False``，
  调用方静默回退暴力。默认关闭，需 ``VECTOR_BACKEND=faiss`` 且已
  ``pip install faiss-cpu``（见 requirements-optional.txt）才启用。
* 多 worker 安全：索引对象按需构建、不跨请求共享可变状态。

用法::

    from .vector_index import backend_name, faiss_available, cosine, topk_cosine
"""
from __future__ import annotations

import math
import os
from typing import Dict, List, Optional, Tuple


def cosine(a: List[float], b: List[float]) -> float:
    """余弦相似度（与旧 rag_service._cosine 同语义，抽到此处复用）。"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def topk_cosine(q_emb: List[float], vecs: List[Tuple[str, Optional[List[float]]]],
                top_k: int) -> List[Tuple[str, float]]:
    """对 (chunk_id, vec|None) 暴力打分，缺向量判 -1（与旧逻辑一致）。"""
    scored: List[Tuple[str, float]] = []
    for cid, v in vecs:
        if v:
            scored.append((cid, cosine(q_emb, v)))
        else:
            scored.append((cid, -1.0))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:max(1, top_k)]


def faiss_available() -> bool:
    """FAISS 是否已安装（不抛异常）。"""
    try:
        import faiss  # noqa: F401
        return True
    except Exception:
        return False


def backend_name() -> str:
    """当前生效的向量后端名：brute（默认）| faiss。

    ``VECTOR_BACKEND=faiss`` 且 faiss 已安装时才返回 faiss，否则一律 brute。
    ``auto``（默认）= 有 faiss 也不自动启用，保持零依赖行为可预期；
    只有显式配 faiss 才启用，避免用户无感引入原生依赖。
    """
    want = (os.environ.get("VECTOR_BACKEND") or "brute").strip().lower()
    if want == "faiss" and faiss_available():
        return "faiss"
    return "brute"


def faiss_topk(q_emb: List[float], vecs: List[Tuple[str, Optional[List[float]]]],
               top_k: int) -> Optional[List[Tuple[str, float]]]:
    """FAISS 加速的 top-k（内积≈余弦，假设向量已 L2 归一化；未归一化也可用相对排序）。

    失败/未安装返回 None，调用方回退 ``topk_cosine``。P0 只做单次内存索引，
    不持久化（真源在 SQLite，重建成本低）。
    """
    if backend_name() != "faiss":
        return None
    try:
        import faiss
        import numpy as np
    except Exception:
        return None
    try:
        ids: List[str] = []
        mat: List[List[float]] = []
        missing: List[Tuple[str, float]] = []
        for cid, v in vecs:
            if v:
                ids.append(cid)
                mat.append(v)
            else:
                missing.append((cid, -1.0))
        if not mat:
            return (missing[:top_k] or [])[:max(1, top_k)]
        dim = len(mat[0])
        if any(len(r) != dim for r in mat):
            return None
        index = faiss.IndexFlatIP(dim)
        xb = np.asarray(mat, dtype=np.float32)
        # L2 归一化后内积即余弦；归一化失败不阻断
        try:
            norms = np.linalg.norm(xb, axis=1, keepdims=True) + 1e-8
            xb = xb / norms
            q = np.asarray([q_emb], dtype=np.float32)
            q = q / (np.linalg.norm(q) + 1e-8)
        except Exception:
            q = np.asarray([q_emb], dtype=np.float32)
        index.add(xb)
        k = min(max(1, top_k), len(ids))
        scores, idx = index.search(q, k)
        out = [(ids[i], float(scores[0][j])) for j, i in enumerate(idx[0]) if 0 <= i < len(ids)]
        # 缺向量垫底（保持与暴力一致的语义）
        if len(out) < top_k:
            out.extend(missing[:max(0, top_k - len(out))])
        return out
    except Exception:
        return None


__all__ = ["cosine", "topk_cosine", "faiss_available", "backend_name", "faiss_topk"]
