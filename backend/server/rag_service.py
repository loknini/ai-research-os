"""RAG 检索引擎：文档抓取、切片、向量化、检索与带引用回答。

设计要点
--------
* **零重依赖**：PDF 解析用可选依赖 ``pypdf``（已在 requirements.txt）；TXT/MD
  用标准库读取。无 ``pypdf`` 时仅跳过 PDF，不影响其它格式。
* **嵌入向量**：复用 ``llm.py`` 的 OpenAI 兼容 ``/v1/embeddings`` 端点
  （与 chat 共用同一 LLM 配置）。嵌入失败时**自动降级**为关键词（词频）检索，
  保证 RAG 在任意环境下都能工作。
* **切片**：递归字符切分（按段落/句/词逐级回退），记录每个切片的字符区间与
  对应页码，便于后续溯源。
* **空间隔离**：所有读写均经 ``scripts/database.py`` 并按 ``space_id`` 过滤。
"""
from __future__ import annotations

import math
import os
import re
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import db
from .llm import llm_client

# PDF 解析为可选依赖：未安装时仅跳过 PDF，不阻断其它格式。
try:  # pragma: no cover - 依赖在 requirements 中声明
    from pypdf import PdfReader
    _HAS_PYPDF = True
except Exception:  # noqa: BLE001
    _HAS_PYPDF = False


# 支持的扩展名 -> 归一化类型
_EXT_TO_TYPE = {
    ".pdf": "pdf",
    ".txt": "txt",
    ".md": "md",
    ".markdown": "md",
}

# 单文件大小上限（50MB），避免超大文件卡死索引。
_MAX_FILE_SIZE = 50 * 1024 * 1024

# 切片参数
_CHUNK_SIZE = 1000          # 每个切片的目标字符数
_CHUNK_SEPARATORS = ["\n\n", "\n", "。", "！", "？", "；", ";", ".", " ", ""]
_EMBED_BATCH = 16           # 每次嵌入请求的批量大小


# ===========================================================================
# 1. 文件发现
# ===========================================================================
def _ext_type(fp: Path) -> str:
    ext = fp.suffix.lower()
    return _EXT_TO_TYPE.get(ext, ext.lstrip("."))


def _ext_match(fp: Path, wanted: set) -> bool:
    if not wanted:
        return fp.suffix.lower() in _EXT_TO_TYPE
    ext = fp.suffix.lower().lstrip(".")
    typ = _ext_type(fp)
    return typ in wanted or ext in wanted


def discover_files(paths: List[str], recursive: bool, file_types: Optional[List[str]]) -> List[Path]:
    """根据一个或多个目标路径，递归/非递归收集可索引文件。

    * 路径不存在则跳过（不报错，便于批量提交）。
    * 目录：``recursive`` 决定是否深入子目录。
    * 文件类型：``file_types`` 为空则接受全部受支持类型，否则按归一化类型过滤。
    * 返回去重、按路径排序后的绝对文件路径列表。
    """
    wanted = {t.lower().lstrip(".") for t in (file_types or [])}
    results: List[Path] = []
    for raw in paths or []:
        p = Path(raw.strip())
        if not p.exists():
            continue
        if p.is_file():
            if _ext_match(p, wanted):
                results.append(p)
        elif p.is_dir():
            iterator = p.rglob("*") if recursive else p.iterdir()
            for f in iterator:
                if f.is_file() and _ext_match(f, wanted):
                    results.append(f)

    # 去重（按 resolve 后的真实路径），保持顺序。
    seen: set = set()
    uniq: List[Path] = []
    for f in sorted(results, key=lambda x: str(x)):
        try:
            rp = f.resolve()
        except Exception:
            rp = f
        if rp not in seen:
            seen.add(rp)
            uniq.append(f)
    return uniq


# ===========================================================================
# 2. 文档抽取（逐页）
# ===========================================================================
def _read_text_file(fp: Path) -> str:
    """读取文本文件，多编码回退，保证不崩。"""
    last_err: Optional[Exception] = None
    for enc in ("utf-8", "utf-8-sig", "gbk", "latin-1"):
        try:
            return fp.read_text(encoding=enc)
        except Exception as e:  # noqa: BLE001
            last_err = e
    # 终极兜底：二进制读取后按 utf-8 容错解码。
    try:
        return fp.read_bytes().decode("utf-8", errors="replace")
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"无法读取文本文件 {fp.name}: {last_err or e}")


def _build_page_layout(page_texts: List[Tuple[int, str]]) -> Tuple[str, List[Tuple[int, int, int]]]:
    """把 (页码, 文本) 列表拼成连续全文，并返回每页的字符区间。

    全文用单个 ``\\n`` 连接相邻页，便于页码映射。返回 (full_text, bounds)，
    bounds 元素为 (page_no, start_char, end_char)。
    """
    parts: List[str] = []
    bounds: List[Tuple[int, int, int]] = []
    pos = 0
    for idx, (no, txt) in enumerate(page_texts):
        if idx > 0:
            sep = "\n"
            parts.append(sep)
            pos += len(sep)
        start = pos
        parts.append(txt)
        end = pos + len(txt)
        bounds.append((no, start, end))
        pos = end
    return "".join(parts), bounds


def extract_document(fp: Path) -> Dict[str, Any]:
    """抽取单个文档为逐页文本 + 元数据。

    返回 dict: {full_text, page_boundaries, file_type, file_size, page_count, char_count}
    """
    file_size = fp.stat().st_size
    ext = fp.suffix.lower()
    if ext == ".pdf":
        if not _HAS_PYPDF:
            raise RuntimeError("未安装 pypdf，无法解析 PDF（请 pip install pypdf）")
        reader = PdfReader(str(fp))
        page_texts: List[Tuple[int, str]] = []
        for i, page in enumerate(reader.pages):
            try:
                txt = page.extract_text() or ""
            except Exception:  # noqa: BLE001
                txt = ""
            page_texts.append((i + 1, txt))
    else:
        txt = _read_text_file(fp)
        page_texts = [(1, txt)]

    full_text, bounds = _build_page_layout(page_texts)
    return {
        "full_text": full_text,
        "page_boundaries": bounds,
        "file_type": _ext_type(fp),
        "file_size": file_size,
        "page_count": len(page_texts),
        "char_count": len(full_text),
    }


# ===========================================================================
# 3. 切片
# ===========================================================================
def _split_span(text: str, start: int, end: int, chunk_size: int,
                seps: List[str]) -> List[Tuple[int, int]]:
    """递归字符切分：在 [start, end) 内按分隔符逐级回退，产出 <= chunk_size 的区间。

    纯索引切分（不含 overlap），区间边界精确，便于页码映射。
    """
    seg = text[start:end]
    if len(seg) <= chunk_size:
        return [(start, end)] if seg.strip() else []
    sep = seps[0]
    if not sep:
        out: List[Tuple[int, int]] = []
        s = start
        while s < end:
            e = min(s + chunk_size, end)
            out.append((s, e))
            s = e
        return out
    # 在该层级找分隔位置。
    positions: List[int] = []
    idx = start
    while True:
        found = text.find(sep, idx, end)
        if found == -1:
            break
        positions.append(found + len(sep))
        idx = found + len(sep)
    if not positions:
        return _split_span(text, start, end, chunk_size, seps[1:])
    bounds = [start] + positions + [end]
    merged: List[Tuple[int, int]] = []
    cur_s, cur_e = bounds[0], bounds[0]
    for b in bounds[1:]:
        if (b - cur_s) > chunk_size and (cur_e - cur_s) > 0:
            merged.append((cur_s, cur_e))
            cur_s = cur_e
        cur_e = b
    if cur_e - cur_s > 0:
        merged.append((cur_s, cur_e))
    # 仍有超长片段（单个巨大 piece）→ 进入更深层级继续切。
    refined: List[Tuple[int, int]] = []
    for (s, e) in merged:
        if (e - s) > chunk_size:
            refined.extend(_split_span(text, s, e, chunk_size, seps[1:]))
        else:
            refined.append((s, e))
    return refined


def _pages_for_range(bounds: List[Tuple[int, int, int]], s: int, e: int) -> Tuple[int, int]:
    """求字符区间 [s, e) 覆盖的页码范围（首/尾页）。"""
    ps: Optional[int] = None
    pe: Optional[int] = None
    for (no, start, end) in bounds:
        if start < e and end > s:  # 区间有重叠
            if ps is None:
                ps = no
            pe = no
    if ps is None:
        ps = bounds[-1][0] if bounds else 1
        pe = ps
    return ps, (pe or ps)


def chunk_document(full_text: str, bounds: List[Tuple[int, int, int]],
                   chunk_size: int = _CHUNK_SIZE) -> List[Dict[str, Any]]:
    """把全文切成带页码映射的切片列表。"""
    spans = _split_span(full_text, 0, len(full_text), chunk_size, _CHUNK_SEPARATORS)
    chunks: List[Dict[str, Any]] = []
    for (s, e) in spans:
        ps, pe = _pages_for_range(bounds, s, e)
        chunks.append({
            "content": full_text[s:e],
            "char_start": s,
            "char_end": e,
            "page_start": ps,
            "page_end": pe,
        })
    return chunks


# ===========================================================================
# 4. 嵌入（向量化）
# ===========================================================================
def _embed_texts(texts: List[str], model: Optional[str] = None) -> Optional[List[List[float]]]:
    """批量嵌入；任一分组失败即返回 None（调用方降级为关键词检索）。"""
    if not texts or not llm_client.configured:
        return None
    out: List[List[float]] = []
    for i in range(0, len(texts), _EMBED_BATCH):
        vecs = llm_client.embed(texts[i:i + _EMBED_BATCH], model=model)
        if vecs is None:
            return None
        out.extend(vecs)
    return out if len(out) == len(texts) else None


# ===========================================================================
# 5. 索引编排（后台线程调用，async）
# ===========================================================================
async def index_source(
    source_id: str,
    space_id: str,
    paths: List[str],
    recursive: bool,
    file_types: Optional[List[str]],
    embedding_model: Optional[str] = None,
    cancel_event: Optional[threading.Event] = None,
) -> Dict[str, Any]:
    """对一个索引源执行完整索引流程：发现 → 抽取 → 切片 → 嵌入 → 落库。

    进度/状态全部落在 ``rag_sources``（status: indexing→ready/partial/failed/cancelled），
    前端轮询即可看到；``cancel_event`` 支持中途取消（跨 worker 以 DB 状态为准）。
    """
    await db.database.update_rag_source(source_id, space_id, status="indexing", error=None)
    files = discover_files(paths, recursive, file_types)
    if not files:
        await db.database.update_rag_source(
            source_id, space_id, status="failed", error="未找到可索引的文件（请检查路径/类型）")
        return {"status": "failed", "doc_count": 0, "chunk_count": 0}

    all_chunks: List[Dict[str, Any]] = []
    doc_count = 0
    skipped = 0
    for fp in files:
        if cancel_event and cancel_event.is_set():
            await db.database.update_rag_source(source_id, space_id, status="cancelled")
            return {"status": "cancelled", "doc_count": doc_count,
                    "chunk_count": len(all_chunks)}
        try:
            if fp.stat().st_size > _MAX_FILE_SIZE:
                skipped += 1
                continue
            meta = extract_document(fp)
        except Exception as exc:  # noqa: BLE001 - 单个文件失败不阻断整体
            print(f"[rag] skip {fp}: {exc}")
            skipped += 1
            continue

        doc_id = str(uuid.uuid4())
        await db.database.create_rag_document(
            doc_id, space_id, source_id, str(fp), fp.name, meta["file_type"],
            meta["file_size"], meta["page_count"], meta["char_count"], 0)
        doc_count += 1

        chunks = chunk_document(meta["full_text"], meta["page_boundaries"])
        for i, ch in enumerate(chunks):
            all_chunks.append({
                "id": str(uuid.uuid4()),
                "source_id": source_id,
                "doc_id": doc_id,
                "chunk_index": i,
                "content": ch["content"],
                "page_start": ch["page_start"],
                "page_end": ch["page_end"],
                "char_start": ch["char_start"],
                "char_end": ch["char_end"],
                "embedding": None,
                "token_count": max(1, len(ch["content"]) // 4),
            })
        await db.database.update_rag_document(doc_id, space_id, chunk_count=len(chunks))

        # 及时释放大文本，避免内存堆积。
        meta.clear()

    if doc_count == 0:
        await db.database.update_rag_source(
            source_id, space_id, status="failed",
            error="所有文件均解析失败（PDF 需安装 pypdf；或文件为空/损坏）")
        return {"status": "failed", "doc_count": 0, "chunk_count": 0}

    # 向量化（可选）。
    embed_mode = "keyword"
    if embedding_model and llm_client.configured:
        texts = [c["content"] for c in all_chunks]
        vecs = _embed_texts(texts, model=embedding_model)
        if vecs is not None and len(vecs) == len(all_chunks):
            for c, v in zip(all_chunks, vecs):
                c["embedding"] = v
            embed_mode = "vector"

    # 落库（分批，避免单事务过大）。
    for i in range(0, len(all_chunks), 200):
        await db.database.insert_rag_chunks(all_chunks[i:i + 200], space_id)

    status = "ready" if skipped == 0 else "partial"
    await db.database.update_rag_source(
        source_id, space_id, status=status, doc_count=doc_count,
        chunk_count=len(all_chunks), embed_mode=embed_mode,
        embedding_model=embedding_model or "")
    return {"status": status, "doc_count": doc_count, "chunk_count": len(all_chunks),
            "skipped": skipped, "embed_mode": embed_mode}


# ===========================================================================
# 6. 检索 + 带引用回答
# ===========================================================================
def _tokenize(text: str) -> List[str]:
    """英文/数字词 + 中文单字，作为关键词检索的基本单位。"""
    text = text.lower()
    tokens = re.findall(r"[a-z0-9]+", text)
    cjk = re.findall(r"[\u4e00-\u9fff]", text)
    return tokens + cjk


def _cosine(a: List[float], b: List[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _keyword_score(query_tokens: List[str], content: str) -> float:
    if not query_tokens:
        return 0.0
    content_l = content.lower()
    # 词频计数（只在需要时计算一次）。
    counts: Dict[str, int] = {}
    for tok in re.findall(r"[a-z0-9]+", content_l):
        counts[tok] = counts.get(tok, 0) + 1
    cjk_counts: Dict[str, int] = {}
    for ch in re.findall(r"[\u4e00-\u9fff]", content_l):
        cjk_counts[ch] = cjk_counts.get(ch, 0) + 1
    score = 0.0
    for qt in query_tokens:
        if len(qt) == 1:  # 中文单字权重略低
            score += min(cjk_counts.get(qt, 0), 5) * 0.5
        else:
            score += min(counts.get(qt, 0), 5) * 1.0
    return score


async def retrieve(space_id: str, question: str, top_k: int = 5,
                   source_ids: Optional[List[str]] = None) -> Tuple[List[Dict[str, Any]], str, bool]:
    """检索最相关切片，返回 (hits, mode, embed_available)。

    mode: 'vector'（向量语义）| 'keyword'（关键词）| 'empty'（无内容）。
    """
    chunks = await db.database.get_rag_chunks_for_retrieval(space_id, source_ids)
    if not chunks:
        return [], "empty", False

    q_tokens = _tokenize(question)
    q_emb: Optional[List[float]] = None
    embed_available = False
    if llm_client.configured:
        try:
            r = llm_client.embed([question])
            if r:
                q_emb = r[0]
                embed_available = True
        except Exception:  # noqa: BLE001
            q_emb = None

    any_vec = any(c["embedding"] for c in chunks)
    use_vector = embed_available and q_emb is not None and any_vec

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for c in chunks:
        if use_vector and c["embedding"]:
            score = _cosine(q_emb, c["embedding"])
        elif use_vector and not c["embedding"]:
            score = -1.0  # 向量模式下缺向量的切片降权
        else:
            score = _keyword_score(q_tokens, c["content"])
        scored.append((score, c))

    scored.sort(key=lambda x: x[0], reverse=True)
    top = scored[:top_k]

    hits: List[Dict[str, Any]] = []
    for rank, (score, c) in enumerate(top, 1):
        hits.append({
            "rank": rank,
            "chunkId": c["id"],
            "sourceId": c["sourceId"],
            "docId": c["docId"],
            "fileName": c["fileName"],
            "filePath": c["filePath"],
            "fileType": c["fileType"],
            "pageStart": c["pageStart"],
            "pageEnd": c["pageEnd"],
            "content": c["content"],
            "score": round(float(score), 4),
        })
    mode = "vector" if use_vector else "keyword"
    return hits, mode, embed_available


_SYSTEM_PROMPT = (
    "你是严谨的研究助手。请仅基于下面提供的「文档片段」回答用户问题。"
    "每个片段前有编号 [n]，括号内为其来源文件与页码。请在回答中通过 [n] 引用"
    "你实际用到的片段；若片段信息不足以回答，请明确说明，不要编造。"
    "用中文回答，保持简洁准确。"
)


async def answer_with_context(question: str, hits: List[Dict[str, Any]],
                              mode: str) -> Dict[str, Any]:
    """基于检索命中，调用 LLM 生成带引用的回答；LLM 不可用时给出片段兜底。"""
    if not hits:
        return {
            "answer": "暂无可检索的文档内容，请先在左侧索引至少一个目标路径。",
            "sources": [],
            "mode": "empty",
        }

    context_parts: List[str] = []
    for h in hits:
        context_parts.append(
            f"[{h['rank']}] (来源: {h['fileName']} 第{h['pageStart']}页)\n{h['content']}")
    context_text = "\n\n".join(context_parts)
    user_msg = f"用户问题：{question}\n\n文档片段：\n{context_text}"

    answer = llm_client.call_llm([
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": user_msg},
    ])

    if not answer:
        # LLM 不可用：退化为片段罗列，仍给出溯源。
        lines = [f"[{h['rank']}] {h['fileName']}（第 {h['pageStart']} 页）：{h['content'][:240]}…"
                 for h in hits]
        answer = "（LLM 未配置或调用失败，以下为最相关片段，请自行参考）\n" + "\n".join(lines)

    sources = [{
        "rank": h["rank"],
        "fileName": h["fileName"],
        "filePath": h["filePath"],
        "fileType": h["fileType"],
        "pageStart": h["pageStart"],
        "pageEnd": h["pageEnd"],
        "snippet": h["content"],
        "score": h["score"],
    } for h in hits]

    return {"answer": answer, "sources": sources, "mode": mode}


async def query(space_id: str, question: str, top_k: int = 5,
                source_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    """检索 + 回答一站式入口。"""
    hits, mode, embed_available = await retrieve(space_id, question, top_k, source_ids)
    result = await answer_with_context(question, hits, mode)
    result["hits"] = hits
    result["embedAvailable"] = embed_available
    result["topK"] = top_k
    return result


__all__ = [
    "discover_files", "extract_document", "chunk_document",
    "index_source", "retrieve", "answer_with_context", "query",
]
