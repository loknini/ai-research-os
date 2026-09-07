"""本地嵌入引擎：基于 transformers + torch，支持 Qwen3-Embedding-0.6B。

模型从 ModelScope 下载，首次调用自动初始化，后续复用缓存。

用法（外部不直接调用，由 ``llm.py`` 的 ``embed_with_fallback`` 统一调度）::

    from .local_embed import get_local_embedder
    embedder = get_local_embedder()
    if not embedder.loaded:
        embedder.load("Qwen/Qwen3-Embedding-0.6B")
    vecs = embedder.embed(["hello world"])

设计要点：
  * **零启动开销**：torch / transformers 延迟导入，首次 ``embed()`` 才加载。
  * **线程安全**：``load()`` 加锁，多 worker 不重复加载。
  * **设备自适应**：CUDA 可用自动用 GPU，否则 CPU。
  * **Last-token pooling**：Qwen3 官方推荐，优于 mean pooling。
  * **L2 归一化**：输出向量已归一化，可直接用余弦内积检索。
"""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import List, Optional

# 延迟导入 torch / transformers（避免模块加载时拖慢启动）
_torch = None
_transformers = None


def _ensure_imports() -> None:
    global _torch, _transformers
    if _torch is None:
        import torch as _t
        import transformers as _tr
        _torch = _t
        _transformers = _tr


class LocalEmbedder:
    """单例本地嵌入引擎（惰性初始化）。"""

    def __init__(self) -> None:
        self._model = None
        self._tokenizer = None
        self._device = None
        self._dims: int = 0
        self._model_path: str = ""
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 模型路径解析 & 下载
    # ------------------------------------------------------------------
    def _resolve_model_path(self, model_id: str) -> Path:
        """解析模型路径：本地目录直接用，ModelScope ID 下载到 data/models/。"""
        p = Path(model_id)
        if p.is_dir():
            return p
        # 默认缓存目录：data/models/<sanitized_id>
        from . import config
        safe_name = model_id.replace("/", "_").replace("\\", "_")
        cache_dir = config.DATA_DIR / "models" / safe_name
        cache_dir.mkdir(parents=True, exist_ok=True)
        # 检查是否已下载（config.json 存在即认为已下载）
        if any(cache_dir.glob("config.json")):
            return cache_dir
        # 从 ModelScope 下载
        self._download_modelscope(model_id, cache_dir)
        return cache_dir

    def _download_modelscope(self, model_id: str, target_dir: Path) -> None:
        """从 ModelScope 下载模型（优先 modelscope SDK，fallback huggingface_hub）。"""
        try:
            from modelscope import snapshot_download
            snapshot_download(model_id, local_dir=str(target_dir))
            return
        except ImportError:
            pass
        # fallback: huggingface_hub + ModelScope 镜像
        try:
            from huggingface_hub import snapshot_download as hf_snapshot
            old_endpoint = os.environ.get("HF_ENDPOINT")
            os.environ["HF_ENDPOINT"] = os.environ.get(
                "HF_ENDPOINT", "https://hf-mirror.com")
            try:
                hf_snapshot(model_id, local_dir=str(target_dir))
            finally:
                if old_endpoint is None:
                    os.environ.pop("HF_ENDPOINT", None)
                else:
                    os.environ["HF_ENDPOINT"] = old_endpoint
        except ImportError:
            raise RuntimeError(
                "请安装 modelscope 或 huggingface_hub 以下载嵌入模型："
                "pip install modelscope  或  pip install huggingface_hub"
            )

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------
    def load(self, model_path: str) -> bool:
        """加载模型。线程安全，只加载一次。返回是否成功。"""
        with self._lock:
            if self._model is not None and self._model_path == model_path:
                return True
            try:
                _ensure_imports()
                resolved = self._resolve_model_path(model_path)
                # 设备选择
                self._device = _torch.device(
                    "cuda" if _torch.cuda.is_available() else "cpu")
                # tokenizer
                self._tokenizer = _transformers.AutoTokenizer.from_pretrained(
                    str(resolved), trust_remote_code=True)
                # model
                self._model = _transformers.AutoModel.from_pretrained(
                    str(resolved), trust_remote_code=True).to(self._device)
                self._model.eval()
                self._dims = getattr(
                    self._model.config, "hidden_size", 1024)
                self._model_path = model_path
                dev = "GPU" if self._device.type == "cuda" else "CPU"
                print(f"[local_embed] 模型加载完成: {model_path} ({dev}，"
                      f"{self._dims} 维)")
                return True
            except Exception as exc:
                print(f"[local_embed] 模型加载失败: {exc}")
                self._model = None
                return False

    # ------------------------------------------------------------------
    # 推理
    # ------------------------------------------------------------------
    def embed(
        self,
        texts: List[str],
        *,
        max_length: int = 8192,
    ) -> Optional[List[List[float]]]:
        """批量嵌入，返回 L2 归一化向量列表。失败返回 None。"""
        if self._model is None or self._tokenizer is None:
            return None
        try:
            _ensure_imports()
            # tokenize
            batch_dict = self._tokenizer(
                texts,
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )
            batch_dict = batch_dict.to(self._device)
            # 推理
            with _torch.no_grad():
                outputs = self._model(**batch_dict)
            # last-token pooling
            last_hidden = outputs.last_hidden_state
            attention_mask = batch_dict["attention_mask"]
            left_padding = (
                attention_mask[:, -1].sum() == attention_mask.shape[0])
            if left_padding:
                embeddings = last_hidden[:, -1]
            else:
                seq_lens = attention_mask.sum(dim=1) - 1
                bs = last_hidden.shape[0]
                embeddings = last_hidden[
                    _torch.arange(bs, device=self._device), seq_lens]
            # L2 normalize
            norms = _torch.norm(embeddings, p=2, dim=1, keepdim=True)
            embeddings = embeddings / (norms + 1e-8)
            # → python list
            vecs = embeddings.cpu().float().numpy().tolist()
            return vecs
        except Exception as exc:
            print(f"[local_embed] 推理失败: {exc}")
            return None

    # ------------------------------------------------------------------
    # 属性
    # ------------------------------------------------------------------
    @property
    def dims(self) -> int:
        return self._dims

    @property
    def device_name(self) -> str:
        return str(self._device) if self._device else "cpu"

    @property
    def loaded(self) -> bool:
        return self._model is not None


# 全局单例
_local_embedder = LocalEmbedder()


def get_local_embedder() -> LocalEmbedder:
    """获取全局本地嵌入引擎单例。"""
    return _local_embedder


__all__ = ["LocalEmbedder", "get_local_embedder"]
