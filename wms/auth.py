from django.contrib.auth.backends import BaseBackend

from .models import NguoiDung


class LockoutBackend(BaseBackend):
    """Xác thực theo ten_dang_nhap; tài khoản bị khóa / vô hiệu hóa không đăng nhập được.

    Việc đếm số lần sai và khóa tài khoản xử lý trong view đăng nhập để hiển thị thông báo rõ ràng.
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        try:
            user = NguoiDung.objects.get(ten_dang_nhap=username)
        except NguoiDung.DoesNotExist:
            NguoiDung().set_password(password)  # cân bằng thời gian phản hồi
            return None
        if user.is_active and not user.is_locked and user.check_password(password):
            return user
        return None

    def get_user(self, user_id):
        user = NguoiDung.objects.filter(pk=user_id).first()
        if user and user.is_active and not user.is_locked:
            return user
        return None
