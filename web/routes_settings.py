"""Routes for single-device profile, avatar, and email settings."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from services.email_service import EmailNotificationService
from services.email_settings_service import EmailSettingsService
from services.profile_settings_service import ProfileSettingsService
from web.schemas import EmailSchemePayload, EmailTestPayload, ProfileAvatarUploadPayload, ProfileSettingsPayload


def build_settings_router(
    profile_settings_service: ProfileSettingsService,
    email_settings_service: EmailSettingsService,
    email_service: EmailNotificationService,
) -> APIRouter:
    """Create routes for device profile metadata, avatar files, and email settings."""
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

    @router.get("/api/settings/email")
    def get_email_settings() -> dict:
        return {"email": email_settings_service.get_settings()}

    @router.post("/api/settings/email/schemes")
    def create_email_scheme(payload: EmailSchemePayload) -> dict:
        try:
            email_settings_service.create_scheme(
                name=payload.name,
                enabled=payload.enabled,
                username=payload.username,
                password=payload.password,
                from_address=payload.from_address,
                recipients=payload.recipients,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"email": email_settings_service.get_settings()}

    @router.put("/api/settings/email/schemes/{scheme_id}")
    def update_email_scheme(scheme_id: int, payload: EmailSchemePayload) -> dict:
        try:
            email_settings_service.update_scheme(
                scheme_id=scheme_id,
                name=payload.name,
                enabled=payload.enabled,
                username=payload.username,
                password=payload.password,
                from_address=payload.from_address,
                recipients=payload.recipients,
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"email": email_settings_service.get_settings()}

    @router.delete("/api/settings/email/schemes/{scheme_id}")
    def delete_email_scheme(scheme_id: int) -> dict:
        try:
            email_settings_service.delete_scheme(scheme_id)
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        return {"email": email_settings_service.get_settings()}

    @router.post("/api/settings/email/test")
    def send_email_test(payload: EmailTestPayload) -> dict:
        try:
            result = email_service.send_test_email(payload.scheme_id)
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"result": result}

    return router
