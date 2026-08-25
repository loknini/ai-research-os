#!/usr/bin/env python3
"""
论文总结脚本 - 使用可配置 LLM 客户端（backend/server/llm.py）生成论文中文摘要
"""

import sys
import os
import json
import time
import asyncio
from pathlib import Path
from typing import Optional

# 导入数据库模块（已迁移到 aiosqlite 异步；此处按需在协程中调用）
sys.path.insert(0, str(Path(__file__).parent))
import database

# 可配置 LLM 客户端（后端 llm.py）；独立 CLI 运行且无法导入后端时回退为 None
try:
    from backend.server.llm import llm_client, LLMUnavailableError
except Exception:
    llm_client = None

    class LLMUnavailableError(Exception):
        """LLM 端点不可达时抛出。"""
        pass


def build_summary_prompt(paper: dict) -> str:
    """构建论文 AI 总结所需的 prompt（供后端 ``llm.py`` 复用）。"""
    title = paper.get('title', '')
    abstract = paper.get('abstract', '')
    authors = paper.get('authors', [])
    categories = paper.get('categories', [])
    arxiv_id = paper.get('arxivId', '')
    return f"""请对以下学术论文进行深入的中文分析和总结：

📄 论文信息
- 标题：{title}
- 作者：{', '.join(authors[:5])}{' 等' if len(authors) > 5 else ''}
- arXiv ID：{arxiv_id}
- 分类：{', '.join(categories)}

📝 英文摘要
{abstract}

请提供以下中文总结（使用Markdown格式）：

## 🎯 研究背景与动机
（阐述研究问题、现有方法的不足、本文的切入点）

## 💡 核心方法
（详细描述技术方案、模型架构、关键创新点）

## 🏆 主要贡献
1. （具体贡献1）
2. （具体贡献2）
3. （具体贡献3）

## 📊 实验与结果
（实验设置、数据集、评价指标、与SOTA的对比）

## ✨ 创新亮点
- （创新点1）
- （创新点2）

## ⚠️ 局限性与未来工作
- （局限性1）
- （局限性2）

## 💭 总体评价
（论文质量、学术价值、对领域的影响、可复现性评估）

请确保总结内容具体、有洞察力，不要泛泛而谈。字数控制在800-1200字。"""


def generate_summary_with_llm(paper):
    """使用可配置 LLM 客户端（backend llm.py）生成论文总结。"""
    prompt = build_summary_prompt(paper)
    if llm_client is not None:
        try:
            text = llm_client.call_llm([{"role": "user", "content": prompt}])
            if text:
                return text
        except LLMUnavailableError:
            pass
    return None

def generate_fallback_summary(paper):
    """LLM 调用失败时的备用总结"""
    title = paper.get('title', '')
    abstract = paper.get('abstract', '')
    authors = paper.get('authors', [])
    categories = paper.get('categories', [])
    
    background = abstract.split('.')[0] if abstract else ""
    
    tasks = []
    abstract_lower = abstract.lower()
    if 'detection' in abstract_lower:
        tasks.append("目标检测")
    if 'segmentation' in abstract_lower:
        tasks.append("图像分割")
    if 'generation' in abstract_lower:
        tasks.append("图像生成")
    if 'recognition' in abstract_lower or 'classification' in abstract_lower:
        tasks.append("识别分类")
    if 'tracking' in abstract_lower:
        tasks.append("目标跟踪")
    if 'pose' in abstract_lower:
        tasks.append("姿态估计")
    if not tasks:
        tasks.append("计算机视觉")
    
    methods = []
    if 'transformer' in abstract_lower:
        methods.append("Transformer架构")
    if 'cnn' in abstract_lower or 'convolutional' in abstract_lower:
        methods.append("卷积神经网络")
    if 'diffusion' in abstract_lower:
        methods.append("扩散模型")
    if 'gan' in abstract_lower:
        methods.append("生成对抗网络")
    if 'attention' in abstract_lower:
        methods.append("注意力机制")
    
    is_sota = any(word in abstract_lower for word in ['state-of-the-art', 'sota', 'outperform', 'achieves superior', 'best performance'])
    
    return f"""## 🎯 研究背景与动机

{background}

本文聚焦于**{'、'.join(tasks)}**任务，属于{'/'.join(categories[:2])}研究领域，由{', '.join(authors[:3])}{' 等' if len(authors) > 3 else ''}提出。

## 💡 核心方法

{'作者采用了' + '、'.join(methods) + '等技术。' if methods else '作者提出了一种新的技术方案。'}核心创新在于解决了现有方法在该任务上的关键局限性。

## 🏆 主要贡献

1. 针对{'、'.join(tasks)}任务中的关键挑战，提出了有效的解决方案
2. {'在多个基准数据集上达到了当前最优性能' if is_sota else '通过充分的实验验证了方法的有效性'}
3. 为该领域的后续研究提供了新的思路和技术参考

## 📊 实验与结果

{'实验结果表明，该方法在标准测试集上取得了SOTA性能，显著优于现有方法。' if is_sota else '实验结果验证了该方法的有效性，在相关任务上展现了较好的性能。'}

## ✨ 创新亮点

- 针对现有方法的痛点提出了改进方案
- {'通过创新设计实现了性能突破' if is_sota else '在特定场景下取得了较好的效果'}

## ⚠️ 局限性与未来工作

- 方法的泛化能力需要更多场景验证
- 计算效率和实际部署优化仍有提升空间

## 💭 总体评价

这是一篇关于**{title.split(':')[0] if ':' in title else title}**的{'高质量' if is_sota else '有价值'}研究论文，{'具有较强的创新性和实用价值，对该领域的发展有积极推动作用。' if is_sota else '为该领域提供了新的研究思路和方法参考。'}

---
*⚠️ 提示：此总结基于论文元数据自动生成。如需更精确的 AI 分析，请在「设置 → LLM API 配置」中配置可用的 LLM 端点。*"""

async def main():
    if len(sys.argv) < 2:
        print(json.dumps({
            "success": False,
            "message": "Usage: python summarize_paper.py <paper_id>"
        }, ensure_ascii=False))
        sys.exit(1)
    
    # 确保库表与 space_id 列就位（幂等）
    await database.init_db()

    paper_id = sys.argv[1]
    
    paper = await database.get_paper_by_id(paper_id, space_id=database.DEFAULT_SPACE)
    
    if not paper:
        print(json.dumps({
            "success": False,
            "message": f"Paper not found: {paper_id}"
        }, ensure_ascii=False))
        sys.exit(1)
    
    try:
        summary = generate_summary_with_llm(paper)
        source = "llm"
        
        if not summary:
            print("LLM API not available, using fallback summary", file=sys.stderr)
            summary = generate_fallback_summary(paper)
            source = "fallback"
        
        await database.update_paper(paper_id, {'summary': summary}, space_id=database.DEFAULT_SPACE)
        
        print(json.dumps({
            "success": True,
            "summary": summary,
            "paperId": paper_id,
            "source": source
        }, ensure_ascii=False))
        
    except Exception as e:
        print(json.dumps({
            "success": False,
            "message": str(e)
        }, ensure_ascii=False))
        sys.exit(1)

if __name__ == '__main__':
    asyncio.run(main())
