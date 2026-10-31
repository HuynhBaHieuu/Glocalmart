from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect


def admin_required(view):
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_admin:
            messages.error(request, "Bạn không có quyền thực hiện thao tác này (chỉ Quản trị viên).")
            return redirect(request.META.get("HTTP_REFERER") or "/")
        return view(request, *args, **kwargs)

    return wrapper
