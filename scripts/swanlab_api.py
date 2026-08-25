#!/usr/bin/env python3
"""
SwanLab API 接口 - 用于前端调用
提供从 SwanLab 拉取实验数据的接口
"""

import sys
import json
from swanlab_integration import (
    SwanLabIntegration,
    save_config,
    load_config,
    get_full_config
)


def main():
    if len(sys.argv) < 2:
        print(json.dumps({"success": False, "error": "No action specified"}))
        sys.exit(1)
    
    action = sys.argv[1]
    params = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    
    # 加载配置
    config = get_full_config()
    
    if action == "get_config":
        # 获取配置（不包含 API Key）
        config_info = load_config()
        if config_info:
            print(json.dumps({
                "success": True,
                "config": config_info
            }))
        else:
            print(json.dumps({
                "success": True,
                "config": None
            }))
    
    elif action == "save_config":
        # 保存配置
        api_key = params.get("apiKey", "")
        api_url = params.get("apiUrl", "https://api.swanlab.cn/api")
        enabled = params.get("enabled", True)
        default_workspace = params.get("defaultWorkspace")
        
        if not api_key.strip():
            print(json.dumps({
                "success": False,
                "error": "API Key 不能为空"
            }))
            sys.exit(1)
        
        success = save_config(
            api_key=api_key,
            api_url=api_url,
            enabled=enabled,
            default_workspace=default_workspace
        )
        
        if success:
            print(json.dumps({
                "success": True,
                "message": "配置保存成功"
            }))
        else:
            print(json.dumps({
                "success": False,
                "error": "保存配置失败"
            }))
    
    elif action == "test_connection":
        # 测试连接
        api_key = params.get("apiKey")
        api_url = params.get("apiUrl", "https://api.swanlab.cn/api")
        
        if not api_key and config:
            api_key = config.get("api_key")
        
        if not api_key:
            print(json.dumps({
                "success": False,
                "message": "未配置 API Key"
            }))
            sys.exit(1)
        
        integration = SwanLabIntegration(api_key=api_key, api_url=api_url)
        result = integration.test_connection()
        print(json.dumps(result))
    
    elif action == "fetch_data":
        # 从 SwanLab 拉取所有数据
        if not config or not config.get("api_key"):
            print(json.dumps({
                "success": False,
                "error": "未配置 API Key，请先配置"
            }))
            sys.exit(1)
        
        integration = SwanLabIntegration(
            api_key=config.get("api_key"),
            api_url=config.get("api_url", "https://api.swanlab.cn/api")
        )
        
        username = params.get("username") or config.get("default_workspace")
        
        try:
            data = integration.fetch_all_data(username=username)
            print(json.dumps({
                "success": True,
                "data": data,
                "message": f"成功获取 {len(data['experiments'])} 个实验"
            }))
        except Exception as e:
            print(json.dumps({
                "success": False,
                "error": str(e)
            }))
    
    elif action == "list_workspaces":
        # 获取工作空间列表
        if not config or not config.get("api_key"):
            print(json.dumps({
                "success": False,
                "error": "未配置 API Key"
            }))
            sys.exit(1)
        
        integration = SwanLabIntegration(
            api_key=config.get("api_key"),
            api_url=config.get("api_url", "https://api.swanlab.cn/api")
        )
        
        workspaces = integration.list_workspaces()
        print(json.dumps({
            "success": True,
            "workspaces": workspaces
        }))
    
    elif action == "list_projects":
        # 获取项目列表
        if not config or not config.get("api_key"):
            print(json.dumps({
                "success": False,
                "error": "未配置 API Key"
            }))
            sys.exit(1)
        
        integration = SwanLabIntegration(
            api_key=config.get("api_key"),
            api_url=config.get("api_url", "https://api.swanlab.cn/api")
        )
        
        username = params.get("username") or config.get("default_workspace")
        projects = integration.list_projects(username=username)
        
        print(json.dumps({
            "success": True,
            "projects": projects
        }))
    
    elif action == "list_experiments":
        # 获取实验列表
        if not config or not config.get("api_key"):
            print(json.dumps({
                "success": False,
                "error": "未配置 API Key"
            }))
            sys.exit(1)
        
        project = params.get("project")
        if not project:
            print(json.dumps({
                "success": False,
                "error": "缺少 project 参数"
            }))
            sys.exit(1)
        
        integration = SwanLabIntegration(
            api_key=config.get("api_key"),
            api_url=config.get("api_url", "https://api.swanlab.cn/api")
        )
        
        username = params.get("username") or config.get("default_workspace")
        experiments = integration.list_experiments(project=project, username=username)
        
        print(json.dumps({
            "success": True,
            "experiments": experiments
        }))
    
    elif action == "get_experiment_detail":
        # 获取实验详情
        if not config or not config.get("api_key"):
            print(json.dumps({
                "success": False,
                "error": "未配置 API Key"
            }))
            sys.exit(1)
        
        project = params.get("project")
        exp_id = params.get("expId")
        
        if not project or not exp_id:
            print(json.dumps({
                "success": False,
                "error": "缺少 project 或 expId 参数"
            }))
            sys.exit(1)
        
        integration = SwanLabIntegration(
            api_key=config.get("api_key"),
            api_url=config.get("api_url", "https://api.swanlab.cn/api")
        )
        
        username = params.get("username") or config.get("default_workspace")
        
        # 获取实验详情
        detail = integration.get_experiment_detail(
            project=project,
            exp_id=exp_id,
            username=username
        )
        
        # 获取实验摘要
        summary = integration.get_experiment_summary(
            project=project,
            exp_id=exp_id,
            username=username
        )
        
        print(json.dumps({
            "success": True,
            "experiment": detail,
            "summary": summary
        }))
    
    elif action == "get_cached_data":
        # 获取缓存的数据
        integration = SwanLabIntegration()
        data = integration.load_cached_data()
        
        if data:
            print(json.dumps({
                "success": True,
                "data": data
            }))
        else:
            print(json.dumps({
                "success": False,
                "error": "没有缓存数据"
            }))
    
    elif action == "check_status":
        # 检查集成状态
        config_info = load_config()
        
        status = {
            "configured": config_info is not None and config_info.get("api_key_configured", False),
            "enabled": config_info.get("enabled", False) if config_info else False,
            "default_workspace": config_info.get("default_workspace") if config_info else None
        }
        
        # 如果有配置，测试连接
        if status["configured"] and config:
            integration = SwanLabIntegration(
                api_key=config.get("api_key"),
                api_url=config.get("api_url", "https://api.swanlab.cn/api")
            )
            test_result = integration.test_connection()
            status["connection"] = "connected" if test_result.get("success") else "disconnected"
            status["workspaces"] = test_result.get("workspaces", 0)
        else:
            status["connection"] = "not_configured"
        
        print(json.dumps({
            "success": True,
            "status": status
        }))
    
    else:
        print(json.dumps({
            "success": False,
            "error": f"Unknown action: {action}"
        }))
        sys.exit(1)


if __name__ == "__main__":
    main()