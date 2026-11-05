"""Dữ liệu cũ: chia ton_kho hiện tại vào các lô (ưu tiên lô nhập gần nhất), phần dư → phiếu PN-TONDAU."""
from django.db import migrations

from wms.lo import MA_NCC_NOI_BO, MA_TON_DAU, kiem_tra_tong_lo, phan_bo_lo_ton_kho


def forward(apps, schema_editor):
    m = {n: apps.get_model("wms", n) for n in ("SanPham", "PhieuNhap", "ChiTietPhieuNhap", "NhaCungCap", "NguoiDung")}
    phan_bo_lo_ton_kho(m["SanPham"], m["PhieuNhap"], m["ChiTietPhieuNhap"], m["NhaCungCap"], m["NguoiDung"])
    lech = kiem_tra_tong_lo(m["SanPham"], m["ChiTietPhieuNhap"])
    if lech:
        raise RuntimeError(f"Phân bổ lô sai cho {len(lech)} sản phẩm: {lech[:5]}")
    # Kết quả xem bằng: python manage.py kiem_tra_lo


def backward(apps, schema_editor):
    PhieuNhap = apps.get_model("wms", "PhieuNhap")
    NhaCungCap = apps.get_model("wms", "NhaCungCap")
    PhieuNhap.objects.filter(pk=MA_TON_DAU).delete()  # chi tiết xóa theo CASCADE
    NhaCungCap.objects.filter(ma_ncc=MA_NCC_NOI_BO, phieu_nhap__isnull=True).delete()


class Migration(migrations.Migration):
    dependencies = [("wms", "0002_lo_so_luong_con_lai")]
    operations = [migrations.RunPython(forward, backward)]
