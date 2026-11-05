"""Tạo dữ liệu demo cho G'Local Mart & Cafe.

    python manage.py seed_demo            # chỉ chạy khi DB trống
    python manage.py seed_demo --reset    # xóa toàn bộ dữ liệu nghiệp vụ rồi tạo lại

Mọi biến động tồn kho đều đi qua các hàm nghiệp vụ (post_stock_move) nên nhật ký kho, báo cáo N-X-T
và tồn kho hiện tại luôn khớp nhau.
"""
import random
from datetime import timedelta
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from wms.api_auth import tao_api_key
from wms.models import (
    ApiKey, AuditLog, ChiTietPhieuKiemKe, ChiTietPhieuNhap, ChiTietPhieuXuat, DanhMuc, DocSequence, NguoiDung,
    NhaCungCap, NhatKyKho, PhieuKiemKe, PhieuNhap, PhieuXuat, SanPham,
)
from wms.services import (
    chuyen_trang_thai_giao, duyet_kiem_ke, ghi_dem, gui_duyet, next_doc_code, tu_choi_kiem_ke, xac_nhan_phieu_nhap,
    xac_nhan_phieu_xuat,
)

D = Decimal

USERS = [
    ("AD001", "admin", "Nguyễn Minh Anh", "ADMIN", "admin@glocal.vn"),
    ("NV002", "nvkho_002", "Trần Thị Bích", "NHAN_VIEN", "nvkho2@glocal.vn"),
    ("NV003", "nvkho_003", "Lê Quang Duy", "NHAN_VIEN", "nvkho3@glocal.vn"),
    ("NV004", "nvkho_004", "Phạm Thị Hồng", "NHAN_VIEN", "nvkho4@glocal.vn"),
    ("NV005", "nvkho_005", "Nguyễn Bảo Trân", "NHAN_VIEN", "nvkho5@glocal.vn"),
    ("AD002", "quanly", "Hoàng Văn Giang", "ADMIN", "quanly@glocal.vn"),
]

CATS = [  # (mã, tên, cha, mô tả)
    ("DM001", "Đồ uống", None, "Nước giải khát, sữa, đồ uống đóng chai"),
    ("DM002", "Nước giải khát", "DM001", "Nước ngọt có ga, nước khoáng, trà đóng chai"),
    ("DM003", "Sữa & chế phẩm từ sữa", "DM001", "Sữa tươi, sữa chua, sữa đặc"),
    ("DM004", "Thực phẩm khô", None, "Mì gói, gia vị, dầu ăn"),
    ("DM005", "Mì - Phở ăn liền", "DM004", "Mì gói, phở gói, cháo ăn liền"),
    ("DM006", "Gia vị & Dầu ăn", "DM004", "Nước mắm, dầu ăn, hạt nêm"),
    ("DM007", "Bánh kẹo & Snack", None, "Bánh quy, snack khoai tây, kẹo"),
    ("DM008", "Nguyên liệu Cafe", None, "Cà phê hạt, syrup, kem béo cho quầy cafe"),
    ("DM009", "Hóa mỹ phẩm", None, "Nước rửa chén, dầu gội, kem đánh răng"),
    ("DM010", "Văn phòng phẩm", None, "Giấy, bút cho văn phòng cửa hàng"),
]

NCCS = [
    ("NCC-0001", "Công ty CP Sữa Việt Nam (Vinamilk)", "028 5415 5555", "sales@vinamilk.com.vn", "10 Tân Trào, Q.7, TP. Hồ Chí Minh", 1),
    ("NCC-0002", "Công ty CP Hàng tiêu dùng Masan", "028 6256 3862", "contact@masan.com", "Tầng 12, MPlaza, Q.1, TP. Hồ Chí Minh", 1),
    ("NCC-0003", "Công ty CP Acecook Việt Nam", "028 3815 4064", "info@acecookvietnam.com", "Lô II-3 KCN Tân Bình, TP. Hồ Chí Minh", 1),
    ("NCC-0004", "Coca-Cola Beverages Việt Nam", "028 3896 1000", "order@coca-cola.vn", "485 Xa lộ Hà Nội, TP. Thủ Đức", 1),
    ("NCC-0005", "Tập đoàn Trung Nguyên Legend", "0262 3854 333", "b2b@trungnguyen.com.vn", "82-84 Bùi Thị Xuân, Q.1, TP. Hồ Chí Minh", 1),
    ("NCC-0006", "Công ty TNHH Thương Nhất", "024 3812 3456", "kinhdoanh@thuongnhat.vn", "25 Láng Hạ, Đống Đa, Hà Nội", 1),
    ("NCC-0007", "Công ty TNHH Thương mại Minh Đức", "0225 3859 288", "lienhe@minhducmt.vn", "12 Lạch Tray, Hải Phòng", 0),
]

# (mã, tên, mô tả, danh mục, ĐVT, giá vốn nhập, giá bán, ngưỡng, NCC, SL nhập đầu, HSD sau n ngày kể từ lô đầu)
PRODUCTS = [
    ("SP-0001", "Sữa tươi Vinamilk 100% không đường 1L", "Hộp giấy 1L", "DM003", "Hộp", 28000, 35000, 30, "NCC-0001", 160, 120),
    ("SP-0002", "Sữa chua Vinamilk có đường", "Lốc 4 hộp 100g", "DM003", "Lốc", 22000, 28000, 20, "NCC-0001", 90, 72),
    ("SP-0003", "Sữa đặc Ông Thọ đỏ 380g", "Lon 380g", "DM003", "Lon", 21000, 27000, 25, "NCC-0001", 120, 300),
    ("SP-0004", "Coca-Cola lon 320ml", "Thùng 24 lon", "DM002", "Lon", 7500, 10000, 48, "NCC-0004", 480, 270),
    ("SP-0005", "Sprite lon 320ml", "Lon 320ml", "DM002", "Lon", 7500, 10000, 48, "NCC-0004", 240, 270),
    ("SP-0006", "Fanta cam lon 320ml", "Lon 320ml", "DM002", "Lon", 7500, 10000, 36, "NCC-0004", 120, 270),
    ("SP-0007", "Nước khoáng Dasani 500ml", "Chai PET 500ml", "DM002", "Chai", 4000, 6000, 60, "NCC-0004", 360, 365),
    ("SP-0008", "Trà xanh Không Độ 455ml", "Chai 455ml", "DM002", "Chai", 7000, 10000, 40, "NCC-0006", 200, 66),
    ("SP-0009", "Mì Hảo Hảo tôm chua cay", "Gói 75g", "DM005", "Gói", 3500, 5000, 100, "NCC-0003", 600, 160),
    ("SP-0010", "Phở Đệ Nhất bò", "Gói 65g", "DM005", "Gói", 6500, 9000, 40, "NCC-0003", 160, 180),
    ("SP-0011", "Mì Omachi xốt bò hầm", "Gói 80g", "DM005", "Gói", 7000, 9500, 50, "NCC-0002", 200, 150),
    ("SP-0012", "Cháo Gấu Đỏ thịt bằm", "Gói 50g", "DM005", "Gói", 3800, 5500, 40, "NCC-0003", 120, 75),
    ("SP-0013", "Nước mắm Nam Ngư 500ml", "Chai 500ml", "DM006", "Chai", 32000, 41000, 15, "NCC-0002", 60, 540),
    ("SP-0014", "Dầu ăn Tường An Cooking oil 1L", "Chai 1L", "DM006", "Chai", 45000, 56000, 15, "NCC-0006", 70, 400),
    ("SP-0015", "Hạt nêm Knorr thịt thăn 400g", "Gói 400g", "DM006", "Gói", 38000, 47000, 12, "NCC-0006", 50, 365),
    ("SP-0016", "Tương ớt Chin-su 250g", "Chai 250g", "DM006", "Chai", 12000, 16000, 20, "NCC-0002", 80, 200),
    ("SP-0017", "Bánh quy Cosy Marie 432g", "Hộp 432g", "DM007", "Hộp", 39000, 49000, 10, "NCC-0006", 40, 240),
    ("SP-0018", "Snack khoai tây Lay's 95g", "Gói 95g", "DM007", "Gói", 17000, 23000, 25, "NCC-0006", 100, 58),
    ("SP-0019", "Kẹo bạc hà Mentos cuộn", "Cuộn 37g", "DM007", "Cuộn", 8000, 12000, 30, "NCC-0006", 120, 365),
    ("SP-0020", "Bánh Chocopie Orion hộp 12", "Hộp 396g", "DM007", "Hộp", 52000, 65000, 10, "NCC-0006", 45, 63),
    ("SP-0021", "Cà phê hạt Trung Nguyên S-Gold 500g", "Túi 500g · Robusta & Arabica", "DM008", "Túi", 145000, 185000, 8, "NCC-0005", 40, 365),
    ("SP-0022", "Cà phê G7 3in1 hộp 21 gói", "Hộp 336g", "DM008", "Hộp", 48000, 59000, 15, "NCC-0005", 60, 360),
    ("SP-0023", "Syrup Monin Caramel 700ml", "Chai thủy tinh 700ml", "DM008", "Chai", 185000, 230000, 4, "NCC-0006", 14, 540),
    ("SP-0024", "Sữa đặc Ngôi Sao Phương Nam 1.284kg", "Hộp 1.284kg cho pha chế", "DM008", "Hộp", 58000, 72000, 10, "NCC-0001", 36, 90),
    ("SP-0025", "Kem béo thực vật Rich's 907g", "Hộp 907g", "DM008", "Hộp", 62000, 79000, 6, "NCC-0006", 20, 79),
    ("SP-0026", "Nước rửa chén Sunlight chanh 750g", "Chai 750g", "DM009", "Chai", 26000, 33000, 12, "NCC-0002", 48, 720),
    ("SP-0027", "Kem đánh răng P/S bảo vệ 123 230g", "Tuýp 230g", "DM009", "Tuýp", 28000, 36000, 12, "NCC-0006", 40, 720),
    ("SP-0028", "Dầu gội Clear mát lạnh 630g", "Chai 630g", "DM009", "Chai", 125000, 155000, 6, "NCC-0006", 24, 720),
    ("SP-0029", "Giấy in A4 Double A 80gsm", "Ram 500 tờ", "DM010", "Ram", 72000, 85000, 5, "NCC-0006", 20, None),
    ("SP-0030", "Bút bi Thiên Long TL-027", "Hộp 20 cây · mực xanh", "DM010", "Hộp", 42000, 52000, 3, "NCC-0006", 10, None),
]


class Command(BaseCommand):
    help = "Tạo dữ liệu demo (tài khoản, danh mục, sản phẩm, NCC, phiếu nhập/xuất/kiểm kê)."

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Xóa dữ liệu cũ trước khi tạo")

    def handle(self, *args, reset=False, **kw):
        if NguoiDung.objects.exists() and not reset:
            self.stdout.write(self.style.WARNING("DB đã có dữ liệu. Dùng --reset để tạo lại."))
            return
        rnd = random.Random(2026)
        now = timezone.now()
        with transaction.atomic():
            if reset:
                for m in (NhatKyKho, ChiTietPhieuKiemKe, PhieuKiemKe, ChiTietPhieuXuat, PhieuXuat, ChiTietPhieuNhap,
                          PhieuNhap, SanPham, NhaCungCap, AuditLog, ApiKey, DocSequence, NguoiDung):
                    m.objects.all().delete()
                DanhMuc.objects.filter(id_dmcha__isnull=False).delete()
                DanhMuc.objects.all().delete()

            users = {}
            for ma, un, ten, vt, email in USERS:
                pw = "Admin@123" if vt == "ADMIN" else "Nhanvien@123"
                users[un] = NguoiDung.objects.create_user(un, pw, ma_nv=ma, ho_ten=ten, vai_tro=vt, email=email)
            locked = NguoiDung.objects.create_user("nvkho_006", "Nhanvien@123", ma_nv="NV006", ho_ten="Đỗ Văn Khánh",
                                                   vai_tro="NHAN_VIEN", email="nvkho6@glocal.vn")
            locked.is_locked, locked.so_lan_sai = True, 5
            locked.save()
            admin, staff = users["admin"], [users[k] for k in ("nvkho_002", "nvkho_003", "nvkho_004", "nvkho_005")]

            cats = {}
            for ma, ten, cha, mo_ta in CATS:
                cats[ma] = DanhMuc.objects.create(ma_danhmuc=ma, ten_danhmuc=ten, id_dmcha=cats.get(cha), mo_ta=mo_ta)
            nccs = {ma: NhaCungCap.objects.create(ma_ncc=ma, ten_ncc=t, so_dien_thoai=sdt, email=e, dia_chi=dc, trang_thai=tt)
                    for ma, t, sdt, e, dc, tt in NCCS}
            sps, meta = {}, {}
            for ma, ten, mo_ta, dm, dvt, von, ban, nguong, ncc, sl0, hsd in PRODUCTS:
                sps[ma] = SanPham.objects.create(ma_sp=ma, ten_sp=ten, mo_ta=mo_ta, id_danhmuc=cats[dm], don_vi=dvt,
                                                 gia_ban=ban, nguong_toi_thieu=nguong)
                meta[ma] = dict(von=von, ncc=ncc, sl0=sl0, hsd=hsd)

            def at(days, hour=9):
                return (now - timedelta(days=days)).replace(hour=hour, minute=rnd.randint(0, 59), second=0, microsecond=0)

            def backdate(phieu, when, field):
                NhatKyKho.objects.filter(**{field: phieu}).update(ngay_tao=when)

            def nhap(days, ncc_ma, lines, user, *, confirm=True, giao=True, ghi_chu=None, diff=None):
                """lines: [(ma_sp, sl, gia, hsd_days|None)]"""
                t = at(days, 8)
                p = PhieuNhap.objects.create(ma_phieu_nhap=next_doc_code("PN", t), id_ncc=nccs[ncc_ma], nguoi_tao=user,
                                             ngay_tao=t, ngay_du_kien_nhan=(t + timedelta(days=2)).date(), ghi_chu=ghi_chu)
                cts = [ChiTietPhieuNhap.objects.create(ma_phieu_nhap=p, id_sp=sps[m], so_luong_dat=sl, don_gia_nhap=g)
                       for m, sl, g, _ in lines]
                AuditLog.objects.create(nguoi_dung=user, hanh_dong="TAO_PHIEU", doi_tuong="phieu_nhap", ma_doi_tuong=p.pk,
                                        chi_tiet=f"{len(lines)} sản phẩm — Chờ giao", ngay_tao=t)
                if giao:
                    chuyen_trang_thai_giao(p, PhieuNhap.DANG_GIAO, user)
                    AuditLog.objects.create(nguoi_dung=user, hanh_dong="CAP_NHAT_GIAO", doi_tuong="phieu_nhap",
                                            ma_doi_tuong=p.pk, chi_tiet="→ Đang giao", ngay_tao=t + timedelta(hours=1))
                if confirm:
                    dong = {}
                    for ct, (m, sl, g, hsd) in zip(cts, lines):
                        thuc, ly_do = sl, None
                        if diff and m in diff:
                            thuc, ly_do = sl + diff[m][0], diff[m][1]
                        dong[ct.pk] = {"sl": D(thuc), "ly_do": ly_do,
                                       "hsd": (t + timedelta(days=hsd)).date() if hsd is not None else None}
                    # dữ liệu mô phỏng quá khứ: lúc nhận hàng, lô chưa cận hạn như tính theo hôm nay
                    xac_nhan_phieu_nhap(p.pk, dong, user, "Hàng giao đủ, bao bì nguyên vẹn." if not diff else
                                        "Có chênh lệch khi kiểm đếm, đã ghi nhận lý do.",
                                        ly_do_can_han="Hạn còn dài tại thời điểm nhận hàng (dữ liệu demo)")
                    ChiTietPhieuNhap.objects.filter(ma_phieu_nhap=p).update(ghi_chu_doi_soat=None)
                    t2 = t + timedelta(hours=2)
                    PhieuNhap.objects.filter(pk=p.pk).update(ngay_xac_nhan=t2, ngay_cap_nhat_giao=t2)
                    backdate(p, t2, "ma_phieu_nhap")
                    AuditLog.objects.create(nguoi_dung=user, hanh_dong="XAC_NHAN", doi_tuong="phieu_nhap",
                                            ma_doi_tuong=p.pk, chi_tiet="Đã giao & tự động cập nhật tồn kho", ngay_tao=t2)
                return p

            def xuat(days, ly_do, lines, user, *, confirm=True, ghi_chu=None):
                t = at(days, 15)
                p = PhieuXuat.objects.create(ma_phieu_xuat=next_doc_code("PX", t), nguoi_tao=user, ngay_tao=t,
                                             ly_do_xuat=ly_do, ghi_chu=ghi_chu)
                for m, sl in lines:
                    ChiTietPhieuXuat.objects.create(ma_phieu_xuat=p, id_sp=sps[m], so_luong_xuat=sl)
                AuditLog.objects.create(nguoi_dung=user, hanh_dong="TAO_PHIEU", doi_tuong="phieu_xuat", ma_doi_tuong=p.pk,
                                        chi_tiet=f"{p.get_ly_do_xuat_display()} — {len(lines)} sản phẩm", ngay_tao=t)
                if confirm:
                    xac_nhan_phieu_xuat(p.pk, user)
                    t2 = t + timedelta(minutes=40)
                    PhieuXuat.objects.filter(pk=p.pk).update(ngay_xac_nhan=t2)
                    backdate(p, t2, "ma_phieu_xuat")
                    AuditLog.objects.create(nguoi_dung=user, hanh_dong="XAC_NHAN", doi_tuong="phieu_xuat",
                                            ma_doi_tuong=p.pk, chi_tiet="Đã trừ tồn kho", ngay_tao=t2)
                return p

            # Các sự kiện được thực thi theo đúng thứ tự thời gian để nhật ký kho (sl_truoc/sl_sau) liên tục.
            events = []

            def ev(day, hour, fn):
                events.append((-day, hour, len(events), fn))

            # ---- 1. Nhập đầu kỳ (~75 ngày trước), gom theo nhà cung cấp
            by_ncc = {}
            for ma, m in meta.items():
                by_ncc.setdefault(m["ncc"], []).append((ma, m["sl0"], m["von"], m["hsd"]))
            for i, (ncc_ma, lines) in enumerate(sorted(by_ncc.items())):
                ev(75 - i, 8, lambda d=75 - i, n=ncc_ma, ln=lines: nhap(d, n, ln, admin,
                                                                       ghi_chu="Nhập hàng đầu kỳ khai trương hệ thống"))

            # ---- 2. Bán hàng hằng ngày (xuất) & nhập bổ sung định kỳ
            ban_chay = ["SP-0004", "SP-0005", "SP-0007", "SP-0009", "SP-0001", "SP-0011", "SP-0010", "SP-0018",
                        "SP-0019", "SP-0003", "SP-0012", "SP-0016", "SP-0022", "SP-0008", "SP-0002"]

            def ban_le(day):
                lines = []
                for m in rnd.sample(ban_chay, rnd.randint(3, 5)):
                    sps[m].refresh_from_db()
                    nhieu = sps[m].don_vi in ("Lon", "Gói", "Chai")
                    sl = min(int(sps[m].ton_con_han), rnd.randint(8, 40) if nhieu else rnd.randint(3, 12))
                    if sl > 0:
                        lines.append((m, sl))
                if lines:
                    xuat(day, PhieuXuat.BAN_HANG, lines, rnd.choice(staff), ghi_chu="Xuất bán tại quầy mart")

            for day in range(66, 1, -3):
                ev(day, 15, lambda d=day: ban_le(d))
            for day in (48, 27):
                ev(day, 16, lambda d=day: xuat(d, PhieuXuat.BAN_HANG, [("SP-0021", 4), ("SP-0024", 5), ("SP-0023", 2)],
                                                rnd.choice(staff), ghi_chu="Xuất nguyên liệu cho quầy cafe"))

            ev(45, 8, lambda: nhap(45, "NCC-0004", [("SP-0004", 240, 7400, 270), ("SP-0005", 96, 7400, 270),
                                                    ("SP-0007", 120, 3900, 365)],
                                   staff[0], ghi_chu="Bổ sung nước giải khát mùa nóng"))
            ev(30, 8, lambda: nhap(30, "NCC-0003", [("SP-0009", 300, 3450, 150), ("SP-0010", 80, 6400, 180),
                                                    ("SP-0012", 60, 3800, 120)],
                                   staff[1], diff={"SP-0009": (-12, "HU_HONG")}))
            ev(18, 8, lambda: nhap(18, "NCC-0001", [("SP-0001", 100, 27500, 25), ("SP-0002", 60, 21500, 20),
                                                    ("SP-0024", 24, 57500, 80)],
                                   staff[2], diff={"SP-0001": (-7, "THIEU_HANG")}, ghi_chu="Giao 2 đợt trong ngày"))
            ev(9, 8, lambda: nhap(9, "NCC-0005", [("SP-0021", 20, 148000, 365), ("SP-0022", 30, 47500, 360)], staff[0]))

            # ---- 3. Tạo các tình huống cảnh báo
            def ban_het(day, m, giu=0):
                sps[m].refresh_from_db()
                if sps[m].ton_kho > giu:
                    ly = PhieuXuat.HUY_HANG if sps[m].ton_con_han < sps[m].ton_kho - giu else PhieuXuat.BAN_HANG
                    xuat(day, ly, [(m, sps[m].ton_kho - giu)], rnd.choice(staff),
                         ghi_chu="Hủy hàng hết hạn" if ly == PhieuXuat.HUY_HANG else "Bán sỉ cho khách đoàn")

            for m in ("SP-0006", "SP-0020", "SP-0025"):  # bán hết → Đã hết hàng
                d = rnd.randint(3, 6)
                ev(d, 16, lambda d=d, m=m: ban_het(d, m))
            for m, giu in (("SP-0013", 9), ("SP-0017", 6), ("SP-0028", 4), ("SP-0030", 2), ("SP-0014", 11)):
                d = rnd.randint(2, 7)
                ev(d, 16, lambda d=d, m=m, g=giu: ban_het(d, m, g))

            def huy_tra_xanh():
                sps["SP-0008"].refresh_from_db()
                xuat(4, PhieuXuat.HUY_HANG, [("SP-0008", min(D(12), sps["SP-0008"].ton_kho))], admin,
                     ghi_chu="Hủy lô trà xanh hết hạn, móp méo")

            ev(4, 11, huy_tra_xanh)
            ev(6, 11, lambda: xuat(6, PhieuXuat.DIEU_CHINH, [("SP-0029", 3)], staff[3], ghi_chu="Xuất dùng nội bộ văn phòng"))

            # ---- 4. Kiểm kê
            def kiem(days, user, dem, *, lan2=None, gui=True, duyet=None, tu_choi=None):
                t = at(days, 17)
                p = PhieuKiemKe.objects.create(ma_phieu_kiem=next_doc_code("KK", t), nguoi_tao=user, ngay_tao=t)
                for m in dem:
                    ChiTietPhieuKiemKe.objects.create(ma_phieu_kiem=p, id_sp=sps[m], don_vi=sps[m].don_vi)
                cts = {ct.id_sp.ma_sp: ct for ct in p.chi_tiet.select_related("id_sp")}
                for m in dem:
                    sps[m].refresh_from_db()
                ghi_dem(p, 1, {cts[m].pk: sps[m].ton_kho + D(d) for m, d in dem.items()},
                        {cts[m].pk: "Rách bao bì 2 gói" for m, d in dem.items() if d < 0})
                AuditLog.objects.create(nguoi_dung=user, hanh_dong="TAO_PHIEU", doi_tuong="phieu_kiem_ke",
                                        ma_doi_tuong=p.pk, chi_tiet=f"Đếm lần 1: {len(dem)} sản phẩm", ngay_tao=t)
                if lan2 is not None:
                    p.refresh_from_db()
                    ghi_dem(p, 2, {cts[m].pk: sps[m].ton_kho + D(d) for m, d in lan2.items()}, {})
                    AuditLog.objects.create(nguoi_dung=user, hanh_dong="DEM_LAN_2", doi_tuong="phieu_kiem_ke",
                                            ma_doi_tuong=p.pk, ngay_tao=t + timedelta(minutes=30))
                if gui:
                    p.refresh_from_db()
                    gui_duyet(p, {ct.pk: ct.id_sp.han_su_dung for ct in p.chi_tiet.select_related("id_sp")
                                  if ct.sl_thua > 0})
                    PhieuKiemKe.objects.filter(pk=p.pk).update(ngay_gui_duyet=t + timedelta(minutes=45))
                    AuditLog.objects.create(nguoi_dung=user, hanh_dong="GUI_DUYET", doi_tuong="phieu_kiem_ke",
                                            ma_doi_tuong=p.pk, ngay_tao=t + timedelta(minutes=45))
                if duyet:
                    duyet_kiem_ke(p.pk, duyet)
                    t2 = t + timedelta(hours=1)
                    PhieuKiemKe.objects.filter(pk=p.pk).update(ngay_duyet=t2)
                    backdate(p, t2, "ma_phieu_kiem")
                    AuditLog.objects.create(nguoi_dung=duyet, hanh_dong="DUYET", doi_tuong="phieu_kiem_ke",
                                            ma_doi_tuong=p.pk, chi_tiet="Cân bằng tồn kho", ngay_tao=t2)
                if tu_choi:
                    p.refresh_from_db()
                    tu_choi_kiem_ke(p, tu_choi, "Số đếm Mì Hảo Hảo chênh lệch bất thường, yêu cầu đếm lại toàn bộ kệ.")
                    AuditLog.objects.create(nguoi_dung=tu_choi, hanh_dong="TU_CHOI", doi_tuong="phieu_kiem_ke",
                                            ma_doi_tuong=p.pk, chi_tiet=p.ly_do_tu_choi, ngay_tao=t + timedelta(hours=1))
                return p

            ev(20, 17, lambda: kiem(20, staff[1], {"SP-0009": -6, "SP-0010": 0, "SP-0011": -2},
                                    lan2={"SP-0009": -5, "SP-0011": -2}, duyet=admin))
            ev(12, 17, lambda: kiem(12, staff[2], {"SP-0004": 0, "SP-0005": -3, "SP-0007": 0}, lan2={"SP-0005": -2},
                                    duyet=admin))
            ev(8, 17, lambda: kiem(8, staff[3], {"SP-0009": -40, "SP-0012": 0}, lan2={"SP-0009": -38}, tu_choi=admin))
            ev(2, 17, lambda: kiem(2, staff[0], {"SP-0001": -2, "SP-0002": 0, "SP-0003": 1},
                                   lan2={"SP-0001": -2, "SP-0003": 1}))
            ev(1, 17, lambda: kiem(1, staff[1], {"SP-0016": 0, "SP-0019": -4, "SP-0018": 0}, gui=False))  # chờ đếm lần 2

            for _, _, _, fn in sorted(events, key=lambda e: e[:3]):
                fn()

            # ---- 5. Chứng từ đang xử lý (để demo luồng)
            nhap(3, "NCC-0004", [("SP-0006", 120, 7400, 270), ("SP-0004", 96, 7400, 270)], staff[0], confirm=False,
                 ghi_chu="Hàng được vận chuyển bằng xe tải, liên hệ anh Minh (0901234567) khi giao.")
            nhap(2, "NCC-0006", [("SP-0020", 30, 51000, 180), ("SP-0025", 24, 61500, 120), ("SP-0017", 24, 38500, 240)],
                 staff[1], confirm=False)
            nhap(1, "NCC-0002", [("SP-0013", 48, 31500, 540), ("SP-0016", 60, 11800, 200)], admin, confirm=False, giao=False)
            nhap(0, "NCC-0001", [("SP-0001", 120, 27500, 25), ("SP-0003", 48, 20800, 300)], staff[2], confirm=False,
                 giao=False, ghi_chu="Đơn đặt hàng định kỳ tuần")
            huy = nhap(5, "NCC-0006", [("SP-0029", 10, 72000, None)], staff[3], confirm=False, giao=False)
            PhieuNhap.objects.filter(pk=huy.pk).update(trang_thai=PhieuNhap.DA_HUY, ly_do_huy="NCC báo hết hàng, đặt lại sau")
            xuat(0, PhieuXuat.BAN_HANG, [("SP-0009", 24), ("SP-0004", 24)], staff[0], confirm=False,
                 ghi_chu="Đơn hàng online #DH-1023")
            xuat(0, PhieuXuat.HUY_HANG, [("SP-0018", 6)], staff[2], confirm=False, ghi_chu="Hủy snack quá hạn sử dụng")

            raw = tao_api_key("Ứng dụng POS quầy cafe (demo)", admin)

            # mọi nghiệp vụ đã trừ / cộng theo lô (FEFO) → tổng lô phải khớp tồn kho
            from wms.services import kiem_tra_tong_lo
            lech = kiem_tra_tong_lo()
            if lech:
                raise RuntimeError(f"Tổng lô lệch tồn kho: {lech[:5]}")

        sp_count = SanPham.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f"Đã tạo dữ liệu demo: {NguoiDung.objects.count()} tài khoản, {sp_count} sản phẩm, "
            f"{PhieuNhap.objects.count()} phiếu nhập, {PhieuXuat.objects.count()} phiếu xuất, "
            f"{PhieuKiemKe.objects.count()} phiếu kiểm kê, {NhatKyKho.objects.count()} bút toán kho."
        ))
        self.stdout.write("Đăng nhập: admin / Admin@123  ·  nvkho_002 / Nhanvien@123")
        self.stdout.write(f"API Key demo: {raw}")
