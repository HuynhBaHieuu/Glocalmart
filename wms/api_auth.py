"""Xác thực API Key cho REST API (tách riêng để tránh import vòng với DRF settings)."""
import hashlib
import secrets

from django.utils import timezone
from rest_framework import authentication, exceptions

from .models import ApiKey


def tao_api_key(ten, user):
    raw = "glm_" + secrets.token_urlsafe(32)
    ApiKey.objects.create(ten=ten, tien_to=raw[:12], key_hash=hashlib.sha256(raw.encode()).hexdigest(), nguoi_tao=user)
    return raw


class ApiClient:
    """Đại diện client đã xác thực (không phải người dùng hệ thống)."""

    is_authenticated = True

    def __init__(self, key):
        self.key = key


class ApiKeyAuthentication(authentication.BaseAuthentication):
    def authenticate(self, request):
        raw = request.headers.get("X-API-Key") or ""
        if not raw:
            auth = request.headers.get("Authorization", "")
            if auth.lower().startswith("api-key "):
                raw = auth[8:].strip()
        if not raw:
            return None
        key = ApiKey.objects.filter(key_hash=hashlib.sha256(raw.encode()).hexdigest(), is_active=True).first()
        if not key:
            raise exceptions.AuthenticationFailed("API Key không hợp lệ hoặc đã bị thu hồi.")
        ApiKey.objects.filter(pk=key.pk).update(lan_dung_cuoi=timezone.now())
        return ApiClient(key), key

    def authenticate_header(self, request):
        return "X-API-Key"
