"""Tồn kho an toàn (SS) & điểm đặt hàng lại (ROP): tính lại thủ công và cấu hình — chỉ Quản trị viên."""
from django.contrib import messages
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from ..decorators import admin_required
from ..forms import CauHinhTonKhoForm
from ..models import CauHinhTonKho
from ..services import audit, tinh_ss_rop
from .common import form_errors


@admin_required
@require_POST
def tinh_lai_ss_rop(request):
    tk = tinh_ss_rop()
    audit(request, "TINH_SS_ROP", "san_pham", "", tk)
    messages.success(request, f"Đã tính lại SS/ROP cho {tk['tong']} sản phẩm ({tk['du_du_lieu']} đủ dữ liệu, "
                              f"{tk['chua_du']} chưa đủ dữ liệu).")
    nxt = request.POST.get("next", "")
    ok = url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure())
    return redirect(nxt if nxt and ok else "dashboard")


@admin_required
def cau_hinh_ton_kho(request):
    cfg = CauHinhTonKho.lay()
    form = CauHinhTonKhoForm(request.POST or None, instance=cfg)
    if request.method == "POST":
        if form.is_valid():
            cfg = form.save(commit=False)
            cfg.nguoi_cap_nhat = request.user
            cfg.save()
            audit(request, "SUA", "cau_hinh_ton_kho", cfg.pk, form.cleaned_data)
            if request.POST.get("tinh_lai"):
                tk = tinh_ss_rop()
                messages.success(request, f"Đã lưu cấu hình và tính lại SS/ROP cho {tk['tong']} sản phẩm.")
            else:
                messages.success(request, "Đã lưu cấu hình. Bấm “Tính lại SS/ROP” để áp dụng ngay.")
            return redirect("cau_hinh_ton_kho")
        messages.error(request, "Vui lòng kiểm tra lại các giá trị cấu hình.")
    return render(request, "tonkho/cau_hinh.html", {
        "active": "dashboard",
        "form": form,
        "cfg": cfg,
        "loi": form_errors(form) if form.is_bound else {},
    })
