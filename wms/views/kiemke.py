"""Kiểm kê mù 2 bước: DANG_KIEM (đếm lần 1 → lần 2 cho dòng lệch) → CHO_DUYET → HOAN_THANH / BI_TU_CHOI."""
from django.contrib import messages
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from ..decorators import admin_required
from ..models import AuditLog, ChiTietPhieuKiemKe, DanhMuc, PhieuKiemKe, SanPham
from ..services import NghiepVuError, audit, dem_lai, duyet_kiem_ke, ghi_dem, gui_duyet, next_doc_code, \
    tu_choi_kiem_ke
from .common import paginate, products_json, to_date, to_decimal


# Danh sách chỉ hiện phiếu đã bấm "Gửi duyệt" trở đi; phiếu đang kiểm (chưa gửi) bị ẩn.
TRANG_THAI_DANH_SACH = [(k, v) for k, v in PhieuKiemKe.TRANG_THAI if k != PhieuKiemKe.DANG_KIEM]


def kiem_list(request):
    hien_thi = [k for k, _ in TRANG_THAI_DANH_SACH]
    qs = (PhieuKiemKe.objects.filter(trang_thai__in=hien_thi)
          .select_related("nguoi_tao", "nguoi_duyet").prefetch_related("chi_tiet"))
    q, tt = request.GET.get("q", "").strip(), request.GET.get("tt", "")
    if tt not in hien_thi:
        tt = ""
    if q:
        qs = qs.filter(Q(ma_phieu_kiem__icontains=q) | Q(nguoi_tao__ho_ten__icontains=q))
    if tt:
        qs = qs.filter(trang_thai=tt)
    return render(request, "kiemke/list.html", {
        "active": "kiem_ke",
        "page": paginate(request, qs, 10),
        "q": q,
        "tt": tt,
        "trang_thai": TRANG_THAI_DANH_SACH,
        "dem": {k: PhieuKiemKe.objects.filter(trang_thai=k).count() for k in hien_thi},
        # phiếu đang đếm dở của chính người dùng — để họ quay lại gửi duyệt (không nằm trong bảng)
        "phieu_dang_kiem": PhieuKiemKe.objects.filter(trang_thai=PhieuKiemKe.DANG_KIEM, nguoi_tao=request.user)
        .values_list("ma_phieu_kiem", flat=True),
    })


def kiem_create(request):
    ctx = {
        "active": "kiem_ke",
        # đếm mù: KHÔNG gửi số tồn hệ thống xuống trình duyệt
        "products": products_json(include_stock=False),
        "danh_muc": [{"id": d.pk, "ten": d.duong_dan} for d in DanhMuc.objects.filter(is_active=True)
                     .select_related("id_dmcha__id_dmcha")],
        "max_sp": PhieuKiemKe.MAX_SAN_PHAM,
        "ma_du_kien": f"KK-{timezone.localtime().strftime('%y%m')}-####",
        "old": None,
    }
    if request.method == "POST":
        ids, sls, notes = request.POST.getlist("sp"), request.POST.getlist("sl"), request.POST.getlist("note")
        try:
            if not ids:
                raise NghiepVuError("Cần chọn ít nhất một sản phẩm để kiểm kê.")
            if len(ids) > PhieuKiemKe.MAX_SAN_PHAM:
                raise NghiepVuError(f"Mỗi phiếu kiểm kê tối đa {PhieuKiemKe.MAX_SAN_PHAM} sản phẩm.")
            if len(set(ids)) != len(ids):
                raise NghiepVuError("Một sản phẩm chỉ được xuất hiện một lần trong phiếu.")
            sps = {str(s.pk): s for s in SanPham.objects.filter(pk__in=[i for i in ids if i.isdigit()])}
            if len(sps) != len(ids):
                raise NghiepVuError("Có sản phẩm không hợp lệ.")
            counts = [to_decimal(s) for s in sls]
            if any(c is None or c < 0 for c in counts):
                raise NghiepVuError("Vui lòng nhập số lượng đếm thực tế (≥ 0) cho tất cả sản phẩm.")
            if any(c != c.to_integral_value() for c in counts):
                raise NghiepVuError("Số lượng đếm phải là số nguyên, không nhập số thập phân.")
            with transaction.atomic():
                phieu = PhieuKiemKe.objects.create(ma_phieu_kiem=next_doc_code("KK"), nguoi_tao=request.user,
                                                   ghi_chu=request.POST.get("ghi_chu", "").strip() or None)
                cts = ChiTietPhieuKiemKe.objects.bulk_create([
                    ChiTietPhieuKiemKe(ma_phieu_kiem=phieu, id_sp=sps[i], don_vi=sps[i].don_vi) for i in ids
                ])
                cts = list(phieu.chi_tiet.order_by("id_chi_tiet"))
                ghi_dem(phieu, 1, {ct.pk: c for ct, c in zip(cts, counts)},
                        {ct.pk: n for ct, n in zip(cts, notes) if n})
                audit(request, "TAO_PHIEU", "phieu_kiem_ke", phieu.pk, f"Đếm lần 1: {len(ids)} sản phẩm")
            phieu.refresh_from_db()
            if phieu.can_dem_lan_2:
                messages.warning(request, "Một số sản phẩm lệch so với hệ thống — vui lòng đếm lại lần 2 cho các dòng được gắn cờ.")
            else:
                messages.success(request, f"Đã lưu kết quả đếm phiếu {phieu.pk}. Bạn có thể gửi duyệt.")
            return redirect("kiem_detail", ma=phieu.pk)
        except NghiepVuError as e:
            messages.error(request, str(e))
            ctx["old"] = {
                "ghi_chu": request.POST.get("ghi_chu", ""),
                "items": [{"id": int(i), "sl": s, "note": n} for i, s, n in zip(ids, sls, notes) if i.isdigit()],
            }
    return render(request, "kiemke/create.html", ctx)


def kiem_detail(request, ma):
    phieu = get_object_or_404(PhieuKiemKe.objects.select_related("nguoi_tao", "nguoi_duyet"), pk=ma)
    chi_tiet = list(phieu.chi_tiet.select_related("id_sp"))
    user = request.user
    if phieu.trang_thai == PhieuKiemKe.DANG_KIEM and not phieu.da_dem_lan_1:
        mode = "dem_lan_1"
    elif phieu.trang_thai == PhieuKiemKe.DANG_KIEM and phieu.can_dem_lan_2:
        mode = "dem_lan_2"
    elif phieu.trang_thai == PhieuKiemKe.CHO_DUYET and user.is_admin:
        mode = "duyet"
    else:
        mode = "xem"
    # Đếm mù: nhân viên không thấy tồn hệ thống khi phiếu còn đang kiểm
    an_he_thong = phieu.trang_thai == PhieuKiemKe.DANG_KIEM and not user.is_admin
    tong_thieu = sum((ct.gia_tri_chenh_lech for ct in chi_tiet if ct.sl_chenh_lech < 0), 0)
    tong_thua = sum((ct.gia_tri_chenh_lech for ct in chi_tiet if ct.sl_chenh_lech > 0), 0)
    return render(request, "kiemke/detail.html", {
        "active": "kiem_ke",
        "p": phieu,
        "chi_tiet": chi_tiet,
        "dong_lech": [ct for ct in chi_tiet if ct.co_chenh_lech],
        "dong_thua": [ct for ct in chi_tiet if ct.sl_thua > 0],
        "mode": mode,
        "an_he_thong": an_he_thong,
        "tong_thieu": tong_thieu,
        "tong_thua": tong_thua,
        "so_lech": sum(1 for ct in chi_tiet if ct.sl_chenh_lech),
        "lich_su": AuditLog.objects.filter(doi_tuong="phieu_kiem_ke", ma_doi_tuong=ma).select_related("nguoi_dung"),
    })


@require_POST
def kiem_dem(request, ma):
    phieu = get_object_or_404(PhieuKiemKe, pk=ma)
    lan = 2 if request.POST.get("lan") == "2" else 1
    so_lieu, ghi_chu = {}, {}
    for ct in phieu.chi_tiet.all():
        if f"sl_{ct.pk}" in request.POST:
            so_lieu[ct.pk] = to_decimal(request.POST.get(f"sl_{ct.pk}"))
        if request.POST.get(f"note_{ct.pk}"):
            ghi_chu[ct.pk] = request.POST[f"note_{ct.pk}"]
    try:
        if any(v is None for v in so_lieu.values()):
            raise NghiepVuError("Vui lòng nhập đầy đủ số lượng đếm.")
        ghi_dem(phieu, lan, so_lieu, ghi_chu)
        audit(request, f"DEM_LAN_{lan}", "phieu_kiem_ke", ma, f"{len(so_lieu)} sản phẩm")
        phieu.refresh_from_db()
        if lan == 1 and phieu.can_dem_lan_2:
            messages.warning(request, "Có sản phẩm lệch so với hệ thống — vui lòng đếm lần 2.")
        else:
            messages.success(request, f"Đã lưu kết quả đếm lần {lan}.")
    except NghiepVuError as e:
        messages.error(request, str(e))
    return redirect("kiem_detail", ma=ma)


@require_POST
def kiem_gui_duyet(request, ma):
    phieu = get_object_or_404(PhieuKiemKe, pk=ma)
    # hạn sử dụng nhân viên nhập tay cho phần hàng thừa (sẽ thành lô mới khi được duyệt)
    hsd_thua = {}
    for ct in phieu.chi_tiet.all():
        if request.POST.get(f"khong_hsd_{ct.pk}"):
            hsd_thua[ct.pk] = None
        elif to_date(request.POST.get(f"hsd_thua_{ct.pk}")):
            hsd_thua[ct.pk] = to_date(request.POST.get(f"hsd_thua_{ct.pk}"))
    try:
        gui_duyet(phieu, hsd_thua)
        audit(request, "GUI_DUYET", "phieu_kiem_ke", ma)
        messages.success(request, f"Đã gửi phiếu {ma} cho Quản lý duyệt.")
    except NghiepVuError as e:
        messages.error(request, str(e))
    return redirect("kiem_detail", ma=ma)


@admin_required
@require_POST
def kiem_duyet(request, ma):
    try:
        duyet_kiem_ke(ma, request.user)
        audit(request, "DUYET", "phieu_kiem_ke", ma, "Cân bằng tồn kho theo số đếm thực tế")
        messages.success(request, f"Đã duyệt {ma} và cân bằng tồn kho theo số đếm thực tế.")
    except NghiepVuError as e:
        messages.error(request, str(e))
    return redirect("kiem_detail", ma=ma)


@admin_required
@require_POST
def kiem_tu_choi(request, ma):
    phieu = get_object_or_404(PhieuKiemKe, pk=ma)
    try:
        tu_choi_kiem_ke(phieu, request.user, request.POST.get("ly_do", ""))
        audit(request, "TU_CHOI", "phieu_kiem_ke", ma, phieu.ly_do_tu_choi)
        messages.success(request, f"Đã từ chối phiếu {ma} và yêu cầu đếm lại.")
    except NghiepVuError as e:
        messages.error(request, str(e))
    return redirect("kiem_detail", ma=ma)


@require_POST
def kiem_dem_lai(request, ma):
    phieu = get_object_or_404(PhieuKiemKe, pk=ma)
    try:
        dem_lai(phieu)
        audit(request, "MO_DEM_LAI", "phieu_kiem_ke", ma)
        messages.info(request, "Đã mở lại phiếu để đếm lại từ lần 1.")
    except NghiepVuError as e:
        messages.error(request, str(e))
    return redirect("kiem_detail", ma=ma)


@require_POST
def kiem_huy(request, ma):
    phieu = get_object_or_404(PhieuKiemKe, pk=ma)
    if phieu.trang_thai not in (PhieuKiemKe.DANG_KIEM, PhieuKiemKe.BI_TU_CHOI):
        messages.error(request, "Chỉ hủy được phiếu đang kiểm hoặc bị từ chối.")
    elif phieu.nguoi_tao_id != request.user.pk and not request.user.is_admin:
        messages.error(request, "Chỉ người tạo phiếu hoặc Quản trị viên được hủy.")
    else:
        phieu.trang_thai = PhieuKiemKe.DA_HUY
        phieu.save(update_fields=["trang_thai"])
        audit(request, "HUY", "phieu_kiem_ke", ma)
        messages.success(request, f"Đã hủy phiếu {ma}.")
    return redirect("kiem_detail", ma=ma)


@admin_required
@require_POST
def kiem_xoa(request, ma):
    phieu = get_object_or_404(PhieuKiemKe, pk=ma)
    if phieu.trang_thai == PhieuKiemKe.HOAN_THANH:
        messages.error(request, "Phiếu đã hoàn thành (đã cân bằng kho) không thể xóa.")
        return redirect("kiem_detail", ma=ma)
    phieu.delete()
    audit(request, "XOA", "phieu_kiem_ke", ma)
    messages.success(request, f"Đã xóa phiếu {ma}.")
    return redirect("kiem")
