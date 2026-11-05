from datetime import date
from decimal import Decimal, InvalidOperation
from io import BytesIO

from django.core.paginator import Paginator
from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill

from ..models import DanhMuc, SanPham


def to_decimal(value, default=None):
    if value is None:
        return default
    s = str(value).strip().replace(" ", "")
    if s == "":
        return default
    # chấp nhận cả "1.250" (phân cách nghìn) lẫn "2,5" (thập phân kiểu VN)
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return default


def to_date(value):
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def paginate(request, qs, per_page=10):
    try:
        per_page = int(request.GET.get("per", per_page))
    except ValueError:
        pass
    per_page = max(5, min(per_page, 100))
    page = Paginator(qs, per_page).get_page(request.GET.get("page"))
    page.per_page = per_page
    page.range = page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)
    return page


def products_json(qs=None, include_stock=True):
    """Danh sách sản phẩm cho các form chọn sản phẩm (Alpine.js)."""
    qs = qs if qs is not None else SanPham.objects.filter(trang_thai=1)
    cha = dict(DanhMuc.objects.values_list("pk", "id_dmcha_id"))

    def to_tien(dm_id):
        """Danh mục của SP + toàn bộ danh mục cha (để 'thêm cả danh mục' lấy được danh mục con)."""
        ids, node = [], dm_id
        while node and node not in ids:
            ids.append(node)
            node = cha.get(node)
        return ids

    from ..services import ton_con_han_theo_sp
    con_han = ton_con_han_theo_sp()
    data = []
    for sp in qs.select_related("id_danhmuc"):
        item = {
            "id": sp.pk,
            "ma": sp.ma_sp,
            "ten": sp.ten_sp,
            "dvt": sp.don_vi,
            "dm": sp.id_danhmuc.ten_danhmuc,
            "dm_ids": to_tien(sp.id_danhmuc_id),
            "gia_von": float(sp.gia_von),
            "gia_ban": float(sp.gia_ban),
            "hsd": sp.han_su_dung.isoformat() if sp.han_su_dung else None,
            "het_han": sp.da_het_han,  # có lô đã hết hạn còn hàng
            "active": sp.trang_thai == 1,
        }
        if include_stock:
            item["ton"] = float(sp.ton_kho)
            item["ton_con_han"] = float(con_han.get(sp.pk, 0))  # được bán / điều chỉnh
        data.append(item)
    return data


def excel_response(filename, title, headers, rows, subtitle=None):
    wb = Workbook()
    ws = wb.active
    ws.title = title[:31]
    ws.append([title])
    ws["A1"].font = Font(bold=True, size=14, color="0B4C34")
    r = 2
    if subtitle:
        for line in subtitle if isinstance(subtitle, (list, tuple)) else [subtitle]:
            ws.append([line])
            ws.cell(row=r, column=1).font = Font(italic=True, color="555555")
            r += 1
    ws.append([])
    ws.append(headers)
    hrow = ws.max_row
    for i in range(1, len(headers) + 1):
        c = ws.cell(row=hrow, column=i)
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="0B4C34")
        c.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    for row in rows:
        ws.append([float(v) if isinstance(v, Decimal) else v for v in row])
    for i, h in enumerate(headers, start=1):
        width = max([len(str(h))] + [len(str(row[i - 1])) for row in rows if i - 1 < len(row)] + [8])
        ws.column_dimensions[ws.cell(row=hrow, column=i).column_letter].width = min(width + 2, 50)
    ws.freeze_panes = ws.cell(row=hrow + 1, column=1)
    buf = BytesIO()
    wb.save(buf)
    resp = HttpResponse(buf.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    resp["Content-Disposition"] = f'attachment; filename="{filename}"'
    return resp


def form_errors(form):
    """Gộp lỗi của Django form thành dict {field: message} cho Alpine hiển thị."""
    return {k: " ".join(str(e) for e in v) for k, v in form.errors.items()}
