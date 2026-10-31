from django.shortcuts import render
from django.utils import timezone

from ..models import DanhMuc, NhatKyKho, PhieuKiemKe, PhieuNhap, PhieuXuat, SanPham
from .common import paginate

TABS = [
    ("tat_ca", "Tất cả cảnh báo", None),
    ("het_hang", "Đã hết hàng", "bg-red-500"),
    ("sap_het", "Sắp hết hàng", "bg-orange-500"),
    ("het_han", "Đã hết hạn", "bg-red-700"),
    ("sap_het_han", "Sắp hết hạn", "bg-amber-400"),
]


def tinh_canh_bao():
    """Quét thời gian thực toàn bộ sản phẩm đang kinh doanh → nhóm cảnh báo."""
    sps = list(SanPham.objects.filter(trang_thai=1).select_related("id_danhmuc"))
    nhom = {k: [] for k, *_ in TABS}
    for sp in sps:
        canh_bao = []
        if sp.muc_ton == "HET_HANG":
            nhom["het_hang"].append(sp)
            canh_bao.append("HET_HANG")
        elif sp.muc_ton == "SAP_HET":
            nhom["sap_het"].append(sp)
            canh_bao.append("SAP_HET")
        if sp.ton_kho > 0 and sp.muc_han == "DA_HET_HAN":
            nhom["het_han"].append(sp)
            canh_bao.append("DA_HET_HAN")
        elif sp.ton_kho > 0 and sp.muc_han == "SAP_HET_HAN":
            nhom["sap_het_han"].append(sp)
            canh_bao.append("SAP_HET_HAN")
        if canh_bao:
            sp.canh_bao = canh_bao
            nhom["tat_ca"].append(sp)
    return sps, nhom


def dashboard(request):
    sps, nhom = tinh_canh_bao()
    tong = len(sps)
    het, sap = len(nhom["het_hang"]), len(nhom["sap_het"])
    an_toan = tong - het - sap

    tab = request.GET.get("tab", "tat_ca")
    if tab not in nhom:
        tab = "tat_ca"
    rows = nhom[tab]
    q = request.GET.get("q", "").strip().lower()
    dm = request.GET.get("dm", "")
    if q:
        rows = [s for s in rows if q in s.ten_sp.lower() or q in s.ma_sp.lower()]
    if dm:
        rows = [s for s in rows if str(s.id_danhmuc_id) == dm or str(s.id_danhmuc.id_dmcha_id) == dm]
    for s in rows:
        s.canh_bao = getattr(s, "canh_bao", [])

    def pct(n):
        return round(n * 100 / tong) if tong else 0

    # vẽ donut bằng conic-gradient
    p_het, p_sap = (het * 100 / tong if tong else 0), (sap * 100 / tong if tong else 0)
    donut = f"conic-gradient(#dc2626 0 {p_het}%, #ea580c {p_het}% {p_het + p_sap}%, #16a34a {p_het + p_sap}% 100%)"
    if not tong:
        donut = "conic-gradient(#e5e7eb 0 100%)"

    ctx = {
        "active": "dashboard",
        "tong": tong,
        "het": het,
        "sap": sap,
        "an_toan": an_toan,
        "pct": {"het": pct(het), "sap": pct(sap), "an_toan": pct(an_toan)},
        "het_han": len(nhom["het_han"]),
        "sap_het_han": len(nhom["sap_het_han"]),
        "donut": donut,
        "tabs": [(k, label, dot, len(nhom[k])) for k, label, dot in TABS],
        "tab": tab,
        "page": paginate(request, rows, 7),
        "danh_muc": DanhMuc.objects.filter(is_active=True),
        "q": request.GET.get("q", ""),
        "dm": dm,
        "now": timezone.now(),
        "nhat_ky": NhatKyKho.objects.select_related("id_sp", "nguoi_thuc_hien")[:6],
        "stats": {
            "cho_giao": PhieuNhap.objects.filter(trang_thai=PhieuNhap.CHUA_XAC_NHAN).count(),
            "xuat_cho": PhieuXuat.objects.filter(trang_thai=PhieuXuat.CHUA_XAC_NHAN).count(),
            "kiem_cho": PhieuKiemKe.objects.filter(trang_thai=PhieuKiemKe.CHO_DUYET).count(),
        },
    }
    return render(request, "dashboard.html", ctx)
