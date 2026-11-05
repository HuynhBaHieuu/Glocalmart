from decimal import Decimal, InvalidOperation

from django import template
from django.utils import timezone
from django.utils.html import format_html

register = template.Library()


def _group(n: int) -> str:
    return f"{n:,}".replace(",", ".")


@register.filter
def vnd(value, suffix=" đ"):
    """85000 → '85.000 đ'"""
    if value is None or value == "":
        return "—"
    try:
        d = Decimal(value).quantize(Decimal(1))
    except (InvalidOperation, TypeError, ValueError):
        return value
    sign = "-" if d < 0 else ""
    return f"{sign}{_group(abs(int(d)))}{suffix}"


@register.filter
def money(value):
    return vnd(value, "")


@register.filter
def qty(value):
    """1250.000 → '1.250' ; 2.5 → '2,5'"""
    if value is None or value == "":
        return "—"
    try:
        d = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    sign = "-" if d < 0 else ""
    d = abs(d)
    whole = int(d)
    frac = (d - whole).normalize()
    s = _group(whole)
    if frac:
        s += "," + f"{frac:f}".split(".")[1]
    return sign + s


@register.filter
def signed(value):
    try:
        d = Decimal(value)
    except (InvalidOperation, TypeError, ValueError):
        return value
    return ("+" if d > 0 else "") + qty(d)


@register.filter
def dt(value):
    if not value:
        return "—"
    if hasattr(value, "hour"):
        return timezone.localtime(value).strftime("%d/%m/%Y %H:%M")
    return value.strftime("%d/%m/%Y")


@register.filter
def d(value):
    if not value:
        return "—"
    if hasattr(value, "hour"):
        value = timezone.localtime(value)
    return value.strftime("%d/%m/%Y")


@register.filter
def iso(value):
    return value.isoformat() if value else ""


@register.filter
def num(value):
    """Giá trị cho input number (dùng dấu chấm thập phân, bỏ số 0 thừa)."""
    if value is None or value == "":
        return ""
    return f"{Decimal(value).normalize():f}"


BADGES = {
    # trạng thái giao
    "CHO_GIAO": ("Chờ giao", "bg-amber-50 text-amber-700 ring-amber-200"),
    "DANG_GIAO": ("Đang giao", "bg-blue-50 text-blue-700 ring-blue-200"),
    "DA_GIAO": ("Đã giao", "bg-emerald-50 text-emerald-700 ring-emerald-200"),
    # trạng thái chứng từ
    "CHUA_XAC_NHAN": ("Chờ xác nhận", "bg-amber-50 text-amber-700 ring-amber-200"),
    "DA_XAC_NHAN": ("Đã xác nhận", "bg-emerald-50 text-emerald-700 ring-emerald-200"),
    "DA_HUY": ("Đã hủy", "bg-gray-100 text-gray-500 ring-gray-200"),
    # kiểm kê
    "DANG_KIEM": ("Đang kiểm", "bg-blue-50 text-blue-700 ring-blue-200"),
    "CHO_DUYET": ("Chờ duyệt", "bg-amber-50 text-amber-700 ring-amber-200"),
    "HOAN_THANH": ("Hoàn thành", "bg-emerald-50 text-emerald-700 ring-emerald-200"),
    "BI_TU_CHOI": ("Từ chối", "bg-red-50 text-red-600 ring-red-200"),
    # lý do xuất
    "BAN_HANG": ("Bán hàng", "bg-emerald-50 text-emerald-700 ring-emerald-200"),
    "HUY_HANG": ("Hủy hàng", "bg-red-50 text-red-600 ring-red-200"),
    "DIEU_CHINH": ("Điều chỉnh", "bg-violet-50 text-violet-700 ring-violet-200"),
    # tồn kho
    "HET_HANG": ("Đã hết hàng", "bg-red-50 text-red-600 ring-red-200"),
    "SAP_HET": ("Sắp hết hàng", "bg-orange-50 text-orange-600 ring-orange-200"),
    "AN_TOAN": ("An toàn", "bg-emerald-50 text-emerald-700 ring-emerald-200"),
    "DA_HET_HAN": ("Đã hết hạn", "bg-red-50 text-red-600 ring-red-200"),
    "SAP_HET_HAN": ("Sắp hết hạn", "bg-orange-50 text-orange-600 ring-orange-200"),
    "CON_HAN": ("Còn hạn", "bg-emerald-50 text-emerald-700 ring-emerald-200"),
    # chênh lệch nhập
    "THIEU_HANG": ("Thiếu hàng", "bg-amber-50 text-amber-700 ring-amber-200"),
    "HU_HONG": ("Hư hỏng", "bg-red-50 text-red-600 ring-red-200"),
    "GIAO_NHAM": ("Giao nhầm", "bg-violet-50 text-violet-700 ring-violet-200"),
    # vai trò
    "ADMIN": ("Quản trị viên", "bg-emerald-900/5 text-brand-700 ring-brand-700/20"),
    "NHAN_VIEN": ("Nhân viên", "bg-gray-50 text-gray-600 ring-gray-200"),
    # nhật ký
    "NHAP_KHO": ("Nhập kho", "bg-emerald-50 text-emerald-700 ring-emerald-200"),
    "XUAT_KHO": ("Xuất kho", "bg-blue-50 text-blue-700 ring-blue-200"),
    "KIEM_KE": ("Kiểm kê", "bg-violet-50 text-violet-700 ring-violet-200"),
    "SUA_HAN_LO": ("Sửa hạn lô", "bg-amber-50 text-amber-700 ring-amber-200"),
}


@register.simple_tag
def badge(code, label=None):
    text, cls = BADGES.get(code, (code, "bg-gray-100 text-gray-600 ring-gray-200"))
    return format_html(
        '<span class="inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset {}">{}</span>',
        cls,
        label or text,
    )


@register.simple_tag
def dot_badge(active, on="Đang hoạt động", off="Ngừng hoạt động"):
    if active:
        return format_html(
            '<span class="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-emerald-50 px-2.5 py-0.5 text-xs font-medium text-emerald-700 ring-1 ring-inset ring-emerald-200"><span class="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>{}</span>',
            on,
        )
    return format_html(
        '<span class="inline-flex items-center gap-1.5 whitespace-nowrap rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-500 ring-1 ring-inset ring-gray-200"><span class="h-1.5 w-1.5 rounded-full bg-gray-400"></span>{}</span>',
        off,
    )


@register.simple_tag(takes_context=True)
def qs(context, **kwargs):
    """Giữ các tham số GET hiện có, thay thế các khóa truyền vào."""
    q = context["request"].GET.copy()
    for k, v in kwargs.items():
        if v is None or v == "":
            q.pop(k, None)
        else:
            q[k] = v
    return "?" + q.urlencode() if q else "?"
