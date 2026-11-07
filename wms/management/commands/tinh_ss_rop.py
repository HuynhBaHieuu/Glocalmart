"""Tính tồn kho an toàn (SS) và điểm đặt hàng lại (ROP) cho mọi sản phẩm đang hoạt động — chạy hằng ngày.

    python manage.py tinh_ss_rop
"""
from django.core.management.base import BaseCommand

from wms.services import tinh_ss_rop


class Command(BaseCommand):
    help = "Tính lại SS / ROP cho các sản phẩm đang hoạt động và lưu vào bảng sản phẩm."

    def handle(self, *args, **kw):
        tk = tinh_ss_rop()
        self.stdout.write(self.style.SUCCESS(
            f"Đã tính SS/ROP cho {tk['tong']} sản phẩm: {tk['du_du_lieu']} đủ dữ liệu, "
            f"{tk['chua_du']} chưa đủ dữ liệu (ROP = ngưỡng tối thiểu)."
        ))
