"""Phân hệ Xuất kho: lập phiếu (CHUA_XAC_NHAN) → xác nhận (trừ tồn)."""
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..decorators import admin_required
from ..models import AuditLog, ChiTietPhieuXuat, PhieuXuat, SanPham
from ..services import NghiepVuError, audit, huy_phieu_xuat, kiem_tra_dong_xuat, next_doc_code, \
    ton_con_han_theo_sp, xac_nhan_phieu_xuat
from .common import paginate, products_json, to_decimal


def xuat_list(request):
    qs = PhieuXuat.objects.select_related("nguoi_tao").prefetch_related("chi_tiet")
    q, tt, ld = request.GET.get("q", "").strip(), request.GET.get("tt", ""), request.GET.get("ld", "")
    if q:
        qs = qs.filter(Q(ma_phieu_xuat__icontains=q) | Q(nguoi_tao__ho_ten__icontains=q) | Q(ghi_chu__icontains=q))
    if tt:
        qs = qs.filter(trang_thai=tt)
    if ld:
        qs = qs.filter(ly_do_xuat=ld)
    return render(request, "xuat/list.html", {
        "active": "xuat",
        "page": paginate(request, qs, 8),
        "q": q, "tt": tt, "ld": ld,
        "tong": PhieuXuat.objects.count(),
        "cho": PhieuXuat.objects.filter(trang_thai=PhieuXuat.CHUA_XAC_NHAN).count(),
        "da": PhieuXuat.objects.filter(trang_thai=PhieuXuat.DA_XAC_NHAN).count(),
        "huy_hang": PhieuXuat.objects.filter(trang_thai=PhieuXuat.DA_XAC_NHAN, ly_do_xuat=PhieuXuat.HUY_HANG).count(),
        "ly_do": PhieuXuat.LY_DO,
        "trang_thai": PhieuXuat.TRANG_THAI,
    })


def xuat_form(request, ma=None):
    phieu = None
    if ma:
        phieu = get_object_or_404(PhieuXuat, pk=ma)
        if phieu.trang_thai != PhieuXuat.CHUA_XAC_NHAN:
            messages.error(request, "Chỉ sửa được phiếu chưa xác nhận.")
            return redirect("xuat_detail", ma=ma)
    ctx = {
        "active": "xuat",
        "p": phieu,
        "products": products_json(SanPham.objects.filter(Q(trang_thai=1) | Q(ton_kho__gt=0))),
        "ly_do": PhieuXuat.LY_DO,
        "ma_du_kien": phieu.pk if phieu else f"PX-{timezone.localtime().strftime('%y%m')}-####",
        "today": timezone.localdate(),
        "old": None,
    }
    if phieu and request.method == "GET":
        ctx["old"] = {
            "ly_do": phieu.ly_do_xuat,
            "ghi_chu": phieu.ghi_chu or "",
            "items": [{"id": ct.id_sp_id, "sl": float(ct.so_luong_xuat)} for ct in phieu.chi_tiet.all()],
        }
    if request.method == "POST":
        ly_do = request.POST.get("ly_do_xuat")
        ids, sls = request.POST.getlist("sp"), request.POST.getlist("sl")
        sps = {str(s.pk): s for s in SanPham.objects.filter(pk__in=[i for i in ids if i.isdigit()])}
        dong = [(sps[i], to_decimal(s, 0)) for i, s in zip(ids, sls) if i in sps]
        try:
            if ly_do not in dict(PhieuXuat.LY_DO):
                raise NghiepVuError("Vui lòng chọn lý do xuất.")
            kiem_tra_dong_xuat(ly_do, dong)
            with transaction.atomic():
                if phieu:
                    phieu.ly_do_xuat = ly_do
                    phieu.ghi_chu = request.POST.get("ghi_chu", "").strip() or None
                    phieu.save()
                    phieu.chi_tiet.all().delete()
                else:
                    phieu = PhieuXuat.objects.create(
                        ma_phieu_xuat=next_doc_code("PX"), nguoi_tao=request.user, ly_do_xuat=ly_do,
                        ghi_chu=request.POST.get("ghi_chu", "").strip() or None,
                    )
                ChiTietPhieuXuat.objects.bulk_create(
                    [ChiTietPhieuXuat(ma_phieu_xuat=phieu, id_sp=sp, so_luong_xuat=sl) for sp, sl in dong]
                )
                audit(request, "SUA_PHIEU" if ma else "TAO_PHIEU", "phieu_xuat", phieu.pk,
                      f"{phieu.get_ly_do_xuat_display()} — {len(dong)} sản phẩm")
            messages.success(request, f"Đã lưu phiếu xuất {phieu.pk}. Kiểm tra và bấm Xác nhận để trừ tồn kho.")
            return redirect("xuat_detail", ma=phieu.pk)
        except NghiepVuError as e:
            messages.error(request, str(e))
            ctx["old"] = {
                "ly_do": ly_do or "",
                "ghi_chu": request.POST.get("ghi_chu", ""),
                "items": [{"id": int(i), "sl": s} for i, s in zip(ids, sls) if i.isdigit()],
            }
    return render(request, "xuat/form.html", ctx)


def xuat_detail(request, ma):
    phieu = get_object_or_404(PhieuXuat.objects.select_related("nguoi_tao", "nguoi_xac_nhan"), pk=ma)
    chi_tiet = list(phieu.chi_tiet.select_related("id_sp").prefetch_related("phan_bo__lo__ma_phieu_nhap"))
    canh_bao = []
    if phieu.trang_thai == PhieuXuat.CHUA_XAC_NHAN:
        con_han = ton_con_han_theo_sp([ct.id_sp_id for ct in chi_tiet])
        for ct in chi_tiet:
            sp = ct.id_sp
            if ct.so_luong_xuat > sp.ton_kho:
                canh_bao.append(f"{sp.ten_sp}: tồn hiện tại chỉ còn {sp.ton_kho.normalize():f} {sp.don_vi}.")
            elif phieu.ly_do_xuat != PhieuXuat.HUY_HANG and ct.so_luong_xuat > con_han.get(sp.pk, 0):
                canh_bao.append(f"{sp.ten_sp}: chỉ còn {con_han.get(sp.pk, 0).normalize():f} {sp.don_vi} thuộc lô còn hạn "
                                "— lô đã hết hạn chỉ được xuất với lý do Hủy hàng.")
    return render(request, "xuat/detail.html", {
        "active": "xuat",
        "p": phieu,
        "chi_tiet": chi_tiet,
        "canh_bao": canh_bao,
        "lich_su": AuditLog.objects.filter(doi_tuong="phieu_xuat", ma_doi_tuong=ma).select_related("nguoi_dung"),
    })


@require_POST
def xuat_confirm(request, ma):
    try:
        xac_nhan_phieu_xuat(ma, request.user)
        audit(request, "XAC_NHAN", "phieu_xuat", ma, "Đã trừ tồn kho")
        messages.success(request, f"Đã xác nhận phiếu {ma} và trừ tồn kho.")
    except NghiepVuError as e:
        messages.error(request, f"Không thể xác nhận: {e}")
    return redirect("xuat_detail", ma=ma)


def xuat_print(request, ma):
    phieu = get_object_or_404(PhieuXuat.objects.select_related("nguoi_tao", "nguoi_xac_nhan"), pk=ma)
    return render(request, "xuat/print.html", {"p": phieu, "chi_tiet": phieu.chi_tiet.select_related("id_sp"),
                                               "now": timezone.localtime()})


@require_POST
def xuat_cancel(request, ma):
    """Hủy phiếu kèm lý do; phiếu đã xác nhận (chỉ Admin) được hoàn tồn về đúng các lô đã lấy."""
    try:
        huy_phieu_xuat(ma, request.user, request.POST.get("ly_do", ""))
        audit(request, "HUY", "phieu_xuat", ma, request.POST.get("ly_do", "").strip())
        messages.success(request, f"Đã hủy phiếu {ma}.")
    except NghiepVuError as e:
        messages.error(request, f"Không thể hủy: {e}")
    return redirect("xuat_detail", ma=ma)


@admin_required
@require_POST
def xuat_delete(request, ma):
    phieu = get_object_or_404(PhieuXuat, pk=ma)
    if phieu.trang_thai != PhieuXuat.CHUA_XAC_NHAN:
        messages.error(request, "Chỉ được xóa phiếu nháp chưa xác nhận. Phiếu đã xác nhận hãy dùng chức năng Hủy.")
        return redirect("xuat_detail", ma=ma)
    phieu.delete()
    audit(request, "XOA", "phieu_xuat", ma)
    messages.success(request, f"Đã xóa phiếu nháp {ma}.")
    return redirect("xuat")
