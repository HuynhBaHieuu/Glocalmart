"""Báo cáo Nhập - Xuất - Tồn, tính trực tiếp từ NHAT_KY_KHO (chỉ ghi khi chứng từ đã xác nhận)."""
from datetime import datetime, time, timedelta
from decimal import Decimal
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from ..decorators import admin_required
from ..models import DanhMuc, NhatKyKho, SanPham
from ..services import audit
from .common import excel_response, paginate, to_date


def _ky(request):
    today = timezone.localdate()
    tu = to_date(request.GET.get("tu")) or today.replace(day=1)
    den = to_date(request.GET.get("den")) or today
    if tu > den:
        tu, den = den, tu
    return tu, den


def _aware(d, end=False):
    tz = timezone.get_current_timezone()
    if end:
        return timezone.make_aware(datetime.combine(d + timedelta(days=1), time.min), tz)
    return timezone.make_aware(datetime.combine(d, time.min), tz)


def tinh_nxt(tu, den, sp_qs):
    """Trả về list dict: tồn đầu, nhập, xuất, điều chỉnh kiểm kê, tồn cuối theo từng sản phẩm."""
    start, end = _aware(tu), _aware(den, end=True)
    sps = list(sp_qs.select_related("id_danhmuc"))
    ids = [s.pk for s in sps]
    data = {s.pk: {"sp": s, "dau": Decimal(0), "nhap": Decimal(0), "xuat": Decimal(0), "kiem": Decimal(0),
                   "cuoi": None, "co_gd": False} for s in sps}
    # Tồn đầu kỳ = sl_sau của bút toán cuối cùng trước kỳ
    bien_dong = NhatKyKho.objects.filter(loai_giao_dich__in=NhatKyKho.LOAI_BIEN_DONG)  # bỏ qua SUA_HAN_LO
    for log in (bien_dong.filter(id_sp_id__in=ids, ngay_tao__lt=start)
                .order_by("id_sp_id", "ngay_tao", "id_nhat_ky").only("id_sp_id", "sl_sau")):
        data[log.id_sp_id]["dau"] = log.sl_sau
    for log in (bien_dong.filter(id_sp_id__in=ids, ngay_tao__gte=start, ngay_tao__lt=end)
                .order_by("ngay_tao", "id_nhat_ky").only("id_sp_id", "loai_giao_dich", "sl_thay_doi", "sl_sau")):
        row = data[log.id_sp_id]
        row["co_gd"] = True
        if log.loai_giao_dich == NhatKyKho.NHAP_KHO:
            row["nhap"] += log.sl_thay_doi
        elif log.loai_giao_dich == NhatKyKho.XUAT_KHO:
            row["xuat"] -= log.sl_thay_doi
        else:
            row["kiem"] += log.sl_thay_doi
        row["cuoi"] = log.sl_sau
    rows = []
    for r in data.values():
        if r["cuoi"] is None:
            r["cuoi"] = r["dau"]
        r["gia_tri"] = r["cuoi"] * r["sp"].gia_von
        rows.append(r)
    return rows


def _filter(request):
    tu, den = _ky(request)
    qs = SanPham.objects.all()
    q, dm, sp = request.GET.get("q", "").strip(), request.GET.get("dm", ""), request.GET.get("sp", "")
    if q:
        qs = qs.filter(Q(ten_sp__icontains=q) | Q(ma_sp__icontains=q))
    if dm:
        qs = qs.filter(Q(id_danhmuc_id=dm) | Q(id_danhmuc__id_dmcha_id=dm))
    if sp:
        qs = qs.filter(pk=sp)
    rows = tinh_nxt(tu, den, qs)
    if request.GET.get("chi_gd"):
        rows = [r for r in rows if r["co_gd"]]
    return tu, den, rows, q, dm, sp


def _tong(rows):
    return {k: sum((r[k] for r in rows), Decimal(0)) for k in ("dau", "nhap", "xuat", "kiem", "cuoi", "gia_tri")}


def bao_cao(request):
    tu, den, rows, q, dm, sp = _filter(request)
    tab = request.GET.get("tab", "mat_hang")
    logs = (NhatKyKho.objects.filter(loai_giao_dich__in=NhatKyKho.LOAI_BIEN_DONG,
                                     ngay_tao__gte=_aware(tu), ngay_tao__lt=_aware(den, end=True))
            .select_related("id_sp", "nguoi_thuc_hien"))
    if dm:
        logs = logs.filter(Q(id_sp__id_danhmuc_id=dm) | Q(id_sp__id_danhmuc__id_dmcha_id=dm))
    if sp:
        logs = logs.filter(id_sp_id=sp)
    if q:
        logs = logs.filter(Q(id_sp__ten_sp__icontains=q) | Q(id_sp__ma_sp__icontains=q))
    return render(request, "baocao/bao_cao.html", {
        "active": "bao_cao",
        "tu": tu, "den": den, "q": q, "dm": dm, "sp": sp, "tab": tab,
        "chi_gd": request.GET.get("chi_gd", ""),
        "tong": _tong(rows),
        "so_mat_hang": len(rows),
        "so_gd": logs.count(),
        "page": paginate(request, logs if tab == "giao_dich" else rows, 10),
        "danh_muc": DanhMuc.objects.all(),
        "san_pham": SanPham.objects.only("pk", "ma_sp", "ten_sp"),
    })


@admin_required
def bao_cao_export(request):
    tu, den, rows, *_ = _filter(request)
    fmt = request.GET.get("format", "xlsx")
    nguoi = request.user.ho_ten
    luc = timezone.localtime().strftime("%d/%m/%Y %H:%M")
    audit(request, "XUAT_BAO_CAO", "bao_cao_nxt", f"{tu}..{den}", fmt)
    if fmt == "pdf":
        return _pdf(tu, den, rows, nguoi, luc)
    t = _tong(rows)
    data = [[r["sp"].ma_sp, r["sp"].ten_sp, r["sp"].id_danhmuc.ten_danhmuc, r["sp"].don_vi, r["dau"], r["nhap"],
             r["xuat"], r["kiem"], r["cuoi"], r["sp"].gia_von, r["gia_tri"]] for r in rows]
    data.append(["", "TỔNG CỘNG", "", "", t["dau"], t["nhap"], t["xuat"], t["kiem"], t["cuoi"], "", t["gia_tri"]])
    return excel_response(
        f"bao_cao_NXT_{tu:%Y%m%d}_{den:%Y%m%d}.xlsx", "Báo cáo Nhập - Xuất - Tồn",
        ["Mã SP", "Tên SP", "Danh mục", "ĐVT", "Tồn đầu kỳ", "Tổng nhập", "Tổng xuất", "Điều chỉnh KK", "Tồn cuối kỳ",
         "Giá vốn", "Giá trị tồn"],
        data,
        subtitle=[f"Kỳ báo cáo: {tu:%d/%m/%Y} - {den:%d/%m/%Y}", f"Thời gian khởi tạo: {luc} · Người xuất: {nguoi}"],
    )


def _num(d):
    d = Decimal(d)
    s = f"{abs(int(d)):,}".replace(",", ".")
    frac = (abs(d) - abs(int(d))).normalize()
    if frac:
        s += "," + f"{frac:f}".split(".")[1]
    return ("-" if d < 0 else "") + s


def _pdf(tu, den, rows, nguoi, luc):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    font_dir = Path(settings.BASE_DIR) / "static" / "fonts"
    if "BVP" not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont("BVP", str(font_dir / "BeVietnamPro-Regular.ttf")))
        pdfmetrics.registerFont(TTFont("BVP-B", str(font_dir / "BeVietnamPro-Bold.ttf")))

    green = colors.HexColor("#0B4C34")
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm, topMargin=12 * mm,
                            bottomMargin=12 * mm, title="Báo cáo Nhập - Xuất - Tồn")
    h = ParagraphStyle("h", fontName="BVP-B", fontSize=16, textColor=green, spaceAfter=4)
    s = ParagraphStyle("s", fontName="BVP", fontSize=9, textColor=colors.HexColor("#555555"), leading=13)
    cell = ParagraphStyle("c", fontName="BVP", fontSize=8, leading=10)
    story = [
        Paragraph("G'LOCAL MART &amp; CAFE — BÁO CÁO NHẬP - XUẤT - TỒN", h),
        Paragraph(f"Kỳ báo cáo: {tu:%d/%m/%Y} – {den:%d/%m/%Y}", s),
        Paragraph(f"Thời gian khởi tạo: {luc} · Người xuất: {nguoi}", s),
        Spacer(1, 6 * mm),
    ]
    head = ["Mã SP", "Tên sản phẩm", "ĐVT", "Tồn đầu", "Nhập", "Xuất", "Đ.chỉnh KK", "Tồn cuối", "Giá trị tồn (đ)"]
    body = [[r["sp"].ma_sp, Paragraph(r["sp"].ten_sp, cell), r["sp"].don_vi, _num(r["dau"]), _num(r["nhap"]),
             _num(r["xuat"]), _num(r["kiem"]), _num(r["cuoi"]), _num(r["gia_tri"])] for r in rows]
    t = _tong(rows)
    body.append(["", "TỔNG CỘNG", "", _num(t["dau"]), _num(t["nhap"]), _num(t["xuat"]), _num(t["kiem"]),
                 _num(t["cuoi"]), _num(t["gia_tri"])])
    table = Table([head] + body, repeatRows=1,
                  colWidths=[24 * mm, 78 * mm, 18 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm, 22 * mm, 33 * mm])
    table.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "BVP"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("FONTNAME", (0, 0), (-1, 0), "BVP-B"),
        ("BACKGROUND", (0, 0), (-1, 0), green),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F3F7F5")]),
        ("FONTNAME", (0, -1), (-1, -1), "BVP-B"),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#EDF3EF")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#D1D5DB")),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
    ]))
    story += [table, Spacer(1, 12 * mm)]
    sign = Table([["Người lập biểu", "Quản lý kho"], ["(Ký, ghi rõ họ tên)", "(Ký, ghi rõ họ tên)"],
                  ["", ""], ["", ""], [nguoi, ""]], colWidths=[130 * mm, 130 * mm])
    sign.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, -1), "BVP"), ("FONTNAME", (0, 0), (-1, 0), "BVP-B"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("TEXTCOLOR", (0, 1), (-1, 1), colors.HexColor("#6B7280")),
    ]))
    story.append(sign)
    doc.build(story)
    resp = HttpResponse(buf.getvalue(), content_type="application/pdf")
    resp["Content-Disposition"] = f'attachment; filename="bao_cao_NXT_{tu:%Y%m%d}_{den:%Y%m%d}.pdf"'
    return resp
