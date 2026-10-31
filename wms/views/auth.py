from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from ..models import NguoiDung
from ..services import audit


def login_view(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    ctx = {"error": None, "username": ""}
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        ctx["username"] = username
        user_db = NguoiDung.objects.filter(ten_dang_nhap=username).first()

        if not username or not password:
            ctx["error"] = "Vui lòng nhập đầy đủ tên đăng nhập và mật khẩu."
        elif user_db and not user_db.is_active:
            ctx["error"] = "Tài khoản đã bị vô hiệu hóa. Vui lòng liên hệ Quản trị viên."
        elif user_db and user_db.is_locked:
            ctx["error"] = (
                f"Tài khoản đã bị tạm khóa do nhập sai mật khẩu quá {NguoiDung.MAX_SAI} lần. "
                "Vui lòng liên hệ Quản trị viên để mở khóa."
            )
            ctx["locked"] = True
        else:
            user = authenticate(request, username=username, password=password)
            if user:
                user.so_lan_sai = 0
                user.save(update_fields=["so_lan_sai"])
                login(request, user)
                audit(request, "DANG_NHAP", "nguoi_dung", user.pk)
                nxt = request.GET.get("next") or "/"
                if not url_has_allowed_host_and_scheme(nxt, {request.get_host()}):
                    nxt = "/"
                return redirect(nxt)
            if user_db:
                user_db.so_lan_sai += 1
                if user_db.so_lan_sai >= NguoiDung.MAX_SAI:
                    user_db.is_locked = True
                    ctx["error"] = (
                        f"Bạn đã nhập sai mật khẩu {user_db.so_lan_sai} lần liên tiếp. "
                        "Tài khoản đã bị tạm khóa — vui lòng liên hệ Quản trị viên."
                    )
                    ctx["locked"] = True
                    audit(user_db, "KHOA_TU_DONG", "nguoi_dung", user_db.pk, "Sai mật khẩu quá số lần cho phép")
                else:
                    con_lai = NguoiDung.MAX_SAI - user_db.so_lan_sai
                    ctx["error"] = f"Tên đăng nhập hoặc mật khẩu không đúng. Bạn còn {con_lai} lần thử."
                user_db.save(update_fields=["so_lan_sai", "is_locked"])
            else:
                ctx["error"] = "Tên đăng nhập hoặc mật khẩu không đúng."
    return render(request, "auth/login.html", ctx)


@require_POST
def logout_view(request):
    logout(request)
    return redirect("login")
