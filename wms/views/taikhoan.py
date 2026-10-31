"""Quản lý tài khoản & phân quyền (Admin), API Key, nhật ký thao tác, đổi mật khẩu."""
from django.contrib import messages
from django.contrib.auth import update_session_auth_hash
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..api_auth import tao_api_key
from ..decorators import admin_required
from ..forms import NguoiDungForm
from ..models import ApiKey, AuditLog, NguoiDung
from ..services import audit
from .common import excel_response, form_errors, paginate


def _filter(request):
    qs = NguoiDung.objects.all()
    q, vt, tt = request.GET.get("q", "").strip(), request.GET.get("vt", ""), request.GET.get("tt", "")
    if q:
        qs = qs.filter(Q(ho_ten__icontains=q) | Q(ten_dang_nhap__icontains=q) | Q(email__icontains=q) | Q(ma_nv__icontains=q))
    if vt:
        qs = qs.filter(vai_tro=vt)
    if tt == "active":
        qs = qs.filter(is_active=True, is_locked=False)
    elif tt == "locked":
        qs = qs.filter(is_locked=True)
    elif tt == "disabled":
        qs = qs.filter(is_active=False)
    return qs, q, vt, tt


@admin_required
def tai_khoan_list(request, form=None, form_pk=None):
    qs, q, vt, tt = _filter(request)
    modal = None
    if form:
        data = {k: v for k, v in form.data.items() if k not in ("csrfmiddlewaretoken", "mat_khau")}
        modal = {"open": True, "pk": form_pk or "", "data": data, "errors": form_errors(form)}
    so_nv = NguoiDung.objects.filter(vai_tro=NguoiDung.NHAN_VIEN).count()
    return render(request, "taikhoan/list.html", {
        "active": "tai_khoan",
        "page": paginate(request, qs, 8),
        "q": q, "vt": vt, "tt": tt,
        "tong": NguoiDung.objects.count(),
        "so_admin": NguoiDung.objects.filter(vai_tro=NguoiDung.ADMIN).count(),
        "so_nv": so_nv,
        "dang_hd": NguoiDung.objects.filter(is_active=True, is_locked=False).count(),
        "bi_khoa": NguoiDung.objects.filter(Q(is_locked=True) | Q(is_active=False)).count(),
        "modal": modal,
        "goi_y_ma": f"NV{so_nv + 1:03d}",
        "max_sai": NguoiDung.MAX_SAI,
    })


@admin_required
@require_POST
def tai_khoan_save(request):
    pk = request.POST.get("pk")
    obj = get_object_or_404(NguoiDung, pk=pk) if pk else None
    form = NguoiDungForm(request.POST, instance=obj)
    if obj and obj.pk == request.user.pk and request.POST.get("vai_tro") != NguoiDung.ADMIN:
        form.is_valid()
        form.add_error("vai_tro", "Không thể tự hạ quyền tài khoản đang đăng nhập")
    if not form.is_valid():
        return tai_khoan_list(request, form, pk)
    user = form.save()
    if user.pk == request.user.pk and form.cleaned_data.get("mat_khau"):
        update_session_auth_hash(request, user)
    audit(request, "SUA" if pk else "THEM", "nguoi_dung", user.pk,
          {k: v for k, v in form.cleaned_data.items() if k != "mat_khau"})
    messages.success(request, f"Đã {'cập nhật' if pk else 'tạo'} tài khoản {user.ten_dang_nhap}.")
    return redirect("tai_khoan")


@admin_required
@require_POST
def tai_khoan_lock(request, pk):
    user = get_object_or_404(NguoiDung, pk=pk)
    if user.pk == request.user.pk:
        messages.error(request, "Không thể khóa tài khoản đang đăng nhập.")
        return redirect("tai_khoan")
    user.is_locked = not user.is_locked
    user.so_lan_sai = 0
    user.save(update_fields=["is_locked", "so_lan_sai", "ngay_cap_nhat"])
    audit(request, "KHOA" if user.is_locked else "MO_KHOA", "nguoi_dung", pk)
    messages.success(request, f"Đã {'khóa' if user.is_locked else 'mở khóa'} tài khoản {user.ten_dang_nhap}.")
    return redirect("tai_khoan")


@admin_required
@require_POST
def tai_khoan_active(request, pk):
    """Vô hiệu hóa mềm (is_active=False) để bảo toàn lịch sử chứng từ."""
    user = get_object_or_404(NguoiDung, pk=pk)
    if user.pk == request.user.pk:
        messages.error(request, "Không thể vô hiệu hóa tài khoản đang đăng nhập.")
        return redirect("tai_khoan")
    user.is_active = not user.is_active
    user.save(update_fields=["is_active", "ngay_cap_nhat"])
    audit(request, "KICH_HOAT" if user.is_active else "VO_HIEU_HOA", "nguoi_dung", pk)
    messages.success(request, f"Đã {'kích hoạt' if user.is_active else 'vô hiệu hóa'} tài khoản {user.ten_dang_nhap}.")
    return redirect("tai_khoan")


@admin_required
def tai_khoan_export(request):
    rows = [[u.ma_nv, u.ten_dang_nhap, u.ho_ten, u.email, u.get_vai_tro_display(),
             "Vô hiệu hóa" if not u.is_active else ("Tạm khóa" if u.is_locked else "Đang hoạt động")]
            for u in _filter(request)[0]]
    return excel_response("tai_khoan.xlsx", "Danh sách tài khoản",
                          ["Mã NV", "Username", "Họ tên", "Email", "Vai trò", "Trạng thái"], rows)


@admin_required
def api_keys(request):
    new_key = None
    if request.method == "POST":
        ten = request.POST.get("ten", "").strip()
        if not ten:
            messages.error(request, "Vui lòng nhập tên ứng dụng.")
        else:
            new_key = tao_api_key(ten, request.user)
            audit(request, "TAO_API_KEY", "api_key", new_key[:12], ten)
    base = request.build_absolute_uri("/api/")
    return render(request, "taikhoan/api_keys.html", {
        "active": "tai_khoan",
        "keys": ApiKey.objects.select_related("nguoi_tao"),
        "new_key": new_key,
        "base": base,
    })


@admin_required
@require_POST
def api_key_revoke(request, pk):
    key = get_object_or_404(ApiKey, pk=pk)
    key.is_active = False
    key.save(update_fields=["is_active"])
    audit(request, "THU_HOI_API_KEY", "api_key", key.tien_to)
    messages.success(request, f"Đã thu hồi API Key “{key.ten}”.")
    return redirect("api_keys")


@admin_required
def audit_logs(request):
    qs = AuditLog.objects.select_related("nguoi_dung")
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(Q(ma_doi_tuong__icontains=q) | Q(hanh_dong__icontains=q) | Q(doi_tuong__icontains=q)
                       | Q(nguoi_dung__ho_ten__icontains=q))
    return render(request, "taikhoan/audit.html", {"active": "tai_khoan", "page": paginate(request, qs, 20), "q": q})


def doi_mat_khau(request):
    err = None
    if request.method == "POST":
        cu, moi, xn = (request.POST.get(k, "") for k in ("cu", "moi", "xac_nhan"))
        if not request.user.check_password(cu):
            err = "Mật khẩu hiện tại không đúng."
        elif len(moi) < 6:
            err = "Mật khẩu mới tối thiểu 6 ký tự."
        elif moi != xn:
            err = "Xác nhận mật khẩu không khớp."
        else:
            request.user.set_password(moi)
            request.user.save()
            update_session_auth_hash(request, request.user)
            audit(request, "DOI_MAT_KHAU", "nguoi_dung", request.user.pk)
            messages.success(request, "Đã đổi mật khẩu thành công.")
            return redirect("dashboard")
    return render(request, "taikhoan/doi_mat_khau.html", {"err": err})
