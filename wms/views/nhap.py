"""Phân hệ Nhập kho: CHO_GIAO → DANG_GIAO → (đối soát) DA_GIAO + DA_XAC_NHAN."""
from datetime import timedelta

from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..decorators import admin_required
from ..models import AuditLog, ChiTietPhieuNhap, NhaCungCap, PhieuNhap, SanPham
from ..services import NghiepVuError, audit, chuyen_trang_thai_giao, luu_nhap_doi_soat, next_doc_code, \
    post_stock_move, xac_nhan_phieu_nhap
from .common import excel_response, paginate, products_json, to_date, to_decimal


def _filter(request):
    qs = PhieuNhap.objects.select_related("id_ncc", "nguoi_tao").prefetch_related("chi_tiet")
    q, tt = request.GET.get("q", "").strip(), request.GET.get("tt", "")
    if q:
        qs = qs.filter(Q(ma_phieu_nhap__icontains=q) | Q(id_ncc__ten_ncc__icontains=q) | Q(nguoi_tao__ho_ten__icontains=q))
    if tt in ("CHO_GIAO", "DANG_GIAO"):
        qs = qs.filter(trang_thai_giao=tt, trang_thai=PhieuNhap.CHUA_XAC_NHAN)
    elif tt == "DA_XAC_NHAN":
        qs = qs.filter(trang_thai=PhieuNhap.DA_XAC_NHAN)
    elif tt == "DA_HUY":
        qs = qs.filter(trang_thai=PhieuNhap.DA_HUY)
    return qs, q, tt


def nhap_list(request):
    qs, q, tt = _filter(request)
    now = timezone.localtime()
    dau_thang = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    dau_thang_truoc = (dau_thang - timedelta(days=1)).replace(day=1)
    thang_nay = PhieuNhap.objects.filter(ngay_tao__gte=dau_thang).count()
    thang_truoc = PhieuNhap.objects.filter(ngay_tao__gte=dau_thang_truoc, ngay_tao__lt=dau_thang).count()
    ctx = {
        "active": "nhap",
        "page": paginate(request, qs, 8),
        "q": q,
        "tt": tt,
        "tong": PhieuNhap.objects.count(),
        "thang_nay": thang_nay,
        "tang_truong": round((thang_nay - thang_truoc) * 100 / thang_truoc) if thang_truoc else None,
        "cho_giao": PhieuNhap.objects.filter(trang_thai=PhieuNhap.CHUA_XAC_NHAN, trang_thai_giao=PhieuNhap.CHO_GIAO).count(),
        "dang_giao": PhieuNhap.objects.filter(trang_thai=PhieuNhap.CHUA_XAC_NHAN, trang_thai_giao=PhieuNhap.DANG_GIAO).count(),
        "da_nhap": PhieuNhap.objects.filter(trang_thai=PhieuNhap.DA_XAC_NHAN).count(),
    }
    return render(request, "nhap/list.html", ctx)


def nhap_export(request):
    rows = []
    for p in _filter(request)[0]:
        rows.append([p.ma_phieu_nhap, p.id_ncc.ten_ncc, timezone.localtime(p.ngay_tao).strftime("%d/%m/%Y %H:%M"),
                     p.nguoi_tao.ho_ten, p.get_trang_thai_giao_display(), p.get_trang_thai_display(), p.tong_tien])
    return excel_response("phieu_nhap.xlsx", "Danh sách phiếu nhập kho",
                          ["Mã phiếu", "Nhà cung cấp", "Ngày tạo", "Người tạo", "Giao hàng", "Trạng thái", "Tổng tiền"], rows)


def nhap_create(request):
    ctx = {
        "active": "nhap",
        "ncc_list": NhaCungCap.objects.filter(trang_thai=1),
        "products": products_json(),
        "ma_du_kien": f"PN-{timezone.localtime().strftime('%y%m')}-####",
        "today": timezone.localdate(),
        "old": None,
    }
    if request.method == "POST":
        ncc = NhaCungCap.objects.filter(pk=request.POST.get("ncc"), trang_thai=1).first()
        ids, sls, gias = request.POST.getlist("sp"), request.POST.getlist("sl"), request.POST.getlist("gia")
        dong, loi = [], []
        if not ncc:
            loi.append("Vui lòng chọn nhà cung cấp đang hoạt động.")
        sps = {str(s.pk): s for s in SanPham.objects.filter(pk__in=[i for i in ids if i.isdigit()], trang_thai=1)}
        for i, sl, gia in zip(ids, sls, gias):
            sp, sl, gia = sps.get(i), to_decimal(sl), to_decimal(gia)
            if not sp:
                loi.append("Có sản phẩm không hợp lệ hoặc đã ngừng kinh doanh.")
                continue
            if sl is None or sl <= 0:
                loi.append(f"{sp.ten_sp}: số lượng đặt phải lớn hơn 0.")
            if gia is None or gia < 0:
                loi.append(f"{sp.ten_sp}: đơn giá nhập không hợp lệ.")
            dong.append((sp, sl, gia))
        if not dong:
            loi.append("Cần chọn ít nhất một sản phẩm.")
        if len({sp.pk for sp, *_ in dong}) != len(dong):
            loi.append("Một sản phẩm chỉ được xuất hiện một lần trong phiếu.")
        if loi:
            for e in dict.fromkeys(loi):
                messages.error(request, e)
            ctx["old"] = {
                "ncc": request.POST.get("ncc", ""),
                "ngay": request.POST.get("ngay_du_kien_nhan", ""),
                "ghi_chu": request.POST.get("ghi_chu", ""),
                "items": [{"id": int(i), "sl": s, "gia": g} for i, s, g in zip(ids, sls, gias) if i.isdigit()],
            }
            return render(request, "nhap/create.html", ctx)
        with transaction.atomic():
            phieu = PhieuNhap.objects.create(
                ma_phieu_nhap=next_doc_code("PN"),
                id_ncc=ncc,
                nguoi_tao=request.user,
                ngay_du_kien_nhan=to_date(request.POST.get("ngay_du_kien_nhan")),
                ghi_chu=request.POST.get("ghi_chu", "").strip() or None,
            )
            ChiTietPhieuNhap.objects.bulk_create([
                ChiTietPhieuNhap(ma_phieu_nhap=phieu, id_sp=sp, so_luong_dat=sl, don_gia_nhap=gia) for sp, sl, gia in dong
            ])
            audit(request, "TAO_PHIEU", "phieu_nhap", phieu.pk, f"{len(dong)} sản phẩm — Chờ giao")
        messages.success(request, f"Đã tạo phiếu nhập {phieu.pk} (trạng thái Chờ giao).")
        return redirect("nhap_detail", ma=phieu.pk)
    return render(request, "nhap/create.html", ctx)


def _lich_su(ma, doi_tuong):
    return AuditLog.objects.filter(doi_tuong=doi_tuong, ma_doi_tuong=ma).select_related("nguoi_dung").order_by("-ngay_tao")


def nhap_detail(request, ma):
    phieu = get_object_or_404(PhieuNhap.objects.select_related("id_ncc", "nguoi_tao", "nguoi_xac_nhan"), pk=ma)
    return render(request, "nhap/detail.html", {
        "active": "nhap",
        "p": phieu,
        "chi_tiet": phieu.chi_tiet.select_related("id_sp"),
        "lich_su": _lich_su(ma, "phieu_nhap"),
        "now": timezone.localtime(),
    })


@require_POST
def nhap_giao_hang(request, ma):
    phieu = get_object_or_404(PhieuNhap, pk=ma)
    moi = request.POST.get("trang_thai_giao")
    try:
        chuyen_trang_thai_giao(phieu, moi, request.user)
        audit(request, "CAP_NHAT_GIAO", "phieu_nhap", ma, f"→ {phieu.get_trang_thai_giao_display()}")
        messages.success(request, f"Đã cập nhật {ma} sang “{phieu.get_trang_thai_giao_display()}”.")
    except (NghiepVuError, ValueError) as e:
        messages.error(request, str(e) if isinstance(e, NghiepVuError) else "Trạng thái không hợp lệ.")
    return redirect("nhap_detail", ma=ma)


def nhap_doi_soat(request, ma):
    phieu = get_object_or_404(PhieuNhap.objects.select_related("id_ncc", "nguoi_tao"), pk=ma)
    if phieu.trang_thai != PhieuNhap.CHUA_XAC_NHAN or phieu.trang_thai_giao != PhieuNhap.DANG_GIAO:
        messages.info(request, "Chỉ đối soát phiếu đang ở trạng thái Đang giao.")
        return redirect("nhap_detail", ma=ma)
    chi_tiet = list(phieu.chi_tiet.select_related("id_sp"))
    if request.method == "POST":
        dong = {}
        for ct in chi_tiet:
            dong[ct.pk] = {
                "sl": to_decimal(request.POST.get(f"sl_{ct.pk}")),
                "hsd": to_date(request.POST.get(f"hsd_{ct.pk}")),
                "ly_do": request.POST.get(f"ly_do_{ct.pk}") or None,
            }
        ghi_chu = request.POST.get("ghi_chu_doi_soat", "").strip() or None
        try:
            if request.POST.get("action") == "xac_nhan":
                xac_nhan_phieu_nhap(ma, dong, request.user, ghi_chu)
                audit(request, "XAC_NHAN", "phieu_nhap", ma, "Đã giao & tự động cập nhật tồn kho")
                messages.success(request, f"{ma}: đã chốt Đã giao và cộng tồn kho thành công.")
                return redirect("nhap_detail", ma=ma)
            luu_nhap_doi_soat(ma, dong, ghi_chu)
            audit(request, "LUU_NHAP_DOI_SOAT", "phieu_nhap", ma)
            messages.success(request, "Đã lưu bản nháp đối soát.")
            return redirect("nhap_doi_soat", ma=ma)
        except NghiepVuError as e:
            messages.error(request, str(e))
            for ct in chi_tiet:  # giữ lại dữ liệu người dùng vừa nhập
                d = dong[ct.pk]
                ct.so_luong_thuc_nhan, ct.han_su_dung, ct.ly_do_chenh_lech = d["sl"], d["hsd"], d["ly_do"]
            phieu.ghi_chu_doi_soat = ghi_chu
    return render(request, "nhap/doi_soat.html", {
        "active": "nhap",
        "p": phieu,
        "chi_tiet": chi_tiet,
        "ly_do": ChiTietPhieuNhap.LY_DO,
        "lich_su": _lich_su(ma, "phieu_nhap"),
    })


def nhap_print(request, ma):
    phieu = get_object_or_404(PhieuNhap.objects.select_related("id_ncc", "nguoi_tao", "nguoi_xac_nhan"), pk=ma)
    return render(request, "nhap/print.html", {"p": phieu, "chi_tiet": phieu.chi_tiet.select_related("id_sp"),
                                               "now": timezone.localtime()})


@require_POST
def nhap_cancel(request, ma):
    """Hủy phiếu kèm lý do. Phiếu đã xác nhận: chỉ Admin, tồn kho được hoàn lại qua post_stock_move."""
    ly_do = request.POST.get("ly_do", "").strip()
    if not ly_do:
        messages.error(request, "Vui lòng nhập lý do hủy phiếu.")
        return redirect("nhap_detail", ma=ma)
    try:
        with transaction.atomic():
            phieu = PhieuNhap.objects.select_for_update().get(pk=ma)
            if phieu.trang_thai == PhieuNhap.DA_HUY:
                raise NghiepVuError("Phiếu đã bị hủy trước đó.")
            if phieu.trang_thai == PhieuNhap.DA_XAC_NHAN:
                if not request.user.is_admin:
                    raise NghiepVuError("Chỉ Quản trị viên được hủy phiếu đã xác nhận.")
                for ct in phieu.chi_tiet.all():
                    if ct.so_luong_thuc_nhan:
                        post_stock_move(san_pham_id=ct.id_sp_id, loai="NHAP_KHO", user=request.user,
                                        delta=-ct.so_luong_thuc_nhan, phieu_nhap=phieu)
            phieu.trang_thai = PhieuNhap.DA_HUY
            phieu.ly_do_huy = ly_do
            phieu.save(update_fields=["trang_thai", "ly_do_huy"])
            audit(request, "HUY", "phieu_nhap", ma, ly_do)
        messages.success(request, f"Đã hủy phiếu {ma}.")
    except NghiepVuError as e:
        messages.error(request, f"Không thể hủy: {e}")
    return redirect("nhap_detail", ma=ma)


@admin_required
@require_POST
def nhap_delete(request, ma):
    phieu = get_object_or_404(PhieuNhap, pk=ma)
    if phieu.trang_thai != PhieuNhap.CHUA_XAC_NHAN or phieu.trang_thai_giao != PhieuNhap.CHO_GIAO:
        messages.error(request, "Chỉ được xóa phiếu nháp (Chờ giao, chưa xác nhận). Phiếu khác hãy dùng chức năng Hủy.")
        return redirect("nhap_detail", ma=ma)
    phieu.delete()
    audit(request, "XOA", "phieu_nhap", ma)
    messages.success(request, f"Đã xóa phiếu nháp {ma}.")
    return redirect("nhap")
