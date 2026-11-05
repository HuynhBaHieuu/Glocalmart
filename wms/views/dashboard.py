from django.shortcuts import render
from django.utils import timezone

from ..decorators import admin_required
from ..models import ChiTietPhieuNhap, DanhMuc, NhatKyKho, PhieuNhap, SanPham
from ..services import audit, canh_bao_han_su_dung
from .common import excel_response, paginate

TABS = [
    ("tat_ca", "Tất cả cảnh báo", None),
    ("het_hang", "Đã hết hàng", "bg-red-500"),
    ("sap_het", "Sắp hết hàng", "bg-orange-500"),
    ("het_han", "Đã hết hạn", "bg-red-700"),
    ("sap_het_han", "Sắp hết hạn", "bg-amber-400"),
]


LOT_TABS = ("het_han", "sap_het_han")  # 2 tab này hiển thị theo LÔ, các tab còn lại theo sản phẩm


def tinh_canh_bao():
    """Quét thời gian thực: cảnh báo tồn kho theo sản phẩm, cảnh báo hạn sử dụng theo lô."""
    sps = list(SanPham.objects.filter(trang_thai=1).select_related("id_danhmuc"))
    lots = canh_bao_han_su_dung()
    nhom = {k: [] for k, *_ in TABS}
    for lo in lots:
        nhom["het_han" if lo.muc_han == "DA_HET_HAN" else "sap_het_han"].append(lo)
    sl_han = {}  # {id_sp: {"DA_HET_HAN": tổng SL lô, "SAP_HET_HAN": ...}}
    for lo in lots:
        d = sl_han.setdefault(lo.id_sp_id, {})
        d[lo.muc_han] = d.get(lo.muc_han, 0) + lo.so_luong_con_lai
    for sp in sps:
        canh_bao = []
        if sp.muc_ton == "HET_HANG":
            nhom["het_hang"].append(sp)
            canh_bao.append("HET_HANG")
        elif sp.muc_ton == "SAP_HET":
            nhom["sap_het"].append(sp)
            canh_bao.append("SAP_HET")
        sp.sl_han = sl_han.get(sp.pk, {})
        canh_bao += [k for k in ("DA_HET_HAN", "SAP_HET_HAN") if k in sp.sl_han]
        if canh_bao:
            sp.canh_bao = canh_bao
            nhom["tat_ca"].append(sp)
    return sps, nhom


def _loc(request, nhom):
    """Tab + ô tìm kiếm + lọc danh mục dùng chung cho trang Dashboard và file xuất báo cáo."""
    tab = request.GET.get("tab", "tat_ca")
    if tab not in nhom:
        tab = "tat_ca"
    rows = nhom[tab]
    q = request.GET.get("q", "").strip().lower()
    dm = request.GET.get("dm", "")
    sp_of = (lambda r: r.id_sp) if tab in LOT_TABS else (lambda r: r)
    if q:
        rows = [r for r in rows if q in sp_of(r).ten_sp.lower() or q in sp_of(r).ma_sp.lower()]
    if dm:
        rows = [r for r in rows if str(sp_of(r).id_danhmuc_id) == dm or str(sp_of(r).id_danhmuc.id_dmcha_id) == dm]
    if tab not in LOT_TABS:
        for r in rows:
            r.canh_bao = getattr(r, "canh_bao", [])
    return tab, rows, dm


def _donut(phan, tong):
    """phan: list[(số lượng, màu)] → CSS conic-gradient."""
    if not tong:
        return "conic-gradient(#e5e7eb 0 100%)"
    stops, start = [], 0.0
    for n, mau in phan:
        end = start + n * 100 / tong
        stops.append(f"{mau} {start}% {end}%")
        start = end
    return "conic-gradient(" + ", ".join(stops) + ")"


def dashboard(request):
    sps, nhom = tinh_canh_bao()
    tong = len(sps)
    het, sap = len(nhom["het_hang"]), len(nhom["sap_het"])
    an_toan = tong - het - sap
    tab, rows, dm = _loc(request, nhom)

    def pct(n, base=tong):
        return round(n * 100 / base) if base else 0

    donut = _donut([(het, "#dc2626"), (sap, "#ea580c"), (an_toan, "#16a34a")], tong)

    # biểu đồ hạn sử dụng theo LÔ: lô còn hàng, có hạn, của sản phẩm đang hoạt động
    co_hsd = ChiTietPhieuNhap.objects.filter(ma_phieu_nhap__trang_thai=PhieuNhap.DA_XAC_NHAN, so_luong_con_lai__gt=0,
                                             han_su_dung__isnull=False, id_sp__trang_thai=1).count()
    hh, shh = len(nhom["het_han"]), len(nhom["sap_het_han"])
    con_han = co_hsd - hh - shh
    donut_han = _donut([(hh, "#b91c1c"), (shh, "#f59e0b"), (con_han, "#16a34a")], co_hsd)

    ctx = {
        "active": "dashboard",
        "tong": tong,
        "het": het,
        "sap": sap,
        "an_toan": an_toan,
        "pct": {"het": pct(het), "sap": pct(sap), "an_toan": pct(an_toan)},
        "het_han": hh,
        "sap_het_han": shh,
        "donut": donut,
        "han": {
            "tong": co_hsd, "con_han": con_han, "donut": donut_han,
            "pct": {"het_han": pct(hh, co_hsd), "sap_het_han": pct(shh, co_hsd), "con_han": pct(con_han, co_hsd)},
        },
        "tabs": [(k, label, dot, len(nhom[k])) for k, label, dot in TABS],
        "tab": tab,
        "theo_lo": tab in LOT_TABS,
        "page": paginate(request, rows, 7),
        "danh_muc": DanhMuc.objects.filter(is_active=True),
        "q": request.GET.get("q", ""),
        "dm": dm,
        "now": timezone.now(),
        "nhat_ky": NhatKyKho.objects.filter(loai_giao_dich__in=NhatKyKho.LOAI_BIEN_DONG)
        .select_related("id_sp", "nguoi_thuc_hien")[:6],
    }
    return render(request, "dashboard.html", ctx)


@admin_required
def dashboard_export(request):
    """Xuất Excel danh sách cảnh báo của tab đang xem (kèm bộ lọc tìm kiếm / danh mục)."""
    _, nhom = tinh_canh_bao()
    tab, rows, _ = _loc(request, nhom)
    ten_tab = dict((k, label) for k, label, _ in TABS)[tab]
    labels = {"HET_HANG": "Đã hết hàng", "SAP_HET": "Sắp hết hàng", "DA_HET_HAN": "Đã hết hạn",
              "SAP_HET_HAN": "Sắp hết hạn"}
    data = []
    if tab in LOT_TABS:
        headers = ["Mã SP", "Tên SP", "Lô (mã phiếu nhập)", "SL còn của lô", "Tổng tồn", "Hạn sử dụng", "Còn lại",
                   "Trạng thái"]
        for lo in rows:
            con = lo.so_ngay_con_lai
            data.append([lo.id_sp.ma_sp, lo.id_sp.ten_sp, lo.ma_phieu_nhap_id, lo.so_luong_con_lai, lo.id_sp.ton_kho,
                         lo.han_su_dung.strftime("%d/%m/%Y"), f"Quá hạn {-con} ngày" if con < 0 else f"Còn {con} ngày",
                         labels[lo.muc_han]])
    else:
        headers = ["Mã SP", "Tên SP", "Danh mục", "ĐVT", "SL tồn", "Ngưỡng tối thiểu", "Hạn sớm nhất", "Trạng thái cảnh báo"]
        for sp in rows:
            data.append([sp.ma_sp, sp.ten_sp, sp.id_danhmuc.ten_danhmuc, sp.don_vi, sp.ton_kho, sp.nguong_toi_thieu,
                         sp.han_su_dung.strftime("%d/%m/%Y") if sp.han_su_dung else "",
                         ", ".join(labels.get(c, c) for c in sp.canh_bao)])
    luc = timezone.localtime().strftime("%d/%m/%Y %H:%M")
    audit(request, "XUAT_BAO_CAO", "canh_bao", tab, f"{ten_tab}: {len(rows)} sản phẩm")
    return excel_response(
        f"canh_bao_{tab}_{timezone.localtime():%Y%m%d_%H%M}.xlsx", f"Báo cáo cảnh báo - {ten_tab}",
        headers,
        data,
        subtitle=[f"Thời gian khởi tạo: {luc} · Người xuất: {request.user.ho_ten}", f"Số sản phẩm: {len(rows)}"],
    )
