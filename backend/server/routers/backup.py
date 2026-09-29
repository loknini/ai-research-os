"""备份 HTTP 路由：权限、上传字段和服务结果映射。"""
from fastapi import APIRouter, Depends, File, UploadFile

from ..core.admin_access import require_admin
from ..services import backup as backup_service

router = APIRouter(
    prefix="/api/backup",
    tags=["backup"],
    dependencies=[Depends(require_admin)],
)

# 应用启动时仍从历史路由模块导入恢复函数，保留该公开入口。
recover_interrupted_import = backup_service.recover_interrupted_import


@router.post("/export")
async def export_backup():
    return await backup_service.export_backup()


@router.post("/import")
async def import_backup(file: UploadFile = File(...)):
    return await backup_service.import_backup(file)


__all__ = ["recover_interrupted_import", "router"]
