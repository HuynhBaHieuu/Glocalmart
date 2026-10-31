"""Kiểm thử các quy tắc nghiệp vụ trong đặc tả.  Chạy: python manage.py test wms"""
from datetime import timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.utils import timezone

from .api_auth import tao_api_key
from .models import (
    ChiTietPhieuKiemKe, ChiTietPhieuNhap, ChiTietPhieuXuat, DanhMuc, NguoiDung, NhaCungCap, NhatKyKho, PhieuKiemKe,
    PhieuNhap, PhieuXuat, SanPham,
)
from .services import (
    NghiepVuError, chuyen_trang_thai_giao, duyet_kiem_ke, ghi_dem, gui_duyet, next_doc_code, xac_nhan_phieu_nhap,
    xac_nhan_phieu_xuat,
)


class Base(TestCase):
    def setUp(self):
        self.admin = NguoiDung.objects.create_user("admin", "Admin@123", ma_nv="AD001", ho_ten="Admin", vai_tro="ADMIN",
                                                   email="a@x.vn")
        self.nv = NguoiDung.objects.create_user("nv", "Nhanvien@123", ma_nv="NV001", ho_ten="Nhân viên", email="n@x.vn")
        self.dm = DanhMuc.objects.create(ma_danhmuc="DM1", ten_danhmuc="Sữa")
        self.ncc = NhaCungCap.objects.create(ma_ncc="N1", ten_ncc="Vinamilk", so_dien_thoai="0281234567", dia_chi="HCM")
        self.sp = SanPham.objects.create(ma_sp="SP1", ten_sp="Sữa tươi", id_danhmuc=self.dm, don_vi="Hộp",
                                         gia_ban=30000, nguong_toi_thieu=10)

    def nhap(self, sl, gia, hsd=None, thuc=None, ly_do=None):
        p = PhieuNhap.objects.create(ma_phieu_nhap=next_doc_code("PN"), id_ncc=self.ncc, nguoi_tao=self.nv)
        ct = ChiTietPhieuNhap.objects.create(ma_phieu_nhap=p, id_sp=self.sp, so_luong_dat=sl, don_gia_nhap=gia)
        chuyen_trang_thai_giao(p, PhieuNhap.DANG_GIAO, self.nv)
        xac_nhan_phieu_nhap(p.pk, {ct.pk: {"sl": D(thuc if thuc is not None else sl), "hsd": hsd, "ly_do": ly_do}},
                            self.nv)
        self.sp.refresh_from_db()
        return p

    def xuat(self, sl, ly_do=PhieuXuat.BAN_HANG):
        p = PhieuXuat.objects.create(ma_phieu_xuat=next_doc_code("PX"), nguoi_tao=self.nv, ly_do_xuat=ly_do)
        ChiTietPhieuXuat.objects.create(ma_phieu_xuat=p, id_sp=self.sp, so_luong_xuat=sl)
        return p


class DocSequenceTest(Base):
    def test_ma_chung_tu_tang_dan(self):
        ky = timezone.localtime().strftime("%y%m")
        self.assertEqual(next_doc_code("PN"), f"PN-{ky}-0001")
        self.assertEqual(next_doc_code("PN"), f"PN-{ky}-0002")
        self.assertEqual(next_doc_code("PX"), f"PX-{ky}-0001")


class NhapKhoTest(Base):
    def test_khong_nhay_coc_trang_thai(self):
        p = PhieuNhap.objects.create(ma_phieu_nhap="PN-T", id_ncc=self.ncc, nguoi_tao=self.nv)
        with self.assertRaises(NghiepVuError):
            chuyen_trang_thai_giao(p, PhieuNhap.DA_GIAO, self.nv)

    def test_cong_ton_gia_von_binh_quan_va_hsd_som_nhat(self):
        hsd1 = timezone.localdate() + timedelta(days=60)
        hsd2 = timezone.localdate() + timedelta(days=20)
        self.nhap(100, 20000, hsd1)
        self.assertEqual(self.sp.ton_kho, 100)
        self.assertEqual(self.sp.gia_von, 20000)
        self.nhap(100, 30000, hsd2)
        self.assertEqual(self.sp.ton_kho, 200)
        self.assertEqual(self.sp.gia_von, 25000)
        self.assertEqual(self.sp.han_su_dung, hsd2)
        self.assertEqual(NhatKyKho.objects.filter(id_sp=self.sp, loai_giao_dich="NHAP_KHO").count(), 2)

    def test_chenh_lech_bat_buoc_ly_do(self):
        with self.assertRaises(NghiepVuError):
            self.nhap(100, 20000, thuc=90)
        self.sp.refresh_from_db()
        self.assertEqual(self.sp.ton_kho, 0)  # chưa cộng tồn khi lỗi
        self.nhap(100, 20000, thuc=90, ly_do="THIEU_HANG")
        self.assertEqual(self.sp.ton_kho, 90)

    def test_chi_cong_ton_khi_xac_nhan(self):
        p = PhieuNhap.objects.create(ma_phieu_nhap="PN-X", id_ncc=self.ncc, nguoi_tao=self.nv)
        ChiTietPhieuNhap.objects.create(ma_phieu_nhap=p, id_sp=self.sp, so_luong_dat=50, don_gia_nhap=1000)
        chuyen_trang_thai_giao(p, PhieuNhap.DANG_GIAO, self.nv)
        self.sp.refresh_from_db()
        self.assertEqual(self.sp.ton_kho, 0)


class XuatKhoTest(Base):
    def test_chan_xuat_am_kho(self):
        self.nhap(10, 20000)
        p = self.xuat(11)
        with self.assertRaises(NghiepVuError):
            xac_nhan_phieu_xuat(p.pk, self.nv)
        self.sp.refresh_from_db()
        self.assertEqual(self.sp.ton_kho, 10)

    def test_tru_ton_khi_xac_nhan(self):
        self.nhap(10, 20000)
        p = self.xuat(4)
        self.sp.refresh_from_db()
        self.assertEqual(self.sp.ton_kho, 10)
        xac_nhan_phieu_xuat(p.pk, self.nv)
        self.sp.refresh_from_db()
        self.assertEqual(self.sp.ton_kho, 6)

    def test_hang_het_han_chi_duoc_huy(self):
        self.nhap(10, 20000, hsd=timezone.localdate() - timedelta(days=1))
        with self.assertRaises(NghiepVuError):
            xac_nhan_phieu_xuat(self.xuat(2).pk, self.nv)
        xac_nhan_phieu_xuat(self.xuat(2, PhieuXuat.HUY_HANG).pk, self.nv)
        self.sp.refresh_from_db()
        self.assertEqual(self.sp.ton_kho, 8)


class KiemKeTest(Base):
    def test_dem_mu_2_buoc_va_can_bang(self):
        self.nhap(100, 20000)
        p = PhieuKiemKe.objects.create(ma_phieu_kiem="KK-1", nguoi_tao=self.nv)
        ct = ChiTietPhieuKiemKe.objects.create(ma_phieu_kiem=p, id_sp=self.sp, don_vi="Hộp")
        ghi_dem(p, 1, {ct.pk: D(95)}, {})
        ct.refresh_from_db()
        self.assertTrue(ct.co_chenh_lech)
        self.assertEqual(ct.sl_he_thong, 100)
        with self.assertRaises(NghiepVuError):  # còn dòng lệch chưa đếm lần 2
            gui_duyet(p)
        ghi_dem(p, 2, {ct.pk: D(96)}, {})
        gui_duyet(p)
        self.assertEqual(p.trang_thai, PhieuKiemKe.CHO_DUYET)
        duyet_kiem_ke(p.pk, self.admin)
        self.sp.refresh_from_db()
        self.assertEqual(self.sp.ton_kho, 96)
        log = NhatKyKho.objects.get(ma_phieu_kiem=p)
        self.assertEqual((log.sl_truoc, log.sl_sau, log.sl_thay_doi), (100, 96, -4))


class WebTest(Base):
    def test_khoa_tai_khoan_sau_5_lan_sai(self):
        for _ in range(5):
            self.client.post("/login/", {"username": "nv", "password": "sai"})
        self.nv.refresh_from_db()
        self.assertTrue(self.nv.is_locked)
        r = self.client.post("/login/", {"username": "nv", "password": "Nhanvien@123"})
        self.assertEqual(r.status_code, 200)  # không đăng nhập được dù đúng mật khẩu
        self.assertContains(r, "tạm khóa")

    def test_dang_nhap_dung_reset_dem_sai(self):
        self.client.post("/login/", {"username": "nv", "password": "sai"})
        self.client.post("/login/", {"username": "nv", "password": "Nhanvien@123"})
        self.nv.refresh_from_db()
        self.assertEqual(self.nv.so_lan_sai, 0)

    def test_nhan_vien_khong_duoc_xoa_hay_quan_ly_tai_khoan(self):
        self.client.force_login(self.nv)
        self.client.post(f"/san-pham/{self.sp.pk}/xoa/")
        self.assertTrue(SanPham.objects.filter(pk=self.sp.pk).exists())
        self.assertEqual(self.client.get("/tai-khoan/").status_code, 302)

    def test_xoa_san_pham_da_giao_dich_chuyen_ngung_hoat_dong(self):
        self.nhap(5, 1000)
        self.client.force_login(self.admin)
        self.client.post(f"/san-pham/{self.sp.pk}/xoa/")
        self.sp.refresh_from_db()
        self.assertEqual(self.sp.trang_thai, 0)

    def test_chan_xoa_danh_muc_con_san_pham(self):
        self.client.force_login(self.admin)
        self.client.post(f"/danh-muc/{self.dm.pk}/xoa/")
        self.assertTrue(DanhMuc.objects.filter(pk=self.dm.pk).exists())

    def test_ten_danh_muc_khong_trung_trong_cung_cha(self):
        self.client.force_login(self.admin)
        self.client.post("/danh-muc/luu/", {"ma_danhmuc": "DM2", "ten_danhmuc": "sữa"})
        self.assertFalse(DanhMuc.objects.filter(ma_danhmuc="DM2").exists())

    def test_api_key(self):
        self.assertEqual(self.client.get("/api/san-pham/").status_code, 401)
        key = tao_api_key("test", self.admin)
        r = self.client.get("/api/san-pham/?ma=SP1", HTTP_X_API_KEY=key)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["results"][0]["ma_sp"], "SP1")
        self.assertEqual(self.client.get("/api/ton-kho/SP1/", HTTP_X_API_KEY=key).json()["ton_kho"], 0)

    def test_bao_cao_nxt_khop_ton(self):
        self.nhap(50, 1000)
        xac_nhan_phieu_xuat(self.xuat(20).pk, self.nv)
        from .views.baocao import tinh_nxt

        today = timezone.localdate()
        row = tinh_nxt(today, today, SanPham.objects.filter(pk=self.sp.pk))[0]
        self.assertEqual((row["dau"], row["nhap"], row["xuat"], row["cuoi"]), (0, 50, 20, 30))
        self.client.force_login(self.admin)
        r = self.client.get("/bao-cao/xuat/?format=pdf")
        self.assertEqual(r["Content-Type"], "application/pdf")
