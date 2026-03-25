"""Routes for single-device profile settings and avatar persistence."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from services.profile_settings_service import ProfileSettingsService
from web.schemas import ProfileAvatarUploadPayload, ProfileSettingsPayload


def build_settings_router(profile_settings_service: ProfileSettingsService) -> APIRouter:
    """Create routes for device profile metadata and avatar files."""
    router = APIRouter()

    @router.get("/api/settings/profile")
    def get_profile() -> dict:
        return {"profile": profile_settings_service.get_profile()}

    @router.put("/api/settings/profile")
    def update_profile(payload: ProfileSettingsPayload) -> dict:
        return {
            "profile": profile_settings_service.update_profile(
                name=payload.name,
                role=payload.role,
            )
        }

    @router.post("/api/settings/profile/avatar")
    def upload_profile_avatar(payload: ProfileAvatarUploadPayload) -> dict:
        try:
            profile = profile_settings_service.set_avatar_from_data_url(payload.data_url)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"profile": profile}

    @router.delete("/api/settings/profile/avatar")
    def delete_profile_avatar() -> dict:
        return {"profile": profile_settings_service.clear_avatar()}

    @router.get("/api/settings/profile/avatar")
    def get_profile_avatar() -> FileResponse:
        avatar_path = profile_settings_service.get_avatar_file_path()
        if avatar_path is None:
            raise HTTPException(status_code=404, detail="Avatar not found")
        return FileResponse(
            avatar_path,
            media_type=profile_settings_service.guess_media_type(avatar_path),
            filename=avatar_path.name,
        )

    return router
