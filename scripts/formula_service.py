#!/usr/bin/env python3
"""
Formula OCR Service - SimpleTex 公式识别服务
支持公式识别、历史记录管理

DB 层已迁移到 aiosqlite 异步 + space-key 软隔离：
* 所有公式历史读写按 ``SPACE_ID`` 环境变量（由后端 router 注入）过滤；
* 读写函数均为 ``async``，CLI 入口统一通过 ``asyncio.run`` 驱动。
"""
from __future__ import annotations

import os
import sys
import json
import asyncio
import base64
import requests
from typing import Dict, Any, Optional, List
from datetime import datetime
from pathlib import Path

# 添加父目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import database

# 当前空间（由后端 router 经环境变量注入；缺省走默认空间，保持向后兼容）。
SPACE_ID = os.environ.get("SPACE_ID", database.DEFAULT_SPACE)

# SimpleTex API 配置
SIMPLETEX_BASE_URL = "https://server.simpletex.cn"
SIMPLETEX_TOKEN = os.environ.get('SIMPLETEX_TOKEN', '')

# API 端点
LATEX_OCR_URL = f"{SIMPLETEX_BASE_URL}/api/latex_ocr"
LATEX_OCR_TURBO_URL = f"{SIMPLETEX_BASE_URL}/api/latex_ocr_turbo"
GENERAL_OCR_URL = f"{SIMPLETEX_BASE_URL}/api/simpletex_ocr"
DOC_OCR_URL = f"{SIMPLETEX_BASE_URL}/api/doc_ocr"


def recognize_formula(image_data: bytes, token: str = None, use_turbo: bool = False) -> Dict[str, Any]:
    """识别公式图片（同步 HTTP，无 DB 依赖）。"""
    if not token:
        token = SIMPLETEX_TOKEN

    if not token:
        return {
            "success": False,
            "message": "SimpleTex Token 未配置"
        }

    url = LATEX_OCR_TURBO_URL if use_turbo else LATEX_OCR_URL

    try:
        headers = {"token": token}
        files = {"file": ("formula.png", image_data, "image/png")}

        response = requests.post(url, headers=headers, files=files, timeout=30)
        result = response.json()

        if result.get("status"):
            return {
                "success": True,
                "latex": result["res"]["latex"],
                "confidence": result["res"].get("conf", 0),
                "request_id": result.get("request_id", "")
            }
        else:
            return {
                "success": False,
                "message": result.get("res", {}).get("message", "识别失败")
            }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "message": f"网络请求错误: {str(e)}"
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"识别错误: {str(e)}"
        }


def recognize_document(image_data: bytes, token: str = None) -> Dict[str, Any]:
    """识别文档图片（支持公式 + 文字混排，同步 HTTP，无 DB 依赖）。"""
    if not token:
        token = SIMPLETEX_TOKEN

    if not token:
        return {
            "success": False,
            "message": "SimpleTex Token 未配置"
        }

    try:
        headers = {"token": token}
        files = {"file": ("document.png", image_data, "image/png")}
        data = {"rec_mode": "auto"}

        response = requests.post(GENERAL_OCR_URL, headers=headers, files=files, data=data, timeout=60)
        result = response.json()

        if result.get("status"):
            return {
                "success": True,
                "content": result["res"]["content"],
                "request_id": result.get("request_id", "")
            }
        else:
            return {
                "success": False,
                "message": result.get("res", {}).get("message", "识别失败")
            }

    except requests.exceptions.RequestException as e:
        return {
            "success": False,
            "message": f"网络请求错误: {str(e)}"
        }
    except Exception as e:
        return {
            "success": False,
            "message": f"识别错误: {str(e)}"
        }


async def save_formula_record(record: Dict[str, Any]) -> bool:
    """保存公式识别记录到数据库（按空间归档）。"""
    try:
        async with database.get_db() as conn:
            await conn.execute('''
                INSERT INTO formula_history
                (id, image_data, latex_code, confidence, source_type,
                 is_favorite, tags, note, created_at, space_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                record["id"],
                record.get("image_data"),
                record["latex_code"],
                record.get("confidence", 0),
                record.get("source_type", "upload"),
                record.get("is_favorite", False),
                json.dumps(record.get("tags", [])),
                record.get("note", ""),
                record.get("created_at", int(datetime.now().timestamp() * 1000)),
                SPACE_ID,
            ))
            return True
    except Exception as e:
        print(f"Save formula record error: {e}", file=sys.stderr)
        return False


async def get_formula_history(limit: int = 100, offset: int = 0, favorites_only: bool = False) -> List[Dict[str, Any]]:
    """获取公式识别历史（按空间过滤）。"""
    try:
        async with database.get_db() as conn:
            query = "SELECT * FROM formula_history WHERE space_id = ?"
            params: List[Any] = [SPACE_ID]

            if favorites_only:
                query += " AND is_favorite = 1"

            query += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
            params.extend([limit, offset])

            cur = await conn.execute(query, params)
            rows = await cur.fetchall()

            return [{
                "id": row["id"],
                "latex_code": row["latex_code"],
                "confidence": row["confidence"],
                "source_type": row["source_type"],
                "is_favorite": bool(row["is_favorite"]),
                "tags": json.loads(row["tags"]) if row["tags"] else [],
                "note": row["note"],
                "created_at": row["created_at"]
            } for row in rows]
    except Exception as e:
        print(f"Get formula history error: {e}", file=sys.stderr)
        return []


async def update_formula_record(record_id: str, updates: Dict[str, Any]) -> bool:
    """更新公式记录（同时校验空间归属，避免误改他人数据）。"""
    try:
        async with database.get_db() as conn:
            if "latex_code" in updates:
                await conn.execute(
                    "UPDATE formula_history SET latex_code = ? WHERE id = ? AND space_id = ?",
                    (updates["latex_code"], record_id, SPACE_ID)
                )
            if "is_favorite" in updates:
                await conn.execute(
                    "UPDATE formula_history SET is_favorite = ? WHERE id = ? AND space_id = ?",
                    (updates["is_favorite"], record_id, SPACE_ID)
                )
            if "tags" in updates:
                await conn.execute(
                    "UPDATE formula_history SET tags = ? WHERE id = ? AND space_id = ?",
                    (json.dumps(updates["tags"]), record_id, SPACE_ID)
                )
            if "note" in updates:
                await conn.execute(
                    "UPDATE formula_history SET note = ? WHERE id = ? AND space_id = ?",
                    (updates["note"], record_id, SPACE_ID)
                )
            return True
    except Exception as e:
        print(f"Update formula record error: {e}", file=sys.stderr)
        return False


async def delete_formula_record(record_id: str) -> bool:
    """删除公式记录（同时校验空间归属）。"""
    try:
        async with database.get_db() as conn:
            await conn.execute(
                "DELETE FROM formula_history WHERE id = ? AND space_id = ?",
                (record_id, SPACE_ID)
            )
            return True
    except Exception as e:
        print(f"Delete formula record error: {e}", file=sys.stderr)
        return False


async def get_formula_stats() -> Dict[str, Any]:
    """获取公式识别统计（按空间过滤）。"""
    try:
        async with database.get_db() as conn:
            cur = await conn.execute(
                "SELECT COUNT(*) FROM formula_history WHERE space_id = ?", (SPACE_ID,)
            )
            total = (await cur.fetchone())[0]
            cur = await conn.execute(
                "SELECT COUNT(*) FROM formula_history WHERE space_id = ? AND is_favorite = 1",
                (SPACE_ID,)
            )
            favorites = (await cur.fetchone())[0]

            today_start = int(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp() * 1000)
            cur = await conn.execute(
                "SELECT COUNT(*) FROM formula_history WHERE space_id = ? AND created_at >= ?",
                (SPACE_ID, today_start)
            )
            today_count = (await cur.fetchone())[0]

            return {
                "total": total,
                "favorites": favorites,
                "today": today_count
            }
    except Exception as e:
        print(f"Get formula stats error: {e}", file=sys.stderr)
        return {"total": 0, "favorites": 0, "today": 0}


def process_base64_image(base64_string: str) -> bytes:
    """处理 Base64 编码的图片"""
    if ";base64," in base64_string:
        base64_string = base64_string.split(";base64,")[1]
    return base64.b64decode(base64_string)


async def _run_cli() -> None:
    """CLI 入口：根据动作驱动异步 DB 读写。"""
    if len(sys.argv) < 2:
        print("Usage: python formula_service.py <action> [params]")
        sys.exit(1)

    action = sys.argv[1]

    # 确保库表与 space_id 列就位（幂等）。
    await database.init_db()

    if action == "test" and len(sys.argv) > 2:
        image_path = sys.argv[2]
        token = sys.argv[3] if len(sys.argv) > 3 else ""
        use_turbo = len(sys.argv) > 4 and sys.argv[4] == "true"
        with open(image_path, "rb") as f:
            image_data = f.read()
        result = recognize_formula(image_data, token=token or None, use_turbo=use_turbo)
        if result.get("success"):
            try:
                record_id = f"f_{int(datetime.now().timestamp() * 1000)}_{os.urandom(2).hex()}"
                await save_formula_record({
                    "id": record_id,
                    "latex_code": result.get("latex", ""),
                    "confidence": result.get("confidence", 0),
                    "source_type": "upload",
                    "is_favorite": False,
                    "tags": [],
                    "note": "",
                    "created_at": int(datetime.now().timestamp() * 1000),
                })
                result["record_id"] = record_id
            except Exception as save_err:
                print(f"Save formula record error: {save_err}", file=sys.stderr)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif action == "stats":
        print(json.dumps({"success": True, "stats": await get_formula_stats()}))
    elif action == "history":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 100
        favorites_only = len(sys.argv) > 3 and sys.argv[3] == "true"
        records = await get_formula_history(limit=limit, favorites_only=favorites_only)
        print(json.dumps({"success": True, "records": records}, ensure_ascii=False))
    elif action == "history_update" and len(sys.argv) > 3:
        record_id = sys.argv[2]
        try:
            updates = json.loads(sys.argv[3])
        except json.JSONDecodeError:
            print(json.dumps({"success": False, "error": "Invalid JSON updates"}))
            sys.exit(1)
        ok = await update_formula_record(record_id, updates)
        print(json.dumps({"success": ok, "updated": ok}))
    elif action == "history_delete" and len(sys.argv) > 2:
        ok = await delete_formula_record(sys.argv[2])
        print(json.dumps({"success": ok, "deleted": ok}))
    else:
        print(f"Unknown action: {action}")


if __name__ == "__main__":
    asyncio.run(_run_cli())
