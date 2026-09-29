"""设置 HTTP 路由：统一管理权限并映射到设置服务。"""
from fastapi import APIRouter, Depends

from ..core.admin_access import require_admin
from ..services import settings as settings_service

router = APIRouter(
    prefix="/api/settings",
    tags=["settings"],
    dependencies=[Depends(require_admin)],
)

router.add_api_route("/llm", settings_service.get_llm_settings, methods=["GET"])
router.add_api_route("/llm", settings_service.save_llm_settings, methods=["POST"])
router.add_api_route(
    "/embed-local-models", settings_service.list_embed_local_models, methods=["GET"]
)
router.add_api_route(
    "/embed-download", settings_service.start_embed_download, methods=["POST"]
)
router.add_api_route(
    "/embed-download-status", settings_service.embed_download_status, methods=["GET"]
)
router.add_api_route(
    "/embed-download-active", settings_service.embed_download_active, methods=["GET"]
)
router.add_api_route("/llm/models", settings_service.list_llm_models, methods=["GET"])
router.add_api_route("/llm/test", settings_service.test_llm_connection, methods=["POST"])
router.add_api_route(
    "/integration", settings_service.get_integration_settings, methods=["GET"]
)
router.add_api_route(
    "/integration", settings_service.save_integration_settings, methods=["POST"]
)

__all__ = ["router"]
