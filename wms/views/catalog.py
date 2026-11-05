"""Danh mục, Sản phẩm, Nhà cung cấp."""
import mimetypes
import urllib.request
import uuid

from django.conf import settings
from django.contrib import messages
from django.core.files.storage import default_storage
from django.db import transaction
from django.db.models import Count, F, Q
from django.db.models.deletion import ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from ..decorators import admin_required
from ..forms import DanhMucForm, NhaCungCapForm, SanPhamForm
from ..models import DanhMuc, NhaCungCap, SanPham
from ..services import audit
from .common import excel_response, form_errors, paginate


def _modal_state(form, pk):
    """Dữ liệu để mở lại modal kèm lỗi sau khi submit thất bại."""
    return {
        "open": True,
        "pk": pk or "",
        "data": {k: (v if v is not None else "") for k, v in form.data.items() if k != "csrfmiddlewaretoken"},
        "errors": form_errors(form),
    }


# ================================================================ DANH MỤC
def danh_muc_list(request, form=None, form_pk=None):
    qs = DanhMuc.objects.select_related("id_dmcha").annotate(so_sp=Count("san_pham", distinct=True),
                                                            so_con=Count("con", distinct=True)).order_by("ma_danhmuc")
    q, tt = request.GET.get("q", "").strip(), request.GET.get("tt", "")
    if q:
        qs = qs.filter(Q(ten_danhmuc__icontains=q) | Q(ma_danhmuc__icontains=q) | Q(mo_ta__icontains=q))
    if tt in ("1", "0"):
        qs = qs.filter(is_active=tt == "1")
    tat_ca = DanhMuc.objects.annotate(so_sp=Count("san_pham"))
    ctx = {
        "active": "danh_muc",
        "page": paginate(request, qs, 10),
        "q": q,
        "tt": tt,
        "tong": tat_ca.count(),
        "dang_hd": tat_ca.filter(is_active=True).count(),
        "trong": tat_ca.filter(so_sp=0).count(),
        "tat_ca_dm": DanhMuc.objects.all(),
        "modal": _modal_state(form, form_pk) if form else None,
        "goi_y_ma": f"DM{DanhMuc.objects.count() + 1:03d}",
    }
    return render(request, "catalog/danh_muc.html", ctx)


@admin_required
@require_POST
def danh_muc_save(request):
    pk = request.POST.get("pk")
    obj = get_object_or_404(DanhMuc, pk=pk) if pk else None
    data = request.POST.copy()
    data["is_active"] = "is_active" in request.POST or not pk
    form = DanhMucForm(data, instance=obj)
    if not form.is_valid():
        return danh_muc_list(request, form, pk)
    dm = form.save()
    audit(request, "SUA" if pk else "THEM", "danh_muc", dm.pk, form.cleaned_data)
    messages.success(request, f"Đã {'cập nhật' if pk else 'thêm'} danh mục “{dm.ten_danhmuc}”.")
    return redirect("danh_muc")


CHUA_PHAN_LOAI = ("DM-CHUA-PL", "Chưa phân loại")


@admin_required
@require_POST
def danh_muc_delete(request, pk):
    """Admin được xóa:
    - danh mục đang hoạt động nhưng trống (không còn SP / danh mục con);
    - danh mục đã NGỪNG HOẠT ĐỘNG dù còn SP / danh mục con: danh mục con được chuyển lên danh mục cha,
      sản phẩm được chuyển sang danh mục cha (hoặc "Chưa phân loại" nếu là danh mục gốc) — sản phẩm và
      lịch sử giao dịch được giữ nguyên.
    """
    dm = get_object_or_404(DanhMuc, pk=pk)
    so_sp, so_con = dm.san_pham.count(), dm.con.count()
    if dm.is_active and (so_sp or so_con):
        messages.error(request, f"Không thể xóa “{dm.ten_danhmuc}” khi đang hoạt động và còn sản phẩm / danh mục con. "
                                "Hãy chuyển danh mục sang “Ngừng hoạt động” trước khi xóa.")
        return redirect("danh_muc")
    cha = dm.id_dmcha
    trung = DanhMuc.objects.filter(id_dmcha=cha, ten_danhmuc__in=dm.con.values("ten_danhmuc")).exclude(pk=dm.pk)
    if trung.exists():
        messages.error(request, f"Không thể xóa: danh mục con “{trung.first().ten_danhmuc}” bị trùng tên khi chuyển lên "
                                f"{'“' + cha.ten_danhmuc + '”' if cha else 'cấp gốc'}. Hãy đổi tên trước.")
        return redirect("danh_muc")
    try:
        with transaction.atomic():
            noi_nhan = cha
            if so_sp and noi_nhan is None:
                noi_nhan, _ = DanhMuc.objects.get_or_create(
                    ma_danhmuc=CHUA_PHAN_LOAI[0],
                    defaults={"ten_danhmuc": CHUA_PHAN_LOAI[1], "mo_ta": "Sản phẩm thuộc danh mục đã bị xóa"},
                )
                if noi_nhan.pk == dm.pk:
                    raise ProtectedError("Không thể xóa danh mục Chưa phân loại khi còn sản phẩm.", set())
            if so_sp:
                dm.san_pham.update(id_danhmuc=noi_nhan)
            if so_con:
                dm.con.update(id_dmcha=cha)
            ten = dm.ten_danhmuc
            dm.delete()
            audit(request, "XOA", "danh_muc", pk, {
                "ten": ten, "so_sp_chuyen": so_sp, "so_con_chuyen": so_con,
                "chuyen_sang": noi_nhan.ten_danhmuc if noi_nhan else "cấp gốc",
            })
        chuyen = []
        if so_sp:
            chuyen.append(f"{so_sp} sản phẩm → “{noi_nhan.ten_danhmuc}”")
        if so_con:
            chuyen.append(f"{so_con} danh mục con → {'“' + cha.ten_danhmuc + '”' if cha else 'cấp gốc'}")
        messages.success(request, f"Đã xóa danh mục “{ten}”." + (f" Đã chuyển {', '.join(chuyen)}." if chuyen else ""))
    except ProtectedError as e:
        messages.error(request, e.args[0] if e.args and isinstance(e.args[0], str) else
                       "Danh mục đang được tham chiếu, không thể xóa.")
    return redirect("danh_muc")


# ================================================================ SẢN PHẨM
SP_TABS = [("tat_ca", "Tất cả sản phẩm"), ("dang_ban", "Đang kinh doanh"), ("ngung", "Ngừng kinh doanh")]


def _sp_filter(request):
    qs = SanPham.objects.select_related("id_danhmuc")
    q, dm, tab = request.GET.get("q", "").strip(), request.GET.get("dm", ""), request.GET.get("tab", "tat_ca")
    canh_bao = request.GET.get("cb", "")
    if q:
        qs = qs.filter(Q(ten_sp__icontains=q) | Q(ma_sp__icontains=q))
    if dm:
        qs = qs.filter(Q(id_danhmuc_id=dm) | Q(id_danhmuc__id_dmcha_id=dm))
    if tab == "dang_ban":
        qs = qs.filter(trang_thai=1)
    elif tab == "ngung":
        qs = qs.filter(trang_thai=0)
    if canh_bao == "het":
        qs = qs.filter(ton_kho__lte=0)
    elif canh_bao == "sap_het":
        qs = qs.filter(ton_kho__gt=0, ton_kho__lte=F("nguong_toi_thieu"))
    sort = request.GET.get("sort", "ma_sp")
    if sort.lstrip("-") in ("ma_sp", "ten_sp", "gia_ban", "ton_kho"):
        qs = qs.order_by(sort)
    return qs, q, dm, tab, canh_bao, sort


def san_pham_list(request, form=None, form_pk=None):
    qs, q, dm, tab, cb, sort = _sp_filter(request)
    xem = None
    if request.GET.get("xem"):
        xem = SanPham.objects.select_related("id_danhmuc").filter(pk=request.GET["xem"]).first()
    ctx = {
        "active": "san_pham",
        "page": paginate(request, qs, 8),
        "q": q, "dm": dm, "tab": tab, "cb": cb, "sort": sort,
        "tabs": [(k, label, {"tat_ca": SanPham.objects.count(),
                             "dang_ban": SanPham.objects.filter(trang_thai=1).count(),
                             "ngung": SanPham.objects.filter(trang_thai=0).count()}[k]) for k, label in SP_TABS],
        "so_dm": DanhMuc.objects.count(),
        "danh_muc": DanhMuc.objects.filter(is_active=True),
        "xem": xem,
        "xem_lo": list(xem.lo_con_hang().select_related("id_sp")) if xem else [],
        "modal": _modal_state(form, form_pk) if form else None,
        "goi_y_ma": f"SP-{SanPham.objects.count() + 1:04d}",
        "don_vi_goi_y": sorted(set(SanPham.objects.values_list("don_vi", flat=True)) | {"Cái", "Hộp", "Chai", "Gói", "Lon", "Thùng", "Kg", "Ram"}),
    }
    return render(request, "catalog/san_pham.html", ctx)


def _upload_image(f):
    """Lưu ảnh lên Supabase Storage (nếu cấu hình) hoặc MEDIA_ROOT khi chạy local. Trả về URL."""
    if f.size > 5 * 1024 * 1024:
        raise ValueError("Ảnh tối đa 5 MB")
    ctype = f.content_type or mimetypes.guess_type(f.name)[0] or ""
    if ctype not in ("image/png", "image/jpeg", "image/webp"):
        raise ValueError("Chỉ chấp nhận ảnh PNG, JPG, WEBP")
    ext = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[ctype]
    name = f"sp/{uuid.uuid4().hex}.{ext}"
    if settings.SUPABASE_URL and settings.SUPABASE_SERVICE_KEY:
        url = f"{settings.SUPABASE_URL}/storage/v1/object/{settings.SUPABASE_BUCKET}/{name}"
        req = urllib.request.Request(url, data=f.read(), method="POST", headers={
            "Authorization": f"Bearer {settings.SUPABASE_SERVICE_KEY}",
            "apikey": settings.SUPABASE_SERVICE_KEY,
            "Content-Type": ctype,
            "x-upsert": "true",
        })
        with urllib.request.urlopen(req, timeout=20):
            pass
        return f"{settings.SUPABASE_URL}/storage/v1/object/public/{settings.SUPABASE_BUCKET}/{name}"
    if settings.ON_VERCEL:
        raise ValueError("Chưa cấu hình Supabase Storage để lưu ảnh")
    return settings.MEDIA_URL + default_storage.save(name, f)


@admin_required
@require_POST
def san_pham_save(request):
    pk = request.POST.get("pk")
    obj = get_object_or_404(SanPham, pk=pk) if pk else None
    form = SanPhamForm(request.POST, instance=obj)
    anh = request.FILES.get("anh")
    if form.is_valid() and anh:
        try:
            form.instance.anh_sp = _upload_image(anh)
        except Exception as e:  # noqa: BLE001 — hiển thị lỗi tải ảnh cho người dùng
            form.add_error(None, f"Không tải được ảnh: {e}")
    if not form.is_valid():
        return san_pham_list(request, form, pk)
    if request.POST.get("xoa_anh") and not anh:
        form.instance.anh_sp = None
    sp = form.save()
    audit(request, "SUA" if pk else "THEM", "san_pham", sp.pk, {k: str(v) for k, v in form.cleaned_data.items()})
    messages.success(request, f"Đã {'cập nhật' if pk else 'thêm'} sản phẩm {sp.ma_sp} - {sp.ten_sp}.")
    return redirect(f"/san-pham/?xem={sp.pk}")


@admin_required
@require_POST
def san_pham_toggle(request, pk):
    sp = get_object_or_404(SanPham, pk=pk)
    sp.trang_thai = 0 if sp.trang_thai == 1 else 1
    sp.save(update_fields=["trang_thai", "ngay_cap_nhat"])
    audit(request, "DOI_TRANG_THAI", "san_pham", pk, sp.get_trang_thai_display())
    messages.success(request, f"{sp.ma_sp}: chuyển sang “{sp.get_trang_thai_display()}”.")
    return redirect(request.META.get("HTTP_REFERER") or "san_pham")


@admin_required
@require_POST
def san_pham_delete(request, pk):
    sp = get_object_or_404(SanPham, pk=pk)
    if sp.co_giao_dich:
        sp.trang_thai = 0
        sp.save(update_fields=["trang_thai", "ngay_cap_nhat"])
        audit(request, "XOA_MEM", "san_pham", pk, sp.ma_sp)
        messages.warning(request, f"{sp.ma_sp} đã phát sinh giao dịch nên được chuyển sang Ngừng hoạt động thay vì xóa.")
    else:
        sp.delete()
        audit(request, "XOA", "san_pham", pk, sp.ma_sp)
        messages.success(request, f"Đã xóa sản phẩm {sp.ma_sp}.")
    return redirect("san_pham")


def san_pham_export(request):
    qs = _sp_filter(request)[0]
    rows = [
        [s.ma_sp, s.ten_sp, s.id_danhmuc.ten_danhmuc, s.don_vi, s.gia_ban, s.gia_von, s.ton_kho, s.nguong_toi_thieu,
         s.han_su_dung.strftime("%d/%m/%Y") if s.han_su_dung else "", s.get_trang_thai_display()]
        for s in qs
    ]
    return excel_response(
        "san_pham.xlsx", "Danh sách sản phẩm",
        ["Mã SP", "Tên SP", "Danh mục", "ĐVT", "Giá bán", "Giá vốn", "Tồn kho", "Ngưỡng tối thiểu", "HSD", "Trạng thái"],
        rows,
    )


# ================================================================ NHÀ CUNG CẤP
def _ncc_filter(request):
    qs = NhaCungCap.objects.annotate(so_phieu=Count("phieu_nhap")).order_by("ma_ncc")
    q, tt = request.GET.get("q", "").strip(), request.GET.get("tt", "")
    if q:
        qs = qs.filter(Q(ten_ncc__icontains=q) | Q(ma_ncc__icontains=q) | Q(so_dien_thoai__icontains=q)
                       | Q(email__icontains=q))
    if tt in ("1", "0"):
        qs = qs.filter(trang_thai=int(tt))
    return qs, q, tt


def ncc_list(request, form=None, form_pk=None):
    qs, q, tt = _ncc_filter(request)
    ctx = {
        "active": "ncc",
        "page": paginate(request, qs, 7),
        "q": q,
        "tt": tt,
        "tong": NhaCungCap.objects.count(),
        "dang_hd": NhaCungCap.objects.filter(trang_thai=1).count(),
        "ngung": NhaCungCap.objects.filter(trang_thai=0).count(),
        "co_phieu": NhaCungCap.objects.filter(phieu_nhap__isnull=False).distinct().count(),
        "modal": _modal_state(form, form_pk) if form else None,
        "goi_y_ma": f"NCC-{NhaCungCap.objects.count() + 1:04d}",
    }
    return render(request, "catalog/ncc.html", ctx)


@admin_required
@require_POST
def ncc_save(request):
    pk = request.POST.get("pk")
    obj = get_object_or_404(NhaCungCap, pk=pk) if pk else None
    data = request.POST.copy()
    data.setdefault("trang_thai", "1")
    form = NhaCungCapForm(data, instance=obj)
    if not form.is_valid():
        return ncc_list(request, form, pk)
    ncc = form.save()
    audit(request, "SUA" if pk else "THEM", "nha_cung_cap", ncc.pk, form.cleaned_data)
    messages.success(request, f"Đã {'cập nhật' if pk else 'thêm'} nhà cung cấp {ncc.ten_ncc}.")
    return redirect("ncc")


@admin_required
@require_POST
def ncc_toggle(request, pk):
    ncc = get_object_or_404(NhaCungCap, pk=pk)
    ncc.trang_thai = 0 if ncc.trang_thai == 1 else 1
    ncc.save(update_fields=["trang_thai", "ngay_cap_nhat"])
    audit(request, "DOI_TRANG_THAI", "nha_cung_cap", pk, ncc.get_trang_thai_display())
    messages.success(request, f"{ncc.ten_ncc}: {ncc.get_trang_thai_display().lower()}.")
    return redirect(request.META.get("HTTP_REFERER") or "ncc")


def ncc_export(request):
    qs = _ncc_filter(request)[0]
    rows = [[n.ma_ncc, n.ten_ncc, n.so_dien_thoai, n.email or "", n.dia_chi, n.get_trang_thai_display(), n.so_phieu]
            for n in qs]
    return excel_response("nha_cung_cap.xlsx", "Danh sách nhà cung cấp",
                          ["Mã NCC", "Tên NCC", "SĐT", "Email", "Địa chỉ", "Trạng thái", "Số phiếu nhập"], rows)
