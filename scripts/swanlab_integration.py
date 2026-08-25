#!/usr/bin/env python3
"""
SwanLab 数据拉取集成模块
从 SwanLab 云/私有化部署拉取实验数据
"""

import json
import os
from pathlib import Path
from typing import List, Dict, Optional, Any
from datetime import datetime

# 配置存储路径
DATA_DIR = Path(os.environ.get('DATA_DIR', '../data'))
SWANLAB_CONFIG_FILE = DATA_DIR / '.swanlab' / 'config.json'
SWANLAB_CACHE_FILE = DATA_DIR / '.swanlab' / 'cache.json'

# 确保目录存在
(DATA_DIR / '.swanlab').mkdir(parents=True, exist_ok=True)


class SwanLabIntegration:
    """SwanLab 数据集成类 - 用于从 SwanLab 拉取实验数据"""
    
    def __init__(self, api_key: Optional[str] = None, api_url: Optional[str] = None):
        """
        初始化 SwanLab 集成
        
        Args:
            api_key: SwanLab API Key，如果为 None 则从配置文件读取
            api_url: SwanLab API URL，如果为 None 则使用默认
        """
        self.api_key = api_key
        self.api_url = api_url or "https://api.swanlab.cn/api"
        self._api = None
        
    def _get_api(self):
        """获取 SwanLab OpenAPI 实例（延迟加载）"""
        if self._api is None:
            try:
                from swanlab import OpenApi
                if self.api_key:
                    self._api = OpenApi(api_key=self.api_key)
                else:
                    self._api = OpenApi()
            except ImportError:
                raise ImportError("请安装 swanlab: pip install swanlab")
        return self._api
    
    def test_connection(self) -> Dict[str, Any]:
        """测试与 SwanLab 的连接"""
        try:
            api = self._get_api()
            # 尝试获取工作空间列表来测试连接
            response = api.list_workspaces()
            if response.code == 200:
                return {
                    "success": True,
                    "message": "连接成功",
                    "workspaces": len(response.data) if response.data else 0
                }
            else:
                return {
                    "success": False,
                    "message": f"连接失败: {response.errmsg}"
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"连接错误: {str(e)}"
            }
    
    def list_workspaces(self) -> List[Dict[str, str]]:
        """获取工作空间列表"""
        try:
            api = self._get_api()
            response = api.list_workspaces()
            if response.code == 200 and response.data:
                return [
                    {
                        "name": ws.get("name", ""),
                        "username": ws.get("username", ""),
                        "role": ws.get("role", "")
                    }
                    for ws in response.data
                ]
            return []
        except Exception as e:
            print(f"[SwanLab] 获取工作空间失败: {e}")
            return []
    
    def list_projects(self, username: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取项目列表
        
        Args:
            username: 工作空间用户名，默认为当前用户
        """
        try:
            api = self._get_api()
            response = api.list_projects(username=username)
            if response.code == 200 and response.data:
                projects = []
                for proj in response.data:
                    projects.append({
                        "cuid": proj.cuid,
                        "name": proj.name,
                        "description": proj.description or "",
                        "visibility": proj.visibility,
                        "createdAt": proj.createdAt,
                        "updatedAt": proj.updatedAt,
                        "group": proj.group,
                        "count": proj.count
                    })
                return projects
            return []
        except Exception as e:
            print(f"[SwanLab] 获取项目列表失败: {e}")
            return []
    
    def list_experiments(self, project: str, username: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        获取指定项目的实验列表
        
        Args:
            project: 项目名称
            username: 工作空间用户名
        """
        try:
            api = self._get_api()
            response = api.list_experiments(project=project, username=username)
            if response.code == 200 and response.data:
                experiments = []
                for exp in response.data:
                    experiments.append({
                        "cuid": exp.cuid,
                        "name": exp.name,
                        "description": exp.description or "",
                        "state": exp.state,
                        "show": exp.show,
                        "createdAt": exp.createdAt,
                        "finishedAt": exp.finishedAt,
                        "user": exp.user,
                        "profile": exp.profile
                    })
                return experiments
            return []
        except Exception as e:
            print(f"[SwanLab] 获取实验列表失败: {e}")
            return []
    
    def get_experiment_detail(self, project: str, exp_id: str, 
                             username: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        获取实验详情
        
        Args:
            project: 项目名称
            exp_id: 实验 CUID
            username: 工作空间用户名
        """
        try:
            api = self._get_api()
            response = api.get_experiment(project=project, exp_id=exp_id, username=username)
            if response.code == 200 and response.data:
                exp = response.data
                return {
                    "cuid": exp.cuid,
                    "name": exp.name,
                    "description": exp.description or "",
                    "state": exp.state,
                    "show": exp.show,
                    "createdAt": exp.createdAt,
                    "finishedAt": exp.finishedAt,
                    "user": exp.user,
                    "profile": exp.profile
                }
            return None
        except Exception as e:
            print(f"[SwanLab] 获取实验详情失败: {e}")
            return None
    
    def get_experiment_summary(self, project: str, exp_id: str,
                               username: Optional[str] = None) -> Dict[str, Any]:
        """
        获取实验指标摘要（包含最终值、最小/最大值）
        
        Args:
            project: 项目名称
            exp_id: 实验 CUID
            username: 工作空间用户名
            
        Returns:
            指标摘要字典，如 {"loss": {"step": 47, "value": 0.19, "min": {...}, "max": {...}}}
        """
        try:
            api = self._get_api()
            response = api.get_summary(project=project, exp_id=exp_id, username=username)
            if response.code == 200 and response.data:
                return response.data
            return {}
        except Exception as e:
            print(f"[SwanLab] 获取实验摘要失败: {e}")
            return {}
    
    def fetch_all_data(self, username: Optional[str] = None) -> Dict[str, Any]:
        """
        获取所有数据（工作空间、项目、实验）
        
        Returns:
            包含所有数据的字典
        """
        result = {
            "timestamp": int(datetime.now().timestamp()),
            "workspaces": [],
            "projects": [],
            "experiments": []
        }
        
        # 获取工作空间
        workspaces = self.list_workspaces()
        result["workspaces"] = workspaces
        
        # 获取每个工作空间的项目
        for ws in workspaces:
            ws_username = ws.get("username")
            projects = self.list_projects(username=ws_username)
            
            for proj in projects:
                proj_info = {
                    **proj,
                    "workspace": ws
                }
                result["projects"].append(proj_info)
                
                # 获取每个项目的实验
                experiments = self.list_experiments(
                    project=proj["name"],
                    username=ws_username
                )
                
                for exp in experiments:
                    # 获取实验摘要
                    summary = self.get_experiment_summary(
                        project=proj["name"],
                        exp_id=exp["cuid"],
                        username=ws_username
                    )
                    
                    exp_info = {
                        **exp,
                        "project": proj["name"],
                        "workspace": ws,
                        "summary": summary
                    }
                    result["experiments"].append(exp_info)
        
        # 缓存数据
        self._cache_data(result)
        
        return result
    
    def _cache_data(self, data: Dict[str, Any]):
        """缓存数据到本地"""
        try:
            with open(SWANLAB_CACHE_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"[SwanLab] 缓存数据失败: {e}")
    
    def load_cached_data(self) -> Optional[Dict[str, Any]]:
        """从本地缓存加载数据"""
        try:
            if SWANLAB_CACHE_FILE.exists():
                with open(SWANLAB_CACHE_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
            return None
        except Exception as e:
            print(f"[SwanLab] 加载缓存失败: {e}")
            return None


def save_config(api_key: str, api_url: str = "https://api.swanlab.cn/api",
                enabled: bool = True, default_workspace: Optional[str] = None) -> bool:
    """保存 SwanLab 配置"""
    try:
        config = {
            "api_key": api_key,
            "api_url": api_url,
            "enabled": enabled,
            "default_workspace": default_workspace,
            "updated_at": int(datetime.now().timestamp())
        }
        
        # 简单加密（仅做基本保护）
        import base64
        encoded = base64.b64encode(json.dumps(config).encode()).decode()
        
        with open(SWANLAB_CONFIG_FILE, 'w') as f:
            f.write(encoded)
        
        return True
    except Exception as e:
        print(f"[SwanLab] 保存配置失败: {e}")
        return False


def load_config() -> Optional[Dict[str, Any]]:
    """加载 SwanLab 配置"""
    try:
        if not SWANLAB_CONFIG_FILE.exists():
            return None
        
        with open(SWANLAB_CONFIG_FILE, 'r') as f:
            encoded = f.read()
        
        import base64
        decoded = base64.b64decode(encoded).decode()
        config = json.loads(decoded)
        
        # 返回配置（不包含完整 api_key）
        return {
            "api_url": config.get("api_url", "https://api.swanlab.cn/api"),
            "enabled": config.get("enabled", False),
            "default_workspace": config.get("default_workspace"),
            "api_key_configured": bool(config.get("api_key")),
            "updated_at": config.get("updated_at")
        }
    except Exception as e:
        print(f"[SwanLab] 加载配置失败: {e}")
        return None


def get_full_config() -> Optional[Dict[str, Any]]:
    """获取完整配置（包含 api_key）"""
    try:
        if not SWANLAB_CONFIG_FILE.exists():
            return None
        
        with open(SWANLAB_CONFIG_FILE, 'r') as f:
            encoded = f.read()
        
        import base64
        decoded = base64.b64decode(encoded).decode()
        return json.loads(decoded)
    except Exception as e:
        print(f"[SwanLab] 加载完整配置失败: {e}")
        return None


if __name__ == "__main__":
    # 测试代码
    print("SwanLab Integration Module")
    print("=" * 50)
    
    # 加载配置
    config = get_full_config()
    if config:
        print(f"配置已加载: {config.get('api_url')}")
        
        # 测试连接
        integration = SwanLabIntegration(
            api_key=config.get("api_key"),
            api_url=config.get("api_url")
        )
        
        result = integration.test_connection()
        print(f"连接测试: {result}")
        
        if result.get("success"):
            # 获取数据
            data = integration.fetch_all_data()
            print(f"工作空间: {len(data['workspaces'])}")
            print(f"项目数: {len(data['projects'])}")
            print(f"实验数: {len(data['experiments'])}")
    else:
        print("未找到配置，请先配置 API Key")