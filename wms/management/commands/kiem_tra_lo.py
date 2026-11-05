"""Kiểm tra ràng buộc lô: tổng so_luong_con_lai các lô = ton_kho.

    python manage.py kiem_tra_lo              # chỉ báo cáo, không sửa gì
    python manage.py kiem_tra_lo --phan-bo-lai  # chia lại toàn bộ tồn kho vào lô (giống migration 0003)

Chỉ dùng --phan-bo-lai khi CHƯA bật xuất kho theo FEFO; sau đó việc chia lại sẽ làm mất thông tin đã trừ theo lô.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from wms import lo
from wms.models import ChiTietPhieuNhap, NguoiDung, NhaCungCap, PhieuNhap, SanPham


class Command(BaseCommand):
    help = "Kiểm tra (và tùy chọn chia lại) tồn kho theo lô."

    def add_arguments(self, parser):
        parser.add_argument("--phan-bo-lai", action="store_true", help="Chia lại ton_kho vào các lô")

    def handle(self, *args, phan_bo_lai=False, **kw):
        if phan_bo_lai:
            with transaction.atomic():
                tk = lo.phan_bo_lo_ton_kho(SanPham, PhieuNhap, ChiTietPhieuNhap, NhaCungCap, NguoiDung)
            self.stdout.write(f"Đã chia lại: {tk['lo_co_hang']} lô còn hàng; phần dư vào {lo.MA_TON_DAU}: {tk['ton_dau']}")
        lech = lo.kiem_tra_tong_lo(SanPham, ChiTietPhieuNhap)
        if not lech:
            self.stdout.write(self.style.SUCCESS("OK: tổng các lô khớp tồn kho cho mọi sản phẩm."))
            return
        self.stdout.write(self.style.ERROR(f"{len(lech)} sản phẩm lệch (mã SP, tồn kho, tổng lô):"))
        for row in lech:
            self.stdout.write(f"  {row[0]}: {row[1]} ≠ {row[2]}")
