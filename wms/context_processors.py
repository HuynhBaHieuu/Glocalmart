from django.db.models import F, Q

from .models import PhieuKiemKe, PhieuNhap, SanPham

MENU = [
    ("dashboard", "Tổng quan Dashboard", "Dashboard", "layout-grid", "/"),
    ("danh_muc", "Danh mục sản phẩm", "Product Categories", "tag", "/danh-muc/"),
    ("san_pham", "Sản phẩm", "Product", "layers", "/san-pham/"),
    ("ncc", "Nhà cung cấp", "Partners & Suppliers", "users", "/nha-cung-cap/"),
    ("nhap", "Nhập kho", "Inbound / Goods Receipt", "arrow-down-left", "/nhap-kho/"),
    ("xuat", "Xuất kho", "Outbound / Goods Issue", "arrow-up-right", "/xuat-kho/"),
    ("kiem_ke", "Kiểm kê", "Inventory Audit", "search", "/kiem-ke/"),
    ("bao_cao", "Báo cáo xuất-nhập-tồn", "Inventory Reports", "file-text", "/bao-cao/"),
    ("tai_khoan", "Quản lý tài khoản", "Account Management", "user", "/tai-khoan/"),
]


def sidebar(request):
    user = getattr(request, "user", None)
    if not user or not user.is_authenticated:
        return {}
    menu = [m for m in MENU if m[0] != "tai_khoan" or user.is_admin]
    active_sp = SanPham.objects.filter(trang_thai=1)
    # cần cảnh báo khi tồn ≤ ROP (chưa tính ROP thì dùng ngưỡng tối thiểu) — gồm Hết hàng / Dưới SS / Cần đặt hàng
    so_canh_bao = active_sp.filter(
        Q(ton_kho__lte=0) | Q(rop__isnull=False, ton_kho__lte=F("rop"))
        | Q(rop__isnull=True, ton_kho__lte=F("nguong_toi_thieu"))
    ).count()
    thong_bao = {
        "canh_bao_ton": so_canh_bao,
        "cho_duyet": PhieuKiemKe.objects.filter(trang_thai=PhieuKiemKe.CHO_DUYET).count() if user.is_admin else 0,
        "cho_giao": PhieuNhap.objects.filter(trang_thai=PhieuNhap.CHUA_XAC_NHAN).count(),
    }
    thong_bao["tong"] = thong_bao["canh_bao_ton"] + thong_bao["cho_duyet"]
    return {"MENU": menu, "THONG_BAO": thong_bao}
