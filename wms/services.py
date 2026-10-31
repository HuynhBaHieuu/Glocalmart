"""Lớp nghiệp vụ: mọi thay đổi tồn kho đều đi qua post_stock_move()."""
import json
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import (
    AuditLog,
    ChiTietPhieuKiemKe,
    DocSequence,
    NhatKyKho,
    PhieuKiemKe,
    PhieuNhap,
    PhieuXuat,
    SanPham,
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


def fmt(d):
    d = Decimal(d).normalize()
    return f"{d:f}"


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


def xac_nhan_phieu_nhap(ma_phieu, dong_doi_soat, user, ghi_chu=None):
    """Đối soát & chốt phiếu nhập → cộng tồn, tính giá vốn bình quân, cập nhật HSD sớm nhất.

    dong_doi_soat: {id_chi_tiet: {"sl": Decimal, "hsd": date|None, "ly_do": str|None}}
    """
    with transaction.atomic():
        phieu = PhieuNhap.objects.select_for_update().get(pk=ma_phieu)
        if phieu.trang_thai != PhieuNhap.CHUA_XAC_NHAN:
            raise NghiepVuError("Phiếu đã được xác nhận hoặc đã hủy.")
        if phieu.trang_thai_giao != PhieuNhap.DANG_GIAO:
            raise NghiepVuError("Chỉ đối soát khi phiếu đang ở trạng thái 'Đang giao'.")
        _luu_doi_soat(phieu, dong_doi_soat, ghi_chu, bat_buoc=True)

        for ct in phieu.chi_tiet.select_related("id_sp"):
            sl = ct.so_luong_thuc_nhan
            sp = SanPham.objects.select_for_update().get(pk=ct.id_sp_id)
            # giá vốn bình quân gia quyền
            ton_cu = max(sp.ton_kho, Decimal(0))
            tong = ton_cu + sl
            if tong > 0 and sl > 0:
                sp.gia_von = ((ton_cu * sp.gia_von + sl * ct.don_gia_nhap) / tong).quantize(Decimal(1))
            # HSD: lấy ngày sớm nhất giữa tồn cũ (nếu còn hàng) và lô mới
            if ct.han_su_dung and sl > 0:
                if ton_cu > 0 and sp.han_su_dung:
                    sp.han_su_dung = min(sp.han_su_dung, ct.han_su_dung)
                else:
                    sp.han_su_dung = ct.han_su_dung
            sp.save(update_fields=["gia_von", "han_su_dung", "ngay_cap_nhat"])
            if sl:
                post_stock_move(san_pham_id=sp.pk, loai="NHAP_KHO", user=user, delta=sl, phieu_nhap=phieu)

        phieu.trang_thai_giao = PhieuNhap.DA_GIAO
        phieu.ngay_cap_nhat_giao = timezone.now()
        phieu.trang_thai = PhieuNhap.DA_XAC_NHAN
        phieu.nguoi_xac_nhan = user
        phieu.ngay_xac_nhan = timezone.now()
        phieu.save()
    return phieu


def luu_nhap_doi_soat(ma_phieu, dong_doi_soat, ghi_chu):
    with transaction.atomic():
        phieu = PhieuNhap.objects.select_for_update().get(pk=ma_phieu)
        if phieu.trang_thai != PhieuNhap.CHUA_XAC_NHAN:
            raise NghiepVuError("Phiếu đã được xác nhận hoặc đã hủy.")
        _luu_doi_soat(phieu, dong_doi_soat, ghi_chu, bat_buoc=False)
    return phieu


def _luu_doi_soat(phieu, dong_doi_soat, ghi_chu, bat_buoc):
    loi = []
    for ct in phieu.chi_tiet.select_related("id_sp"):
        d = dong_doi_soat.get(ct.pk, {})
        sl = d.get("sl")
        if sl is None:
            if bat_buoc:
                loi.append(f"{ct.id_sp.ten_sp}: chưa nhập số lượng thực nhận.")
            continue
        if sl < 0:
            loi.append(f"{ct.id_sp.ten_sp}: số lượng thực nhận không được âm.")
            continue
        ly_do = d.get("ly_do") or None
        if sl != ct.so_luong_dat and not ly_do and bat_buoc:
            loi.append(f"{ct.id_sp.ten_sp}: SL thực nhận khác SL đặt — bắt buộc chọn lý do chênh lệch.")
        ct.so_luong_thuc_nhan = sl
        ct.han_su_dung = d.get("hsd")
        ct.ly_do_chenh_lech = ly_do if sl != ct.so_luong_dat else None
        ct.save()
    if loi:
        raise NghiepVuError(" ".join(loi))
    phieu.ghi_chu_doi_soat = ghi_chu
    phieu.save(update_fields=["ghi_chu_doi_soat"])


# ---------------------------------------------------------------- xuất kho
def kiem_tra_dong_xuat(ly_do, dong):
    """dong: list[(SanPham, Decimal)] — kiểm tra tồn khả dụng & HSD theo thời gian thực."""
    loi = []
    if not dong:
        loi.append("Cần chọn ít nhất một sản phẩm.")
    seen = set()
    for sp, sl in dong:
        if sp.pk in seen:
            loi.append(f"{sp.ten_sp} bị chọn trùng.")
        seen.add(sp.pk)
        if sl <= 0:
            loi.append(f"{sp.ten_sp}: số lượng xuất phải lớn hơn 0.")
        elif sl > sp.ton_kho:
            loi.append(f"{sp.ten_sp}: vượt tồn kho khả dụng ({fmt(sp.ton_kho)} {sp.don_vi}).")
        if ly_do == PhieuXuat.BAN_HANG and sp.da_het_han:
            loi.append(f"{sp.ten_sp} đã quá hạn sử dụng — chỉ được xuất với lý do Hủy hàng.")
        if sp.trang_thai != SanPham.DANG_HOAT_DONG and ly_do == PhieuXuat.BAN_HANG:
            loi.append(f"{sp.ten_sp} đang ngừng kinh doanh, không thể xuất bán.")
    if loi:
        raise NghiepVuError(" ".join(loi))


def xac_nhan_phieu_xuat(ma_phieu, user):
    with transaction.atomic():
        phieu = PhieuXuat.objects.select_for_update().get(pk=ma_phieu)
        if phieu.trang_thai != PhieuXuat.CHUA_XAC_NHAN:
            raise NghiepVuError("Phiếu đã được xác nhận hoặc đã hủy.")
        cts = list(phieu.chi_tiet.select_related("id_sp"))
        # khóa dòng & kiểm tra lại tồn tại thời điểm xác nhận
        sps = {s.pk: s for s in SanPham.objects.select_for_update().filter(pk__in=[c.id_sp_id for c in cts])}
        kiem_tra_dong_xuat(phieu.ly_do_xuat, [(sps[c.id_sp_id], c.so_luong_xuat) for c in cts])
        for c in cts:
            post_stock_move(san_pham_id=c.id_sp_id, loai="XUAT_KHO", user=user, delta=-c.so_luong_xuat,
                            phieu_xuat=phieu)
        phieu.trang_thai = PhieuXuat.DA_XAC_NHAN
        phieu.nguoi_xac_nhan = user
        phieu.ngay_xac_nhan = timezone.now()
        phieu.save()
    return phieu


# ---------------------------------------------------------------- kiểm kê
def ghi_dem(phieu: PhieuKiemKe, lan: int, so_lieu: dict, ghi_chu: dict):
    """Lưu kết quả đếm mù. Lần 1: chụp sl_he_thong (ẩn) và gắn cờ chênh lệch. Lần 2: chỉ dòng bị gắn cờ."""
    if phieu.trang_thai != PhieuKiemKe.DANG_KIEM:
        raise NghiepVuError("Phiếu không ở trạng thái đang kiểm.")
    with transaction.atomic():
        for ct in phieu.chi_tiet.select_related("id_sp"):
            if ct.pk not in so_lieu:
                continue
            sl = so_lieu[ct.pk]
            if sl is None or sl < 0:
                raise NghiepVuError(f"{ct.id_sp.ten_sp}: số lượng đếm không hợp lệ.")
            if lan == 1:
                ct.sl_dem_lan_1 = sl
                ct.sl_dem_lan_2 = None
                ct.sl_he_thong = ct.id_sp.ton_kho
                ct.gia_von = ct.id_sp.gia_von
            else:
                if not ct.co_chenh_lech:
                    continue
                ct.sl_dem_lan_2 = sl
            if ct.pk in ghi_chu:
                ct.ghi_chu = ghi_chu[ct.pk][:255]
            ct.sl_chenh_lech = ct.sl_dem_thuc_te - ct.sl_he_thong
            if lan == 1:
                ct.co_chenh_lech = ct.sl_chenh_lech != 0
            ct.save()


def gui_duyet(phieu: PhieuKiemKe):
    if phieu.trang_thai != PhieuKiemKe.DANG_KIEM:
        raise NghiepVuError("Phiếu không ở trạng thái đang kiểm.")
    if not phieu.da_dem_lan_1:
        raise NghiepVuError("Chưa hoàn tất đếm lần 1 cho tất cả sản phẩm.")
    if phieu.can_dem_lan_2:
        raise NghiepVuError("Còn sản phẩm lệch số cần đếm lần 2 trước khi gửi duyệt.")
    phieu.trang_thai = PhieuKiemKe.CHO_DUYET
    phieu.ngay_gui_duyet = timezone.now()
    phieu.save(update_fields=["trang_thai", "ngay_gui_duyet"])


def duyet_kiem_ke(ma_phieu, user):
    """Xác nhận & cân bằng tồn kho: ton_kho = sl_dem_thuc_te, ghi NHAT_KY_KHO."""
    with transaction.atomic():
        phieu = PhieuKiemKe.objects.select_for_update().get(pk=ma_phieu)
        if phieu.trang_thai != PhieuKiemKe.CHO_DUYET:
            raise NghiepVuError("Chỉ duyệt được phiếu đang chờ duyệt.")
        for ct in phieu.chi_tiet.all():
            post_stock_move(san_pham_id=ct.id_sp_id, loai="KIEM_KE", user=user, set_to=ct.sl_dem_thuc_te,
                            phieu_kiem=phieu)
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
        sl_dem_lan_1=None, sl_dem_lan_2=None, sl_he_thong=None, co_chenh_lech=False, sl_chenh_lech=0
    )
    phieu.trang_thai = PhieuKiemKe.DANG_KIEM
    phieu.ngay_gui_duyet = None
    phieu.save(update_fields=["trang_thai", "ngay_gui_duyet"])
