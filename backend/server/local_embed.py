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
import hashlib
import re
import threading
import urllib.parse
from pathlib import Path
from typing import Any, Dict, List, Optional

# 延迟导入 torch / transformers（避免模块加载时拖慢启动）
_torch = None
_transformers = None


def _model_cache_name(model_id: str, revision: str = "") -> str:
    """Filesystem-safe cache key; revisions never become raw path fragments."""
    safe_name = re.sub(r"[^A-Za-z0-9._-]+", "_", model_id).strip("._") or "model"
    if revision:
        rev_hash = hashlib.sha256(revision.encode("utf-8")).hexdigest()[:12]
        safe_name += f"--{rev_hash}"
    return safe_name


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
        self._revision: str = ""
        self._last_error: str = ""  # 最近一次 load/embed 失败原文（供设置页提示）
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # 模型路径解析 & 下载
    # ------------------------------------------------------------------
    def _resolve_model_path(self, model_id: str, revision: str = "") -> Path:
        """解析模型路径：本地目录直接用，ModelScope ID 下载到 data/models/。"""
        p = Path(model_id)
        if p.is_dir():
            return p
        # 默认缓存目录：data/models/<sanitized_id>
        from . import config
        safe_name = _model_cache_name(model_id, revision)
        cache_dir = config.DATA_DIR / "models" / safe_name
        cache_dir.mkdir(parents=True, exist_ok=True)
        # 检查是否已下载（config.json 存在即认为已下载）
        if any(cache_dir.glob("config.json")):
            return cache_dir
        # 从 ModelScope 下载
        self._download_modelscope(model_id, cache_dir, revision)
        return cache_dir

    def _download_modelscope(self, model_id: str, target_dir: Path,
                             revision: str = "") -> None:
        """下载模型快照（三级兜底，零新增依赖可用）。

        1. ``modelscope`` SDK（官方源，速度最稳）；
        2. ``huggingface_hub`` SDK（走 ``HF_ENDPOINT`` 镜像，默认 hf-mirror.com）；
        3. 纯标准库 ``urllib``（无任何 SDK 时的保底：读 Hub API 取文件列表，
           逐文件下载，支持断点续传——手动重试可接着下）。
        前两级缺 SDK（ImportError）或下载抛错都继续往下一级走；全部失败才抛错。
        """
        errors: List[str] = []
        try:
            from modelscope import snapshot_download
            kwargs = {"revision": revision} if revision else {}
            snapshot_download(model_id, local_dir=str(target_dir), **kwargs)
            return
        except ImportError:
            errors.append("modelscope 未安装")
        except Exception as exc:  # noqa: BLE001 - SDK 下载失败，继续试下一级
            errors.append(f"modelscope 下载失败：{exc}")
        try:
            from huggingface_hub import snapshot_download as hf_snapshot
            old_endpoint = os.environ.get("HF_ENDPOINT")
            os.environ["HF_ENDPOINT"] = os.environ.get(
                "HF_ENDPOINT", "https://hf-mirror.com")
            try:
                kwargs = {"revision": revision} if revision else {}
                hf_snapshot(model_id, local_dir=str(target_dir), **kwargs)
                return
            finally:
                if old_endpoint is None:
                    os.environ.pop("HF_ENDPOINT", None)
                else:
                    os.environ["HF_ENDPOINT"] = old_endpoint
        except ImportError:
            errors.append("huggingface_hub 未安装")
        except Exception as exc:  # noqa: BLE001
            errors.append(f"huggingface_hub 下载失败：{exc}")
        try:
            self._download_stdlib(model_id, target_dir, revision)
            return
        except Exception as exc:  # noqa: BLE001
            errors.append(f"标准库下载失败：{exc}")
        raise RuntimeError(
            "模型下载失败（已按 modelscope → huggingface_hub → 标准库顺序尝试）："
            + "；".join(errors)
            + "。可 pip install modelscope 或 huggingface_hub 后重试，"
              "或检查模型 ID / 网络与 HF_ENDPOINT 镜像配置。"
        )

    _STDLIB_UA = "AI-Research-OS RAG/0.5 (+local-first)"
    _STDLIB_CHUNK = 1024 * 1024  # 1MB 分块

    def _download_stdlib(self, model_id: str, target_dir: Path,
                         revision: str = "") -> None:
        """纯标准库下载：Hub API 取文件列表 → 逐文件 urllib 下载。

        * 镜像地址取 ``HF_ENDPOINT``（默认 https://hf-mirror.com），与 SDK 路径一致；
        * 断点续传：目标文件已存在且非空则带 ``Range`` 续下，服务端不支持则重下；
        * 路径穿越防护：所有落盘路径必须位于 ``target_dir`` 内。
        """
        import json as _json
        import urllib.error as _uerr
        import urllib.request as _ureq
        mirror = os.environ.get("HF_ENDPOINT", "https://hf-mirror.com").rstrip("/")

        def _get_json(url: str) -> Any:
            req = _ureq.Request(url, headers={"User-Agent": self._STDLIB_UA,
                                              "Accept": "application/json"})
            with _ureq.urlopen(req, timeout=30) as resp:
                return _json.loads(resp.read().decode("utf-8"))

        try:
            info = _get_json(f"{mirror}/api/models/{model_id}")
        except Exception as exc:
            raise RuntimeError(f"读取模型文件列表失败（ID 错误/需登录/镜像不可达）：{exc}")
        siblings = info.get("siblings") or []
        files = [s.get("rfilename") for s in siblings if isinstance(s, dict) and s.get("rfilename")]
        if not files:
            raise RuntimeError(f"模型 {model_id} 文件列表为空（ID 错误或需登录的私有库）")

        base = target_dir.resolve()
        target_dir.mkdir(parents=True, exist_ok=True)
        for rel in files:
            dest = (target_dir / rel).resolve()
            if dest != base and base not in dest.parents:
                raise RuntimeError(f"拒绝路径穿越：{rel}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            ref = urllib.parse.quote(revision or "main", safe="")
            url = f"{mirror}/{model_id}/resolve/{ref}/{rel}"
            existing = dest.stat().st_size if dest.exists() else 0
            headers = {"User-Agent": self._STDLIB_UA}
            if existing > 0:
                headers["Range"] = f"bytes={existing}-"
            req = _ureq.Request(url, headers=headers)
            try:
                resp = _ureq.urlopen(req, timeout=60)
            except _uerr.HTTPError as exc:
                if exc.code == 416:
                    continue  # 本地已完整（Range 越界），跳过
                raise RuntimeError(f"下载 {rel} 失败：HTTP {exc.code}")
            except Exception as exc:
                raise RuntimeError(f"下载 {rel} 失败：{exc}")
            with resp:
                status = getattr(resp, "status", 200)
                mode = "ab" if (status == 206 and existing > 0) else "wb"
                with open(dest, mode) as f:
                    while True:
                        chunk = resp.read(self._STDLIB_CHUNK)
                        if not chunk:
                            break
                        f.write(chunk)

    # ------------------------------------------------------------------
    # 加载
    # ------------------------------------------------------------------
    def load(self, model_path: str, revision: str = "") -> bool:
        """加载模型。线程安全，只加载一次。返回是否成功。"""
        with self._lock:
            if (self._model is not None and self._model_path == model_path
                    and self._revision == revision):
                return True
            try:
                _ensure_imports()
                resolved = self._resolve_model_path(model_path, revision)
                # 设备选择
                self._device = _torch.device(
                    "cuda" if _torch.cuda.is_available() else "cpu")
                # tokenizer
                self._tokenizer = _transformers.AutoTokenizer.from_pretrained(
                    str(resolved), trust_remote_code=False, local_files_only=True,
                    padding_side="left", truncation_side="left")
                # model
                self._model = _transformers.AutoModel.from_pretrained(
                    str(resolved), trust_remote_code=False, local_files_only=True,
                    use_safetensors=True).to(self._device)
                self._model.eval()
                self._dims = getattr(
                    self._model.config, "hidden_size", 1024)
                self._model_path = model_path
                self._revision = revision
                self._last_error = ""
                dev = "GPU" if self._device.type == "cuda" else "CPU"
                print(f"[local_embed] 模型加载完成: {model_path} ({dev}，"
                      f"{self._dims} 维)")
                return True
            except Exception as exc:
                print(f"[local_embed] 模型加载失败: {exc}")
                self._model = None
                self._last_error = str(exc)[:200]
                return False

    # ------------------------------------------------------------------
    # 推理
    # ------------------------------------------------------------------
    def embed(
        self,
        texts: List[str],
        *,
        max_length: int = 8192,
        is_query: bool = False,
        instruction: str = "",
    ) -> Optional[List[List[float]]]:
        """批量嵌入，返回 L2 归一化向量列表。失败返回 None。"""
        if self._model is None or self._tokenizer is None:
            return None
        try:
            _ensure_imports()
            prepared = list(texts)
            if is_query and instruction:
                prepared = [f"Instruct: {instruction}\nQuery: {text}" for text in prepared]
            # Qwen3-Embedding 以最后一个 token 做 pooling；显式 EOS 保证语义位置稳定。
            eos = self._tokenizer.eos_token or ""
            if eos:
                prepared = [text if text.endswith(eos) else text + eos for text in prepared]
            # tokenize
            batch_dict = self._tokenizer(
                prepared,
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
            self._last_error = str(exc)[:200]
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

    @property
    def last_error(self) -> str:
        """最近一次 load/embed 失败原文（空 = 无失败；供设置页提示安装缺失依赖）."""
        return self._last_error


# 全局单例
_local_embedder = LocalEmbedder()


def get_local_embedder() -> LocalEmbedder:
    """获取全局本地嵌入引擎单例。"""
    return _local_embedder


def _dir_size_mb(path: Path) -> float:
    """目录大小（MB，失败回 0）。"""
    try:
        total = sum(f.stat().st_size for f in path.rglob("*") if f.is_file())
        return round(total / 1024 / 1024, 1)
    except Exception:
        return 0.0


def scan_local_models() -> List[Dict[str, Any]]:
    """只读扫描已下载的本地嵌入模型（绝不触发下载）。

    来源：``data/models/*``。``downloaded`` 为严格口径（含 config.json +
    权重文件）；仅有 config.json 的残缺目录照常列出但 ``downloaded=False``、
    ``incomplete=True``，供前端提示续传。
    返回 ``[{id, path, sizeMB, downloaded, incomplete}]``，按 id 排序。
    """
    from . import config as _config
    models_dir = _config.DATA_DIR / "models"
    out: List[Dict[str, Any]] = []
    try:
        if not models_dir.is_dir():
            return out
        for child in sorted(models_dir.iterdir(), key=lambda p: p.name):
            try:
                if not child.is_dir():
                    continue
                has_config = any(child.glob("config.json"))
                complete = bool(has_config) and _has_weights(child)
                out.append({
                    "id": child.name,
                    "path": str(child),
                    "sizeMB": _dir_size_mb(child),
                    "downloaded": complete,
                    "incomplete": bool(has_config) and not complete,
                })
            except Exception:
                continue
    except Exception:
        return out
    return out


def _has_weights(d: Path) -> bool:
    """目录是否含权重文件（残缺下载识别用）。"""
    try:
        for pat in ("*.safetensors", "*.bin", "*.pt", "*.pth", "*.h5",
                    "*.ckpt", "*.onnx", "*.msgpack"):
            if any(d.glob(pat)):
                return True
    except Exception:
        pass
    return False


def probe_local_model(model_id: str, revision: str = "") -> Dict[str, Any]:
    """只读判定模型是否本地可用（不下载）。

    完整性要求（T3）：``config.json`` + 至少一个权重文件才算可用；
    仅有 config.json 视为残缺下载（resolvable=False，reason 注明可续传）。
    """
    model_id = (model_id or "").strip()
    if not model_id:
        return {"configured": False, "resolvable": False, "reason": "未配置"}
    p = Path(model_id)
    if p.is_dir():
        complete = any(p.glob("config.json")) and _has_weights(p)
        if complete:
            return {"configured": True, "resolvable": True,
                    "reason": "本地目录可用", "path": str(p)}
        return {"configured": True, "resolvable": False,
                "reason": "本地目录下载不完整（缺权重文件），可续传下载",
                "path": str(p)}
    from . import config as _config
    safe_name = _model_cache_name(model_id, revision)
    cache_dir = _config.DATA_DIR / "models" / safe_name
    if cache_dir.is_dir() and any(cache_dir.glob("config.json")):
        if _has_weights(cache_dir):
            return {"configured": True, "resolvable": True, "reason": "缓存已下载",
                    "path": str(cache_dir)}
        return {"configured": True, "resolvable": False,
                "reason": f"缓存下载不完整（仅 {_dir_size_mb(cache_dir)} MB），可续传下载",
                "path": str(cache_dir)}
    return {"configured": True, "resolvable": False,
            "reason": "未下载，将在首次索引时自动下载",
            "path": str(cache_dir)}


def model_content_fingerprint(model_id: str) -> str:
    """给本地快照生成稳定指纹，防止同名目录内容变化后被当作同一向量空间。"""
    probe = probe_local_model(model_id)
    path = Path(probe.get("path") or "")
    if not probe.get("resolvable") or not path.is_dir():
        return ""
    digest = hashlib.sha256()
    for child in sorted(path.rglob("*")):
        if not child.is_file():
            continue
        rel = child.relative_to(path).as_posix()
        if (rel == "config.json" or rel == "tokenizer_config.json"
                or child.suffix == ".safetensors"):
            digest.update(rel.encode("utf-8"))
            digest.update(str(child.stat().st_size).encode("ascii"))
            if child.stat().st_size < 2 * 1024 * 1024:
                digest.update(child.read_bytes())
    return "snapshot:" + digest.hexdigest()[:24]


# ------------------------------------------------------------------
# 后台下载（设置页“下载模型”按钮用；失败手动重试，不自动重试）
# ------------------------------------------------------------------
# 状态机：idle|downloading|ready|failed。进度以后端目录大小增长为代理
# （snapshot_download 无可靠字节回调，不编造百分比，只报状态 + 已下 MB）。
# 状态落盘 ``data/models/.status_<safe>.json``（跨 worker/刷新可读）；
# 内存 dict 做同进程镜像。DB 不写：worker 线程无事件循环，且避开锁竞争。
_DL_STATUS: Dict[str, Dict[str, Any]] = {}
_DL_THREADS: Dict[str, threading.Thread] = {}
_DL_LOCK = threading.RLock()  # 可重入：持锁路径内可再读/写状态，避免同线程死锁


def _sanitize_model_id(model_id: str) -> str:
    return (model_id or "").strip().replace("/", "_").replace("\\", "_")


def _download_status_path(model_id: str) -> Optional[Path]:
    try:
        from . import config as _config
        return _config.DATA_DIR / "models" / f".status_{_sanitize_model_id(model_id)}.json"
    except Exception:
        return None


def _write_download_status(model_id: str, state: str, size_mb: float = 0.0,
                           error: str = "") -> Dict[str, Any]:
    import json as _json
    import time as _time
    payload = {"model": model_id, "state": state, "sizeMB": size_mb,
               "error": error, "updatedAt": int(_time.time() * 1000)}
    with _DL_LOCK:
        _DL_STATUS[model_id] = payload
    sp = _download_status_path(model_id)
    if sp is not None:
        try:
            sp.parent.mkdir(parents=True, exist_ok=True)
            sp.write_text(_json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
    return payload


def get_download_status(model_id: str) -> Dict[str, Any]:
    """查询下载状态（读盘为准，内存回退；无记录即 idle）。"""
    import json as _json
    model_id = (model_id or "").strip()
    if not model_id:
        return {"model": model_id, "state": "idle", "sizeMB": 0.0, "error": ""}
    sp = _download_status_path(model_id)
    if sp is not None:
        try:
            if sp.exists():
                data = _json.loads(sp.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("state"):
                    with _DL_LOCK:
                        _DL_STATUS[model_id] = data
                    return data
        except Exception:
            pass
    with _DL_LOCK:
        hit = _DL_STATUS.get(model_id)
    if hit:
        return hit
    return {"model": model_id, "state": "idle", "sizeMB": 0.0, "error": ""}


def _download_worker(model_id: str, target_dir: Path, revision: str = "") -> None:
    """后台下载线程体：ticker 刷大小 + 主流程下载，结束落 ready/failed。"""
    import time as _time
    stop = threading.Event()

    def _ticker() -> None:
        while not stop.wait(2.0):
            try:
                _write_download_status(model_id, "downloading", _dir_size_mb(target_dir))
            except Exception:
                pass

    tick = threading.Thread(target=_ticker, name=f"embed-dl-tick-{_sanitize_model_id(model_id)[:16]}",
                            daemon=True)
    tick.start()
    try:
        get_local_embedder()._download_modelscope(model_id, target_dir, revision)
        # 下载后校验完整性（config.json + 权重文件），残缺判失败避免“假完成”
        if target_dir.is_dir() and any(target_dir.glob("config.json")) \
                and _has_weights(target_dir):
            _write_download_status(model_id, "ready", _dir_size_mb(target_dir))
        else:
            _write_download_status(model_id, "failed", _dir_size_mb(target_dir),
                                   error="下载不完整（缺少 config.json 或权重文件），可重试续传")
    except Exception as exc:  # noqa: BLE001 - 失败只落状态，由用户手动重试
        _write_download_status(model_id, "failed", _dir_size_mb(target_dir),
                               error=str(exc)[:200])
    finally:
        stop.set()
        with _DL_LOCK:
            _DL_THREADS.pop(model_id, None)


def download_in_background(model_id: str, revision: str = "") -> Dict[str, Any]:
    """提交后台下载（幂等：已下载直返 ready；下载中直返现状；失败可重调重试）。

    纯本地目录（is_dir）不走下载：完整即 ready，否则 failed 明示。
    全局单飞行（T4）：已有其它模型在下载时，新提交直接回 busy（不排队），
    避免多 GB 任务抢带宽/磁盘。
    """
    model_id = (model_id or "").strip()
    if not model_id:
        return {"model": model_id, "state": "failed", "sizeMB": 0.0,
                "error": "模型 ID 为空"}
    probe = probe_local_model(model_id, revision)
    if probe.get("resolvable"):
        return _write_download_status(model_id, "ready",
                                      _dir_size_mb(Path(probe["path"])))
    if Path(model_id).is_dir():
        # 本地目录但不完整：下载也救不了，直接失败
        return _write_download_status(model_id, "failed", 0.0,
                                      error=probe.get("reason", "本地目录不可用"))
    with _DL_LOCK:
        running = _DL_THREADS.get(model_id)
        if running is not None and running.is_alive():
            return get_download_status(model_id)
        for other_id, th in list(_DL_THREADS.items()):
            if other_id != model_id and th.is_alive():
                cur = get_download_status(other_id)
                return {"model": model_id, "state": "busy", "sizeMB": 0.0,
                        "error": "", "activeModel": other_id,
                        "activeSizeMB": cur.get("sizeMB", 0.0)}
        from . import config as _config
        target_dir = _config.DATA_DIR / "models" / _model_cache_name(model_id, revision)
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return _write_download_status(model_id, "failed", 0.0, error=str(exc)[:200])
        _write_download_status(model_id, "downloading", _dir_size_mb(target_dir))
        t = threading.Thread(target=_download_worker, args=(model_id, target_dir, revision),
                             name=f"embed-dl-{_sanitize_model_id(model_id)[:16]}",
                             daemon=True)
        _DL_THREADS[model_id] = t
        t.start()
        return get_download_status(model_id)


# 心跳过期阈值：ticker 正常 2s 一跳；超此未更新视为任务已死（进程重启等）。
_DL_STALE_SEC = 300


def get_active_download() -> Optional[Dict[str, Any]]:
    """查找正在进行的下载（供切 Hub 回来后恢复轮询，T1）。

    扫描全部 ``.status_*.json``：``downloading`` 但心跳过期（> 5min 未更新）
    就地改写为 failed（中断可重试），避免状态文件永久说谎。
    无进行中任务返回 None。
    """
    import json as _json
    import time as _time
    try:
        from . import config as _config
        models_dir = _config.DATA_DIR / "models"
        if not models_dir.is_dir():
            return None
        now = int(_time.time() * 1000)
        for sp in sorted(models_dir.glob(".status_*.json")):
            try:
                data = _json.loads(sp.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict) or data.get("state") != "downloading":
                continue
            model = str(data.get("model") or "")
            age_sec = (now - int(data.get("updatedAt") or 0)) / 1000.0
            if age_sec > _DL_STALE_SEC:
                data = _write_download_status(
                    model or sp.stem[len(".status_"):], "failed",
                    float(data.get("sizeMB") or 0.0),
                    error="下载中断（服务重启或任务丢失），可重试续传")
                with _DL_LOCK:
                    _DL_THREADS.pop(model, None)
                continue
            with _DL_LOCK:
                _DL_STATUS[model] = data
            return data
    except Exception:
        return None
    return None


__all__ = ["LocalEmbedder", "get_local_embedder", "scan_local_models", "probe_local_model",
           "download_in_background", "get_download_status", "get_active_download"]
