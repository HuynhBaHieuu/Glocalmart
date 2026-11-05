"""Chuyển dữ liệu tồn kho cũ sang quản lý theo LÔ.

Mỗi dòng ChiTietPhieuNhap của phiếu đã xác nhận là 1 lô. Quy tắc bắt buộc:
    tổng so_luong_con_lai các lô của 1 sản phẩm == SanPham.ton_kho

Chia ton_kho hiện tại vào các lô đã có, ưu tiên lô nhập GẦN NHẤT (lô cũ hơn về 0), mỗi lô tối đa bằng
số lượng thực nhận. Nếu tồn kho lớn hơn tổng các lô (do dữ liệu demo gán tồn trực tiếp, kiểm kê thừa…),
phần dư được đưa vào phiếu hệ thống "PN-TONDAU" (Tồn đầu kỳ) để không mất hàng.

Các hàm nhận lớp model làm tham số để dùng được cả trong migration (model lịch sử, apps.get_model)
lẫn trong code thường. Không ghi NHAT_KY_KHO vì tồn kho thực tế không thay đổi.
"""
from datetime import timedelta
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

MA_TON_DAU = "PN-TONDAU"
MA_NCC_NOI_BO = "NCC-NOIBO"
DA_XAC_NHAN = "DA_XAC_NHAN"


def ncc_noi_bo(NhaCungCap):
    """Nhà cung cấp nội bộ cho các phiếu nhập do hệ thống tạo (tồn đầu kỳ, hàng thừa kiểm kê)."""
    ncc, _ = NhaCungCap.objects.get_or_create(
        ma_ncc=MA_NCC_NOI_BO,
        defaults={
            "ten_ncc": "Kho nội bộ – Tồn đầu kỳ",
            "so_dien_thoai": "0000000000",
            "dia_chi": "Kho trung tâm",
            "trang_thai": 0,  # ngừng hoạt động → không xuất hiện khi lập phiếu nhập mới
        },
    )
    return ncc


def _phieu_ton_dau(PhieuNhap, NhaCungCap, NguoiDung):
    phieu = PhieuNhap.objects.filter(pk=MA_TON_DAU).first()
    if phieu:
        return phieu
    ncc = ncc_noi_bo(NhaCungCap)
    nguoi = (NguoiDung.objects.filter(vai_tro="ADMIN").order_by("id_nv").first()
             or NguoiDung.objects.order_by("id_nv").first())
    if nguoi is None:
        raise RuntimeError("Cần ít nhất 1 tài khoản để tạo phiếu Tồn đầu kỳ.")
    # đặt thời điểm trước mọi phiếu nhập: hàng tồn đầu kỳ là hàng cũ nhất (cùng hạn thì xuất trước)
    som_nhat = PhieuNhap.objects.order_by("ngay_tao").values_list("ngay_tao", flat=True).first()
    luc = (som_nhat - timedelta(seconds=1)) if som_nhat else timezone.now()
    return PhieuNhap.objects.create(
        ma_phieu_nhap=MA_TON_DAU,
        id_ncc=ncc,
        nguoi_tao=nguoi,
        ngay_tao=luc,
        trang_thai_giao="DA_GIAO",
        ngay_cap_nhat_giao=luc,
        trang_thai=DA_XAC_NHAN,
        nguoi_xac_nhan=nguoi,
        ngay_xac_nhan=luc,
        ghi_chu="Phiếu hệ thống: phần tồn kho có trước khi quản lý theo lô (không phải hàng nhập mới).",
    )


def phan_bo_lo_ton_kho(SanPham, PhieuNhap, ChiTietPhieuNhap, NhaCungCap, NguoiDung):
    """Gán so_luong_con_lai cho mọi lô sao cho tổng = ton_kho. Trả về dict thống kê."""
    tk = {"san_pham": 0, "lo_co_hang": 0, "ton_dau": []}
    # dòng của phiếu chưa xác nhận / đã hủy không phải là lô
    ChiTietPhieuNhap.objects.exclude(ma_phieu_nhap__trang_thai=DA_XAC_NHAN).update(so_luong_con_lai=0)
    # chạy lại thì tính lại phần Tồn đầu kỳ từ đầu
    ChiTietPhieuNhap.objects.filter(ma_phieu_nhap_id=MA_TON_DAU).delete()

    for sp in SanPham.objects.order_by("pk"):
        tk["san_pham"] += 1
        con = max(sp.ton_kho, Decimal(0))
        lo_list = list(
            ChiTietPhieuNhap.objects.filter(id_sp_id=sp.pk, ma_phieu_nhap__trang_thai=DA_XAC_NHAN)
            .order_by("-ma_phieu_nhap__ngay_xac_nhan", "-ma_phieu_nhap__ngay_tao", "-id_chi_tiet")
        )
        for lo in lo_list:
            lay = min(con, max(lo.so_luong_thuc_nhan or Decimal(0), Decimal(0)))
            if lo.so_luong_con_lai != lay:
                lo.so_luong_con_lai = lay
                lo.save(update_fields=["so_luong_con_lai"])
            if lay > 0:
                tk["lo_co_hang"] += 1
            con -= lay
        if con > 0:
            phieu = _phieu_ton_dau(PhieuNhap, NhaCungCap, NguoiDung)
            ChiTietPhieuNhap.objects.create(
                ma_phieu_nhap=phieu, id_sp_id=sp.pk, so_luong_dat=con, don_gia_nhap=sp.gia_von,
                so_luong_thuc_nhan=con, so_luong_con_lai=con, han_su_dung=sp.han_su_dung,
            )
            tk["lo_co_hang"] += 1
            tk["ton_dau"].append((sp.ma_sp, con))
        # HSD sản phẩm = hạn sớm nhất của các lô còn hàng
        hsd = (ChiTietPhieuNhap.objects.filter(id_sp_id=sp.pk, ma_phieu_nhap__trang_thai=DA_XAC_NHAN,
                                               so_luong_con_lai__gt=0, han_su_dung__isnull=False)
               .order_by("han_su_dung").values_list("han_su_dung", flat=True).first())
        if sp.han_su_dung != hsd:
            SanPham.objects.filter(pk=sp.pk).update(han_su_dung=hsd)

    # không còn sản phẩm nào cần → bỏ phiếu Tồn đầu kỳ rỗng
    if not tk["ton_dau"]:
        PhieuNhap.objects.filter(pk=MA_TON_DAU, chi_tiet__isnull=True).delete()
    return tk


def kiem_tra_tong_lo(SanPham, ChiTietPhieuNhap, san_pham_ids=None):
    """Ràng buộc: tổng so_luong_con_lai các lô == ton_kho. Trả về list (ma_sp, ton_kho, tong_lo) bị lệch."""
    tong = dict(
        ChiTietPhieuNhap.objects.filter(ma_phieu_nhap__trang_thai=DA_XAC_NHAN)
        .values("id_sp_id").annotate(s=Sum("so_luong_con_lai")).values_list("id_sp_id", "s")
    )
    qs = SanPham.objects.order_by("ma_sp")
    if san_pham_ids is not None:
        qs = qs.filter(pk__in=san_pham_ids)
    lech = []
    for sp in qs:
        t = tong.get(sp.pk) or Decimal(0)
        if t != max(sp.ton_kho, Decimal(0)):
            lech.append((sp.ma_sp, sp.ton_kho, t))
    return lech
