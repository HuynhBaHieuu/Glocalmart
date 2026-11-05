"""Lớp nghiệp vụ: mọi thay đổi tồn kho đều đi qua post_stock_move(); số lượng theo LÔ đi qua tru_ton_fefo()
và các hàm lô bên dưới, nên luôn giữ được ràng buộc: tổng so_luong_con_lai các lô = SanPham.ton_kho."""
import json
from decimal import Decimal

from django.db import transaction
from django.db.models import Q, Sum
from django.utils import timezone

from .models import (
    AuditLog,
    ChiTietPhieuKiemKe,
    ChiTietPhieuNhap,
    DocSequence,
    NhaCungCap,
    NhatKyKho,
    PhanBoLoXuat,
    PhieuKiemKe,
    PhieuNhap,
    PhieuXuat,
    SanPham,
    thu_tu_fefo,
)


class NghiepVuError(Exception):
    """Lỗi vi phạm quy tắc nghiệp vụ — thông báo hiển thị thẳng cho người dùng."""


# ---------------------------------------------------------------- mã chứng từ
def next_doc_code(prefix, at=None):
    """Sinh mã dạng PREFIX-YYMM-#### ; khóa dòng để không trùng khi nhiều người tạo cùng lúc."""
    ky = timezone.localtime(at).strftime("%y%m")
    with transaction.atomic():
        seq, _ = DocSequence.objects.select_for_update().get_or_create(prefix=prefix, ky=ky)
        seq.so_cuoi += 1
        seq.save(update_fields=["so_cuoi"])
    return f"{prefix}-{ky}-{seq.so_cuoi:04d}"


# ---------------------------------------------------------------- audit
def audit(request_or_user, hanh_dong, doi_tuong, ma="", chi_tiet=None):
    user = getattr(request_or_user, "user", request_or_user)
    ip = ""
    if hasattr(request_or_user, "META"):
        meta = request_or_user.META
        ip = (meta.get("HTTP_X_FORWARDED_FOR", "").split(",")[0] or meta.get("REMOTE_ADDR", "")).strip()
    if isinstance(chi_tiet, (dict, list)):
        chi_tiet = json.dumps(chi_tiet, ensure_ascii=False, default=str)
    AuditLog.objects.create(
        nguoi_dung=user if getattr(user, "is_authenticated", False) else None,
        hanh_dong=hanh_dong,
        doi_tuong=doi_tuong,
        ma_doi_tuong=str(ma),
        chi_tiet=chi_tiet or "",
        ip=ip[:64],
    )


# ---------------------------------------------------------------- tồn kho
def post_stock_move(*, san_pham_id, loai, user, delta=None, set_to=None, phieu_nhap=None, phieu_xuat=None,
                    phieu_kiem=None):
    """Hàm dịch vụ DUY NHẤT thay đổi ton_kho. Phải gọi bên trong transaction.atomic().

    - delta: cộng/trừ tương đối (nhập/xuất)
    - set_to: ghi đè tuyệt đối (kiểm kê cân bằng)
    Chặn âm kho, ghi NHAT_KY_KHO.
    """
    sp = SanPham.objects.select_for_update().get(pk=san_pham_id)
    truoc = sp.ton_kho
    sau = Decimal(set_to) if set_to is not None else truoc + Decimal(delta)
    if sau < 0:
        raise NghiepVuError(
            f"Không đủ tồn kho cho {sp.ma_sp} - {sp.ten_sp}: tồn {fmt(truoc)} {sp.don_vi}, cần xuất {fmt(-Decimal(delta))}."
        )
    sp.ton_kho = sau
    sp.save(update_fields=["ton_kho", "ngay_cap_nhat"])
    NhatKyKho.objects.create(
        loai_giao_dich=loai,
        ma_phieu_nhap=phieu_nhap,
        ma_phieu_xuat=phieu_xuat,
        ma_phieu_kiem=phieu_kiem,
        id_sp=sp,
        sl_truoc=truoc,
        sl_sau=sau,
        sl_thay_doi=sau - truoc,
        nguoi_thuc_hien=user,
    )
    return sp


def la_so_nguyen(d):
    return d is not None and Decimal(d) == Decimal(d).to_integral_value()


def fmt(d):
    d = Decimal(d).normalize()
    return f"{d:f}"


# ---------------------------------------------------------------- lô hàng (FEFO)
def lo_con_hang_qs(san_pham_id, chi_lo_con_han=False):
    """Các lô còn hàng của sản phẩm theo thứ tự FEFO."""
    qs = ChiTietPhieuNhap.objects.filter(id_sp_id=san_pham_id, ma_phieu_nhap__trang_thai=PhieuNhap.DA_XAC_NHAN,
                                         so_luong_con_lai__gt=0)
    if chi_lo_con_han:
        qs = qs.filter(Q(han_su_dung__isnull=True) | Q(han_su_dung__gte=timezone.localdate()))
    return thu_tu_fefo(qs)


def kiem_tra_tong_lo(san_pham_ids=None):
    """Ràng buộc lô: tổng so_luong_con_lai các lô = SanPham.ton_kho. Trả về list (ma_sp, ton_kho, tong_lo) bị lệch."""
    from . import lo
    return lo.kiem_tra_tong_lo(SanPham, ChiTietPhieuNhap, san_pham_ids)


def cap_nhat_hsd_san_pham(san_pham_id):
    """SanPham.han_su_dung = hạn sớm nhất của các lô còn hàng (không nhập tay ở trang sản phẩm)."""
    hsd = (lo_con_hang_qs(san_pham_id).filter(han_su_dung__isnull=False)
           .order_by("han_su_dung").values_list("han_su_dung", flat=True).first())
    SanPham.objects.filter(pk=san_pham_id).update(han_su_dung=hsd)


def ton_con_han_theo_sp(san_pham_ids=None):
    """{id_sp: số lượng thuộc các lô chưa hết hạn} — 1 truy vấn cho nhiều sản phẩm."""
    qs = (ChiTietPhieuNhap.objects.filter(ma_phieu_nhap__trang_thai=PhieuNhap.DA_XAC_NHAN, so_luong_con_lai__gt=0)
          .filter(Q(han_su_dung__isnull=True) | Q(han_su_dung__gte=timezone.localdate())))
    if san_pham_ids is not None:
        qs = qs.filter(id_sp_id__in=san_pham_ids)
    return dict(qs.values("id_sp_id").annotate(s=Sum("so_luong_con_lai")).values_list("id_sp_id", "s"))


def tru_ton_fefo(san_pham_id, so_luong, *, chi_lo_con_han=False, ct_xuat=None):
    """Trừ so_luong vào các lô còn hàng theo FEFO: hạn tăng dần (không hạn xếp cuối), cùng hạn thì lô nhập trước.

    Trừ hết lô này mới sang lô kế. Không đủ → NghiepVuError (caller đang trong transaction nên rollback toàn bộ).
    chi_lo_con_han: bỏ qua lô đã hết hạn (xuất Bán hàng / Điều chỉnh). Trả về list[(lô, số lượng đã trừ)].
    Gọi trong transaction.atomic() và SAU khi đã khóa dòng sản phẩm (select_for_update).
    """
    can = Decimal(so_luong)
    lots = list(lo_con_hang_qs(san_pham_id, chi_lo_con_han))
    co = sum((lo.so_luong_con_lai for lo in lots), Decimal(0))
    if co < can:
        sp = SanPham.objects.get(pk=san_pham_id)
        them = " còn hạn" if chi_lo_con_han else ""
        raise NghiepVuError(f"Không đủ hàng trong các lô{them} của {sp.ma_sp} - {sp.ten_sp}: "
                            f"còn {fmt(co)} {sp.don_vi}, cần {fmt(can)}.")
    da_tru = []
    for lo in lots:
        if can <= 0:
            break
        lay = min(can, lo.so_luong_con_lai)
        lo.so_luong_con_lai -= lay
        lo.save(update_fields=["so_luong_con_lai"])
        if ct_xuat is not None:
            PhanBoLoXuat.objects.create(ct_xuat=ct_xuat, lo=lo, so_luong=lay)
        da_tru.append((lo, lay))
        can -= lay
    return da_tru


def _phieu_he_thong(ma, user, ghi_chu):
    """Phiếu nhập hệ thống (đã xác nhận) chứa lô không đến từ nhà cung cấp — VD hàng thừa khi kiểm kê."""
    from . import lo
    phieu = PhieuNhap.objects.filter(pk=ma).first()
    if phieu:
        return phieu
    now = timezone.now()
    return PhieuNhap.objects.create(
        ma_phieu_nhap=ma, id_ncc=lo.ncc_noi_bo(NhaCungCap), nguoi_tao=user, ngay_tao=now,
        trang_thai_giao=PhieuNhap.DA_GIAO, ngay_cap_nhat_giao=now, trang_thai=PhieuNhap.DA_XAC_NHAN,
        nguoi_xac_nhan=user, ngay_xac_nhan=now, ghi_chu=ghi_chu,
    )


def _tra_ve_lo(sp, so_luong, user):
    """Cộng lại hàng không rõ lô gốc (phiếu xuất xác nhận trước khi có quản lý lô) vào lô nhập gần nhất."""
    lo = (ChiTietPhieuNhap.objects.filter(id_sp=sp, ma_phieu_nhap__trang_thai=PhieuNhap.DA_XAC_NHAN)
          .order_by("-ma_phieu_nhap__ngay_xac_nhan", "-id_chi_tiet").first())
    if lo is None:
        phieu = _phieu_he_thong(PhieuNhap.MA_TON_DAU, user,
                                "Phiếu hệ thống: phần tồn kho có trước khi quản lý theo lô (không phải hàng nhập mới).")
        lo = ChiTietPhieuNhap.objects.create(ma_phieu_nhap=phieu, id_sp=sp, so_luong_dat=0, don_gia_nhap=sp.gia_von,
                                             so_luong_thuc_nhan=0, so_luong_con_lai=0)
    lo.so_luong_con_lai += so_luong
    lo.save(update_fields=["so_luong_con_lai"])


def sua_han_lo(lo_id, han_moi, ly_do, user):
    """Sửa hạn sử dụng của lô đã nhập kho (khi phát hiện nhập sai). Không đổi số lượng; ghi NHAT_KY_KHO:
    lô, hạn cũ, hạn mới, người sửa, thời điểm, lý do."""
    ly_do = (ly_do or "").strip()
    if not ly_do:
        raise NghiepVuError("Bắt buộc nhập lý do sửa hạn sử dụng.")
    with transaction.atomic():
        lo = ChiTietPhieuNhap.objects.select_related("ma_phieu_nhap").get(pk=lo_id)
        sp = SanPham.objects.select_for_update().get(pk=lo.id_sp_id)
        lo.refresh_from_db()
        if lo.ma_phieu_nhap.trang_thai != PhieuNhap.DA_XAC_NHAN:
            raise NghiepVuError("Chỉ sửa hạn cho lô của phiếu đã xác nhận. Phiếu chưa xác nhận hãy sửa ở bước đối soát.")
        if lo.so_luong_con_lai <= 0:
            raise NghiepVuError("Lô đã hết hàng, không cần sửa hạn.")
        if lo.han_su_dung == han_moi:
            raise NghiepVuError("Hạn mới trùng với hạn hiện tại.")
        han_cu = lo.han_su_dung
        lo.han_su_dung = han_moi
        lo.save(update_fields=["han_su_dung"])
        NhatKyKho.objects.create(
            loai_giao_dich=NhatKyKho.SUA_HAN_LO, ma_phieu_nhap=lo.ma_phieu_nhap, id_sp=sp, lo=lo,
            sl_truoc=sp.ton_kho, sl_sau=sp.ton_kho, sl_thay_doi=0, nguoi_thuc_hien=user,
            han_cu=han_cu, han_moi=han_moi, ly_do=ly_do,
        )
        cap_nhat_hsd_san_pham(sp.pk)
    return lo


def canh_bao_han_su_dung():
    """Cảnh báo theo LÔ: lô còn hàng, có hạn, sản phẩm đang hoạt động; con_ngay = hạn − hôm nay.

    con_ngay < 0 → DA_HET_HAN ; 0 ≤ con_ngay ≤ so_ngay_canh_bao → SAP_HET_HAN ; còn lại không hiển thị.
    Sắp xếp theo hạn tăng dần.
    """
    lots = (ChiTietPhieuNhap.objects
            .filter(ma_phieu_nhap__trang_thai=PhieuNhap.DA_XAC_NHAN, so_luong_con_lai__gt=0, han_su_dung__isnull=False,
                    id_sp__trang_thai=SanPham.DANG_HOAT_DONG)
            .select_related("id_sp__id_danhmuc", "ma_phieu_nhap").order_by("han_su_dung", "id_chi_tiet"))
    return [lo for lo in lots if lo.muc_han in ("DA_HET_HAN", "SAP_HET_HAN")]


# ---------------------------------------------------------------- nhập kho
GIAO_THU_TU = [PhieuNhap.CHO_GIAO, PhieuNhap.DANG_GIAO, PhieuNhap.DA_GIAO]


def chuyen_trang_thai_giao(phieu: PhieuNhap, moi: str, user):
    if phieu.trang_thai != PhieuNhap.CHUA_XAC_NHAN:
        raise NghiepVuError("Phiếu đã chốt hoặc đã hủy, không thể cập nhật giao hàng.")
    cu_idx, moi_idx = GIAO_THU_TU.index(phieu.trang_thai_giao), GIAO_THU_TU.index(moi)
    if moi_idx != cu_idx + 1:
        raise NghiepVuError("Trạng thái bắt buộc chuyển tuần tự Chờ giao → Đang giao → Đã giao, không được nhảy cóc.")
    if moi == PhieuNhap.DA_GIAO:
        raise NghiepVuError("Chuyển sang 'Đã giao' phải thực hiện qua bước Kiểm tra & Đối soát hàng hóa.")
    phieu.trang_thai_giao = moi
    phieu.ngay_cap_nhat_giao = timezone.now()
    phieu.save(update_fields=["trang_thai_giao", "ngay_cap_nhat_giao"])


def lo_can_han(ct):
    """Lô nhận vào đã hết hạn hoặc còn ≤ số ngày cảnh báo của sản phẩm → cần nhân viên xác nhận lại."""
    if not ct.han_su_dung:
        return None
    con = (ct.han_su_dung - timezone.localdate()).days
    if con < 0:
        return "đã hết hạn"
    if con <= ct.id_sp.so_ngay_canh_bao:
        return "cận hạn"
    return None


def xac_nhan_phieu_nhap(ma_phieu, dong_doi_soat, user, ghi_chu=None, dong_moi=(), xoa=(), ly_do_can_han=None):
    """Đối soát & chốt phiếu nhập: mỗi dòng thành 1 LÔ (so_luong_con_lai = SL thực nhận), cộng tồn,
    tính giá vốn bình quân, cập nhật HSD sản phẩm. Sau khi xác nhận, hạn trên phiếu bị khóa.

    dong_doi_soat: {id_chi_tiet: {"sl": Decimal, "hsd": date|None, "ly_do": str|None}}
    dong_moi: [{"goc": id_chi_tiet, "sl": Decimal, "hsd": date|None}] — thêm lô cùng sản phẩm nhưng khác hạn
    xoa: id các dòng tách (SL đặt = 0) cần bỏ
    ly_do_can_han: lý do vẫn nhận lô cận hạn / đã hết hạn (bắt buộc nếu có lô như vậy)
    """
    with transaction.atomic():
        phieu = PhieuNhap.objects.select_for_update().get(pk=ma_phieu)
        if phieu.trang_thai != PhieuNhap.CHUA_XAC_NHAN:
            raise NghiepVuError("Phiếu đã được xác nhận hoặc đã hủy.")
        if phieu.trang_thai_giao != PhieuNhap.DANG_GIAO:
            raise NghiepVuError("Chỉ đối soát khi phiếu đang ở trạng thái 'Đang giao'.")
        _luu_doi_soat(phieu, dong_doi_soat, ghi_chu, bat_buoc=True, dong_moi=dong_moi, xoa=xoa,
                      ly_do_can_han=ly_do_can_han)

        sp_ids = set()
        for ct in phieu.chi_tiet.all():
            sl = ct.so_luong_thuc_nhan
            sp = SanPham.objects.select_for_update().get(pk=ct.id_sp_id)
            # giá vốn bình quân gia quyền
            ton_cu = max(sp.ton_kho, Decimal(0))
            tong = ton_cu + sl
            if tong > 0 and sl > 0:
                sp.gia_von = ((ton_cu * sp.gia_von + sl * ct.don_gia_nhap) / tong).quantize(Decimal(1))
                sp.save(update_fields=["gia_von", "ngay_cap_nhat"])
            ct.so_luong_con_lai = sl
            ct.save(update_fields=["so_luong_con_lai"])
            if sl:
                post_stock_move(san_pham_id=sp.pk, loai="NHAP_KHO", user=user, delta=sl, phieu_nhap=phieu)
            sp_ids.add(sp.pk)

        phieu.trang_thai_giao = PhieuNhap.DA_GIAO
        phieu.ngay_cap_nhat_giao = timezone.now()
        phieu.trang_thai = PhieuNhap.DA_XAC_NHAN
        phieu.nguoi_xac_nhan = user
        phieu.ngay_xac_nhan = timezone.now()
        phieu.save()
        for sp_id in sp_ids:  # sau khi phiếu đã xác nhận thì các dòng mới được tính là lô
            cap_nhat_hsd_san_pham(sp_id)
    return phieu


def luu_nhap_doi_soat(ma_phieu, dong_doi_soat, ghi_chu, dong_moi=(), xoa=()):
    with transaction.atomic():
        phieu = PhieuNhap.objects.select_for_update().get(pk=ma_phieu)
        if phieu.trang_thai != PhieuNhap.CHUA_XAC_NHAN:
            raise NghiepVuError("Phiếu đã được xác nhận hoặc đã hủy.")
        _luu_doi_soat(phieu, dong_doi_soat, ghi_chu, bat_buoc=False, dong_moi=dong_moi, xoa=xoa)
    return phieu


def _luu_doi_soat(phieu, dong_doi_soat, ghi_chu, bat_buoc, dong_moi=(), xoa=(), ly_do_can_han=None):
    loi = []
    ly_do_can_han = (ly_do_can_han or "").strip()
    cts = {ct.pk: ct for ct in phieu.chi_tiet.select_related("id_sp")}
    dong_doi_soat = dict(dong_doi_soat)
    # bỏ các dòng tách không dùng nữa (chỉ dòng thêm lúc đối soát, không có SL đặt)
    for pk in xoa:
        ct = cts.get(pk)
        if ct and ct.la_dong_tach:
            ct.delete()
            del cts[pk]
    # thêm lô mới cho cùng sản phẩm (hàng giao về có 2 hạn khác nhau)
    for d in dong_moi:
        goc = cts.get(d.get("goc"))
        if not goc:
            continue
        ct = ChiTietPhieuNhap.objects.create(ma_phieu_nhap=phieu, id_sp=goc.id_sp, so_luong_dat=0,
                                             don_gia_nhap=goc.don_gia_nhap)
        cts[ct.pk] = ct
        dong_doi_soat[ct.pk] = {"sl": d.get("sl"), "hsd": d.get("hsd"), "ly_do": None}

    nhom = {}
    for ct in cts.values():
        d = dong_doi_soat.get(ct.pk, {})
        sl = d.get("sl")
        if sl is not None and sl < 0:
            loi.append(f"{ct.id_sp.ten_sp}: số lượng thực nhận không được âm.")
            sl = None
        if sl is None and bat_buoc:
            loi.append(f"{ct.id_sp.ten_sp}: chưa nhập số lượng thực nhận" + (" của lô tách." if ct.la_dong_tach else "."))
        if ct.la_dong_tach and bat_buoc and sl is not None and sl <= 0:
            loi.append(f"{ct.id_sp.ten_sp}: lô tách phải có số lượng lớn hơn 0 (hoặc xóa dòng).")
        ct.so_luong_thuc_nhan = sl
        ct.han_su_dung = d.get("hsd")  # để trống = sản phẩm không có hạn sử dụng
        nhom.setdefault(ct.id_sp_id, []).append((ct, d.get("ly_do") or None))

    # chênh lệch tính theo TỔNG các lô của cùng 1 sản phẩm; lý do ghi ở dòng gốc
    for dong in nhom.values():
        goc, ly_do = next(((ct, l) for ct, l in dong if not ct.la_dong_tach), dong[0])
        dat = sum((ct.so_luong_dat for ct, _ in dong), Decimal(0))
        nhan = sum((ct.so_luong_thuc_nhan or Decimal(0) for ct, _ in dong), Decimal(0))
        for ct, _ in dong:
            ct.ly_do_chenh_lech = None
        if all(ct.so_luong_thuc_nhan is not None for ct, _ in dong) and nhan != dat:
            if not ly_do and bat_buoc:
                loi.append(f"{goc.id_sp.ten_sp}: SL thực nhận khác SL đặt — bắt buộc chọn lý do chênh lệch.")
            goc.ly_do_chenh_lech = ly_do

    # lô cận hạn / đã hết hạn: không chặn lưu, nhưng khi chốt phiếu phải xác nhận lại kèm lý do
    can_han = [(ct, lo_can_han(ct)) for ct in cts.values() if lo_can_han(ct)]
    if can_han and bat_buoc and not ly_do_can_han:
        ds = "; ".join(f"{ct.id_sp.ten_sp} (HSD {ct.han_su_dung:%d/%m/%Y}, {loai})" for ct, loai in can_han)
        loi.append(f"Lô hàng cận hạn/đã hết hạn: {ds}. Vui lòng xác nhận lại và nhập lý do vẫn nhận hàng.")
    for ct in cts.values():
        loai = lo_can_han(ct)
        if loai and ly_do_can_han:
            ct.ghi_chu_doi_soat = f"Lô {loai} (HSD {ct.han_su_dung:%d/%m/%Y}) — lý do nhận: {ly_do_can_han}"
        elif not loai:
            ct.ghi_chu_doi_soat = None
        ct.save()
    if loi:
        raise NghiepVuError(" ".join(dict.fromkeys(loi)))
    phieu.ghi_chu_doi_soat = ghi_chu
    phieu.save(update_fields=["ghi_chu_doi_soat"])


def huy_phieu_nhap(ma_phieu, user, ly_do):
    """Hủy phiếu kèm lý do. Phiếu đã xác nhận: chỉ Admin, và chỉ khi chưa lô nào bị xuất / kiểm kê bớt."""
    ly_do = (ly_do or "").strip()
    if not ly_do:
        raise NghiepVuError("Vui lòng nhập lý do hủy phiếu.")
    with transaction.atomic():
        phieu = PhieuNhap.objects.select_for_update().get(pk=ma_phieu)
        if phieu.trang_thai == PhieuNhap.DA_HUY:
            raise NghiepVuError("Phiếu đã bị hủy trước đó.")
        if phieu.la_phieu_he_thong:
            raise NghiepVuError("Phiếu do hệ thống tạo (tồn đầu kỳ / hàng thừa kiểm kê), không thể hủy.")
        if phieu.trang_thai == PhieuNhap.DA_XAC_NHAN:
            if not user.is_admin:
                raise NghiepVuError("Chỉ Quản trị viên được hủy phiếu đã xác nhận.")
            sp_ids = set()
            for ct in phieu.chi_tiet.select_related("id_sp"):
                SanPham.objects.select_for_update().get(pk=ct.id_sp_id)
                ct.refresh_from_db()
                da_dung = (ct.so_luong_thuc_nhan or 0) - ct.so_luong_con_lai
                if da_dung > 0:
                    raise NghiepVuError(f"Lô {ct.id_sp.ten_sp} của phiếu này đã được xuất / kiểm kê bớt {fmt(da_dung)} "
                                        f"{ct.id_sp.don_vi} — không thể hủy phiếu.")
                if ct.so_luong_thuc_nhan:
                    ct.so_luong_con_lai = 0
                    ct.save(update_fields=["so_luong_con_lai"])
                    post_stock_move(san_pham_id=ct.id_sp_id, loai="NHAP_KHO", user=user,
                                    delta=-ct.so_luong_thuc_nhan, phieu_nhap=phieu)
                sp_ids.add(ct.id_sp_id)
            for sp_id in sp_ids:
                cap_nhat_hsd_san_pham(sp_id)
        phieu.trang_thai = PhieuNhap.DA_HUY
        phieu.ly_do_huy = ly_do
        phieu.save(update_fields=["trang_thai", "ly_do_huy"])
    return phieu


# ---------------------------------------------------------------- xuất kho
def kiem_tra_dong_xuat(ly_do, dong):
    """dong: list[(SanPham, Decimal)] — kiểm tra tồn khả dụng theo thời gian thực.

    Lô hết hạn chỉ được xuất với lý do Hủy hàng → Bán hàng / Điều chỉnh chỉ lấy được phần thuộc lô còn hạn.
    """
    loi = []
    if not dong:
        loi.append("Cần chọn ít nhất một sản phẩm.")
    seen = set()
    con_han = ton_con_han_theo_sp([sp.pk for sp, _ in dong])
    for sp, sl in dong:
        if sp.pk in seen:
            loi.append(f"{sp.ten_sp} bị chọn trùng.")
        seen.add(sp.pk)
        if sl <= 0:
            loi.append(f"{sp.ten_sp}: số lượng xuất phải lớn hơn 0.")
        elif not la_so_nguyen(sl):
            loi.append(f"{sp.ten_sp}: số lượng xuất phải là số nguyên, không nhập số thập phân.")
        elif sl > sp.ton_kho:
            loi.append(f"{sp.ten_sp}: vượt tồn kho khả dụng ({fmt(sp.ton_kho)} {sp.don_vi}).")
        elif ly_do != PhieuXuat.HUY_HANG and sl > con_han.get(sp.pk, Decimal(0)):
            loi.append(f"{sp.ten_sp}: chỉ còn {fmt(con_han.get(sp.pk, 0))} {sp.don_vi} thuộc lô còn hạn — "
                       f"lô đã hết hạn chỉ được xuất với lý do Hủy hàng.")
        if sp.trang_thai != SanPham.DANG_HOAT_DONG and ly_do == PhieuXuat.BAN_HANG:
            loi.append(f"{sp.ten_sp} đang ngừng kinh doanh, không thể xuất bán.")
    if loi:
        raise NghiepVuError(" ".join(loi))


def xac_nhan_phieu_xuat(ma_phieu, user):
    """Xác nhận phiếu xuất (mọi lý do): trừ tồn và trừ vào các lô theo FEFO, ghi phân bổ lô."""
    with transaction.atomic():
        phieu = PhieuXuat.objects.select_for_update().get(pk=ma_phieu)
        if phieu.trang_thai != PhieuXuat.CHUA_XAC_NHAN:
            raise NghiepVuError("Phiếu đã được xác nhận hoặc đã hủy.")
        cts = list(phieu.chi_tiet.select_related("id_sp"))
        # khóa dòng & kiểm tra lại tồn tại thời điểm xác nhận
        sps = {s.pk: s for s in SanPham.objects.select_for_update().filter(pk__in=[c.id_sp_id for c in cts])}
        kiem_tra_dong_xuat(phieu.ly_do_xuat, [(sps[c.id_sp_id], c.so_luong_xuat) for c in cts])
        for c in cts:
            tru_ton_fefo(c.id_sp_id, c.so_luong_xuat, chi_lo_con_han=phieu.ly_do_xuat != PhieuXuat.HUY_HANG, ct_xuat=c)
            post_stock_move(san_pham_id=c.id_sp_id, loai="XUAT_KHO", user=user, delta=-c.so_luong_xuat,
                            phieu_xuat=phieu)
            cap_nhat_hsd_san_pham(c.id_sp_id)
        phieu.trang_thai = PhieuXuat.DA_XAC_NHAN
        phieu.nguoi_xac_nhan = user
        phieu.ngay_xac_nhan = timezone.now()
        phieu.save()
    return phieu


def huy_phieu_xuat(ma_phieu, user, ly_do):
    """Hủy phiếu xuất kèm lý do. Phiếu đã xác nhận (chỉ Admin): hoàn tồn và trả hàng về ĐÚNG các lô đã lấy."""
    ly_do = (ly_do or "").strip()
    if not ly_do:
        raise NghiepVuError("Vui lòng nhập lý do hủy phiếu.")
    with transaction.atomic():
        phieu = PhieuXuat.objects.select_for_update().get(pk=ma_phieu)
        if phieu.trang_thai == PhieuXuat.DA_HUY:
            raise NghiepVuError("Phiếu đã bị hủy trước đó.")
        if phieu.trang_thai == PhieuXuat.DA_XAC_NHAN:
            if not user.is_admin:
                raise NghiepVuError("Chỉ Quản trị viên được hủy phiếu đã xác nhận.")
            for ct in phieu.chi_tiet.select_related("id_sp"):
                sp = SanPham.objects.select_for_update().get(pk=ct.id_sp_id)
                da_tra = Decimal(0)
                for pb in ct.phan_bo.select_related("lo"):
                    pb.lo.so_luong_con_lai += pb.so_luong
                    pb.lo.save(update_fields=["so_luong_con_lai"])
                    da_tra += pb.so_luong
                ct.phan_bo.all().delete()
                if ct.so_luong_xuat > da_tra:  # phiếu xác nhận từ trước khi quản lý theo lô
                    _tra_ve_lo(sp, ct.so_luong_xuat - da_tra, user)
                post_stock_move(san_pham_id=sp.pk, loai="XUAT_KHO", user=user, delta=ct.so_luong_xuat,
                                phieu_xuat=phieu)
                cap_nhat_hsd_san_pham(sp.pk)
        phieu.trang_thai = PhieuXuat.DA_HUY
        phieu.ly_do_huy = ly_do
        phieu.save(update_fields=["trang_thai", "ly_do_huy"])
    return phieu


# ---------------------------------------------------------------- kiểm kê
def ghi_dem(phieu: PhieuKiemKe, lan: int, so_lieu: dict, ghi_chu: dict):
    """Lưu kết quả đếm mù. Lần 1: chụp sl_he_thong (ẩn) và gắn cờ chênh lệch. Lần 2: chỉ dòng bị gắn cờ.
    Mỗi lần đếm chỉ lưu một lần (không ghi đè kết quả đã có)."""
    if phieu.trang_thai != PhieuKiemKe.DANG_KIEM:
        raise NghiepVuError("Phiếu không ở trạng thái đang kiểm.")
    with transaction.atomic():
        for ct in phieu.chi_tiet.select_related("id_sp"):
            if ct.pk not in so_lieu:
                continue
            sl = so_lieu[ct.pk]
            if sl is None or sl < 0:
                raise NghiepVuError(f"{ct.id_sp.ten_sp}: số lượng đếm không hợp lệ.")
            if not la_so_nguyen(sl):
                raise NghiepVuError(f"{ct.id_sp.ten_sp}: số lượng đếm phải là số nguyên, không nhập số thập phân.")
            if lan == 1:
                if ct.sl_dem_lan_1 is not None:
                    raise NghiepVuError(f"{ct.id_sp.ten_sp}: đã có kết quả đếm lần 1.")
                ct.sl_dem_lan_1 = sl
                ct.sl_dem_lan_2 = None
                ct.sl_he_thong = ct.id_sp.ton_kho
                ct.gia_von = ct.id_sp.gia_von
            else:
                if not ct.co_chenh_lech:
                    continue
                if ct.sl_dem_lan_2 is not None:
                    raise NghiepVuError(f"{ct.id_sp.ten_sp}: đã có kết quả đếm lần 2.")
                ct.sl_dem_lan_2 = sl
            if ct.pk in ghi_chu:
                ct.ghi_chu = ghi_chu[ct.pk][:255]
            ct.sl_chenh_lech = ct.sl_dem_thuc_te - ct.sl_he_thong
            if lan == 1:
                ct.co_chenh_lech = ct.sl_chenh_lech != 0
            ct.save()


def gui_duyet(phieu: PhieuKiemKe, hsd_thua=None):
    """Gửi duyệt. hsd_thua: {id_chi_tiet: date|None} — hạn sử dụng nhân viên nhập tay cho phần hàng THỪA
    (None = hàng không có hạn). Mọi dòng thừa bắt buộc phải khai báo trước khi gửi."""
    hsd_thua = hsd_thua or {}
    if phieu.trang_thai != PhieuKiemKe.DANG_KIEM:
        raise NghiepVuError("Phiếu không ở trạng thái đang kiểm.")
    if not phieu.da_dem_lan_1:
        raise NghiepVuError("Chưa hoàn tất đếm lần 1 cho tất cả sản phẩm.")
    if phieu.can_dem_lan_2:
        raise NghiepVuError("Còn sản phẩm lệch số cần đếm lần 2 trước khi gửi duyệt.")
    with transaction.atomic():
        thieu = []
        for ct in phieu.chi_tiet.select_related("id_sp"):
            if ct.sl_thua > 0:
                if ct.pk in hsd_thua:
                    ct.hsd_thua_da_khai_bao, ct.han_su_dung_thua = True, hsd_thua[ct.pk]
                elif not ct.hsd_thua_da_khai_bao:
                    thieu.append(ct.id_sp.ten_sp)
            else:
                ct.hsd_thua_da_khai_bao, ct.han_su_dung_thua = False, None
            ct.save(update_fields=["hsd_thua_da_khai_bao", "han_su_dung_thua"])
        if thieu:
            raise NghiepVuError("Nhập hạn sử dụng cho phần hàng thừa (hoặc chọn “Không có HSD”): " + ", ".join(thieu) + ".")
        phieu.trang_thai = PhieuKiemKe.CHO_DUYET
        phieu.ngay_gui_duyet = timezone.now()
        phieu.save(update_fields=["trang_thai", "ngay_gui_duyet"])


def duyet_kiem_ke(ma_phieu, user):
    """Xác nhận & cân bằng tồn kho về SL thực tế, ghi NHAT_KY_KHO.

    Thiếu → trừ phần thiếu vào các lô theo FEFO. Thừa → tạo lô mới với hạn sử dụng nhân viên đã nhập tay.
    """
    with transaction.atomic():
        phieu = PhieuKiemKe.objects.select_for_update().get(pk=ma_phieu)
        if phieu.trang_thai != PhieuKiemKe.CHO_DUYET:
            raise NghiepVuError("Chỉ duyệt được phiếu đang chờ duyệt.")
        for ct in phieu.chi_tiet.select_related("id_sp"):
            sp = SanPham.objects.select_for_update().get(pk=ct.id_sp_id)
            lech = ct.sl_dem_thuc_te - max(sp.ton_kho, Decimal(0))
            if lech < 0:
                tru_ton_fefo(sp.pk, -lech)
            elif lech > 0:
                if not ct.hsd_thua_da_khai_bao:
                    raise NghiepVuError(f"{sp.ten_sp}: tồn kho đã thay đổi sau khi đếm, phần thừa {fmt(lech)} {sp.don_vi} "
                                        "chưa có hạn sử dụng — hãy từ chối phiếu để nhân viên đếm lại.")
                lo_phieu = _phieu_he_thong(f"PN-{phieu.pk}", user, f"Lô hàng thừa phát hiện khi kiểm kê {phieu.pk}.")
                ChiTietPhieuNhap.objects.create(
                    ma_phieu_nhap=lo_phieu, id_sp=sp, so_luong_dat=lech, don_gia_nhap=sp.gia_von,
                    so_luong_thuc_nhan=lech, so_luong_con_lai=lech, han_su_dung=ct.han_su_dung_thua,
                    ghi_chu_doi_soat=f"Hàng thừa kiểm kê {phieu.pk}",
                )
            post_stock_move(san_pham_id=sp.pk, loai="KIEM_KE", user=user, set_to=ct.sl_dem_thuc_te, phieu_kiem=phieu)
            cap_nhat_hsd_san_pham(sp.pk)
        phieu.trang_thai = PhieuKiemKe.HOAN_THANH
        phieu.nguoi_duyet = user
        phieu.ngay_duyet = timezone.now()
        phieu.save()
    return phieu


def tu_choi_kiem_ke(phieu: PhieuKiemKe, user, ly_do):
    if phieu.trang_thai != PhieuKiemKe.CHO_DUYET:
        raise NghiepVuError("Chỉ từ chối được phiếu đang chờ duyệt.")
    if not (ly_do or "").strip():
        raise NghiepVuError("Vui lòng nhập lý do từ chối.")
    phieu.trang_thai = PhieuKiemKe.BI_TU_CHOI
    phieu.nguoi_duyet = user
    phieu.ngay_duyet = timezone.now()
    phieu.ly_do_tu_choi = ly_do.strip()
    phieu.save()


def dem_lai(phieu: PhieuKiemKe):
    """Phiếu bị từ chối → mở lại để đếm từ đầu (xóa kết quả đếm cũ)."""
    if phieu.trang_thai != PhieuKiemKe.BI_TU_CHOI:
        raise NghiepVuError("Chỉ phiếu bị từ chối mới được đếm lại.")
    ChiTietPhieuKiemKe.objects.filter(ma_phieu_kiem=phieu).update(
        sl_dem_lan_1=None, sl_dem_lan_2=None, sl_he_thong=None, co_chenh_lech=False, sl_chenh_lech=0,
        hsd_thua_da_khai_bao=False, han_su_dung_thua=None,
    )
    phieu.trang_thai = PhieuKiemKe.DANG_KIEM
    phieu.ngay_gui_duyet = None
    phieu.save(update_fields=["trang_thai", "ngay_gui_duyet"])
