"""Kiểm thử các quy tắc nghiệp vụ trong đặc tả.  Chạy: python manage.py test wms"""
from datetime import timedelta
from decimal import Decimal as D

from django.test import TestCase
from django.utils import timezone

from .api_auth import tao_api_key
from .models import (
    ChiTietPhieuKiemKe, ChiTietPhieuNhap, ChiTietPhieuXuat, DanhMuc, NguoiDung, NhaCungCap, NhatKyKho, PhanBoLoXuat,
    PhieuKiemKe,
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

    def nhap(self, sl, gia, hsd=None, thuc=None, ly_do=None, ly_do_can_han="Nhận theo chỉ đạo quản lý"):
        p = PhieuNhap.objects.create(ma_phieu_nhap=next_doc_code("PN"), id_ncc=self.ncc, nguoi_tao=self.nv)
        ct = ChiTietPhieuNhap.objects.create(ma_phieu_nhap=p, id_sp=self.sp, so_luong_dat=sl, don_gia_nhap=gia)
        chuyen_trang_thai_giao(p, PhieuNhap.DANG_GIAO, self.nv)
        xac_nhan_phieu_nhap(p.pk, {ct.pk: {"sl": D(thuc if thuc is not None else sl), "hsd": hsd, "ly_do": ly_do}},
                            self.nv, ly_do_can_han=ly_do_can_han)
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

    def test_sua_phieu_xuat_hien_lai_dung_dong_cu(self):
        self.nhap(10, 20000)
        p = self.xuat(5)
        self.client.force_login(self.nv)
        r = self.client.get(f"/xuat-kho/{p.pk}/sua/")
        self.assertEqual(r.context["old"]["items"], [{"id": self.sp.pk, "sl": 5.0}])
        self.assertContains(r, "Đang sửa")
        self.assertNotContains(r, "Phiếu mới</span>")
        self.assertNotContains(r, 'x-init="init()"')        # Alpine tự gọi init() — gọi thêm sẽ nhân đôi dòng


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
        gui_duyet(p)                                            # hàng thiếu: không cần nhập HSD
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


class SuaLoiTestglocalTest(Base):
    """Các lỗi trong test/testglocal.pdf (mục 1-7, 10-20)."""

    def login(self, user):
        self.client.force_login(user)

    def test_danh_sach_kiem_ke_an_phieu_dang_kiem(self):
        dk = PhieuKiemKe.objects.create(ma_phieu_kiem="KK-DANG", nguoi_tao=self.nv)
        cd = PhieuKiemKe.objects.create(ma_phieu_kiem="KK-CHO", nguoi_tao=self.nv, trang_thai=PhieuKiemKe.CHO_DUYET)
        self.login(self.admin)
        r = self.client.get("/kiem-ke/")
        ma = [p.pk for p in r.context["page"]]
        self.assertIn(cd.pk, ma)
        self.assertNotIn(dk.pk, ma)
        self.assertNotIn("DANG_KIEM", [k for k, _ in r.context["trang_thai"]])
        r = self.client.get("/kiem-ke/?tt=DANG_KIEM")  # không lọc ngược ra được
        self.assertNotIn(dk.pk, [p.pk for p in r.context["page"]])

    def test_them_ca_danh_muc_cha_lay_san_pham_danh_muc_con(self):
        from .views.common import products_json
        cha = DanhMuc.objects.create(ma_danhmuc="DM0", ten_danhmuc="Đồ uống")
        self.dm.id_dmcha = cha
        self.dm.save()
        item = next(p for p in products_json(include_stock=False) if p["id"] == self.sp.pk)
        self.assertEqual(item["dm_ids"], [self.dm.pk, cha.pk])

    def test_dem_kiem_ke_khong_nhan_so_thap_phan(self):
        p = PhieuKiemKe.objects.create(ma_phieu_kiem="KK-T", nguoi_tao=self.nv)
        ct = ChiTietPhieuKiemKe.objects.create(ma_phieu_kiem=p, id_sp=self.sp, don_vi="Hộp")
        with self.assertRaises(NghiepVuError):
            ghi_dem(p, 1, {ct.pk: D("13.2")}, {})
        ghi_dem(p, 1, {ct.pk: D("13")}, {})

    def test_xuat_kho_khong_nhan_so_thap_phan(self):
        self.nhap(50, 20000)
        with self.assertRaises(NghiepVuError):
            xac_nhan_phieu_xuat(self.xuat(D("2.4")).pk, self.nv)
        self.sp.refresh_from_db()
        self.assertEqual(self.sp.ton_kho, 50)

    def test_admin_xoa_danh_muc_ngung_hoat_dong_con_san_pham(self):
        cha = DanhMuc.objects.create(ma_danhmuc="DM0", ten_danhmuc="Đồ uống")
        con = DanhMuc.objects.create(ma_danhmuc="DM2", ten_danhmuc="Sữa chua", id_dmcha=self.dm)
        self.dm.id_dmcha = cha
        self.dm.save()
        self.login(self.admin)
        # đang hoạt động + còn sản phẩm → chưa được xóa
        self.client.post(f"/danh-muc/{self.dm.pk}/xoa/")
        self.assertTrue(DanhMuc.objects.filter(pk=self.dm.pk).exists())
        # ngừng hoạt động → xóa được, SP + danh mục con chuyển lên danh mục cha
        DanhMuc.objects.filter(pk=self.dm.pk).update(is_active=False)
        self.client.post(f"/danh-muc/{self.dm.pk}/xoa/")
        self.assertFalse(DanhMuc.objects.filter(pk=self.dm.pk).exists())
        self.sp.refresh_from_db()
        con.refresh_from_db()
        self.assertEqual(self.sp.id_danhmuc_id, cha.pk)
        self.assertEqual(con.id_dmcha_id, cha.pk)

    def test_xoa_danh_muc_goc_ngung_hoat_dong_chuyen_sp_sang_chua_phan_loai(self):
        DanhMuc.objects.filter(pk=self.dm.pk).update(is_active=False)
        self.login(self.admin)
        self.client.post(f"/danh-muc/{self.dm.pk}/xoa/")
        self.sp.refresh_from_db()
        self.assertEqual(self.sp.id_danhmuc.ten_danhmuc, "Chưa phân loại")

    def test_nhan_vien_khong_xuat_duoc_bao_cao(self):
        self.login(self.nv)
        r = self.client.get("/bao-cao/")
        self.assertNotContains(r, "Xuất báo cáo")
        r = self.client.get("/bao-cao/xuat/?format=xlsx")
        self.assertEqual(r.status_code, 302)
        self.login(self.admin)
        r = self.client.get("/bao-cao/xuat/?format=xlsx")
        self.assertEqual(r.status_code, 200)

    def test_dashboard_canh_bao_han_va_xuat_bao_cao(self):
        self.nhap(50, 20000, hsd=timezone.localdate() - timedelta(days=3))
        self.login(self.admin)
        r = self.client.get("/?tab=het_han")
        self.assertEqual(r.context["het_han"], 1)
        self.assertContains(r, "Hạn sử dụng")
        self.assertContains(r, "Lô cần xử lý")
        self.assertContains(r, "Tạo phiếu xuất")
        self.assertNotContains(r, "Tồn kho Tối thiểu")
        self.assertContains(r, "Xuất báo cáo")
        r = self.client.get("/canh-bao/xuat-excel/?tab=het_han")
        self.assertEqual(r["Content-Type"], "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        self.login(self.nv)
        self.assertNotContains(self.client.get("/"), "Xuất báo cáo")
        self.assertEqual(self.client.get("/canh-bao/xuat-excel/").status_code, 302)

    def test_trang_dang_nhap_va_form_khong_con_noi_dung_thua(self):
        self.assertContains(self.client.get("/login/"), "MART &amp; CAFE")
        self.login(self.admin)
        self.assertNotContains(self.client.get("/tai-khoan/"), "Quyền hạn:")
        self.assertNotContains(self.client.get("/nhap-kho/tao/"), "Tổng giá trị phiếu")


class PhanBoLoTonKhoTest(Base):
    """Migration dữ liệu: chia ton_kho vào các lô, phần dư → phiếu Tồn đầu kỳ."""

    def phan_bo(self):
        from . import lo
        return lo.phan_bo_lo_ton_kho(SanPham, PhieuNhap, ChiTietPhieuNhap, NhaCungCap, NguoiDung)

    def con_lai(self, phieu):
        return phieu.chi_tiet.get().so_luong_con_lai

    def test_uu_tien_lo_nhap_gan_nhat_lo_cu_ve_0(self):
        p1, p2 = self.nhap(80, 20000), self.nhap(70, 21000)
        self.xuat_xac_nhan(100)                         # tồn còn 50
        self.phan_bo()
        self.assertEqual(self.con_lai(p2), 50)          # lô mới giữ số
        self.assertEqual(self.con_lai(p1), 0)           # lô cũ về 0
        self.assertFalse(PhieuNhap.objects.filter(pk=PhieuNhap.MA_TON_DAU).exists())

    def test_ton_kho_lon_hon_tong_lo_tao_phieu_ton_dau(self):
        p1 = self.nhap(80, 20000)
        SanPham.objects.filter(pk=self.sp.pk).update(ton_kho=200)   # VD: tồn gán trực tiếp / kiểm kê thừa
        tk = self.phan_bo()
        self.assertEqual(self.con_lai(p1), 80)
        ton_dau = PhieuNhap.objects.get(pk=PhieuNhap.MA_TON_DAU)
        ct = ton_dau.chi_tiet.get()
        self.assertEqual((ct.id_sp_id, ct.so_luong_con_lai, ct.so_luong_thuc_nhan), (self.sp.pk, 120, 120))
        self.assertEqual(ton_dau.trang_thai, PhieuNhap.DA_XAC_NHAN)
        self.assertLess(ton_dau.ngay_tao, p1.ngay_tao)  # hàng tồn đầu kỳ là hàng cũ nhất
        self.assertEqual(tk["ton_dau"], [("SP1", 120)])
        self.assertEqual(NhatKyKho.objects.filter(ma_phieu_nhap=ton_dau).count(), 0)  # tồn thực tế không đổi

        from .services import kiem_tra_tong_lo
        self.assertEqual(kiem_tra_tong_lo(), [])
        self.phan_bo()                                   # chạy lại không nhân đôi
        self.assertEqual(ton_dau.chi_tiet.count(), 1)
        self.assertEqual(kiem_tra_tong_lo(), [])

    def test_kiem_tra_tong_lo_phat_hien_lech(self):
        self.nhap(80, 20000)
        self.phan_bo()
        from .services import kiem_tra_tong_lo
        SanPham.objects.filter(pk=self.sp.pk).update(ton_kho=90)
        self.assertEqual(kiem_tra_tong_lo(), [("SP1", D(90), D(80))])

    def test_khong_huy_duoc_phieu_ton_dau(self):
        self.nhap(10, 20000)
        SanPham.objects.filter(pk=self.sp.pk).update(ton_kho=30)
        self.phan_bo()
        self.client.force_login(self.admin)
        self.client.post(f"/nhap-kho/{PhieuNhap.MA_TON_DAU}/huy/", {"ly_do": "thử"})
        self.assertEqual(PhieuNhap.objects.get(pk=PhieuNhap.MA_TON_DAU).trang_thai, PhieuNhap.DA_XAC_NHAN)
        self.sp.refresh_from_db()
        self.assertEqual(self.sp.ton_kho, 30)

    def xuat_xac_nhan(self, sl):
        xac_nhan_phieu_xuat(self.xuat(sl).pk, self.nv)
        self.sp.refresh_from_db()


class LoFefoTest(Base):
    """Chức năng 1: quản lý hạn sử dụng theo lô (FEFO)."""

    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()

    def ngay(self, n):
        return self.today + timedelta(days=n)

    def lo(self, phieu):
        return phieu.chi_tiet.get()

    def xuat_xn(self, sl, ly_do=PhieuXuat.BAN_HANG):
        p = self.xuat(sl, ly_do)
        xac_nhan_phieu_xuat(p.pk, self.nv)
        self.sp.refresh_from_db()
        return p

    def assertKhopTon(self):
        from .services import kiem_tra_tong_lo
        self.assertEqual(kiem_tra_tong_lo(), [])

    # ---- nhập hạn tay cho từng lô
    def test_nhap_han_tay_tung_lo_de_trong_la_khong_han(self):
        p = PhieuNhap.objects.create(ma_phieu_nhap="PN-T1", id_ncc=self.ncc, nguoi_tao=self.nv)
        ct = ChiTietPhieuNhap.objects.create(ma_phieu_nhap=p, id_sp=self.sp, so_luong_dat=100, don_gia_nhap=20000)
        chuyen_trang_thai_giao(p, PhieuNhap.DANG_GIAO, self.nv)
        # cùng 1 sản phẩm giao về 2 hạn khác nhau + 1 phần không có hạn → 3 lô; tổng = SL đặt nên không cần lý do
        xac_nhan_phieu_nhap(p.pk, {ct.pk: {"sl": D(60), "hsd": self.ngay(90), "ly_do": None}}, self.nv,
                            dong_moi=[{"goc": ct.pk, "sl": D(30), "hsd": self.ngay(120)},
                                      {"goc": ct.pk, "sl": D(10), "hsd": None}])
        lots = list(p.chi_tiet.order_by("id_chi_tiet").values_list("so_luong_con_lai", "han_su_dung", "ly_do_chenh_lech"))
        self.assertEqual(lots, [(60, self.ngay(90), None), (30, self.ngay(120), None), (10, None, None)])
        self.sp.refresh_from_db()
        self.assertEqual((self.sp.ton_kho, self.sp.han_su_dung), (100, self.ngay(90)))  # HSD SP = hạn sớm nhất
        self.assertKhopTon()

    def test_tach_lo_chenh_lech_tinh_theo_tong_san_pham(self):
        p = PhieuNhap.objects.create(ma_phieu_nhap="PN-T3", id_ncc=self.ncc, nguoi_tao=self.nv)
        ct = ChiTietPhieuNhap.objects.create(ma_phieu_nhap=p, id_sp=self.sp, so_luong_dat=100, don_gia_nhap=20000)
        chuyen_trang_thai_giao(p, PhieuNhap.DANG_GIAO, self.nv)
        dong = {ct.pk: {"sl": D(60), "hsd": self.ngay(90), "ly_do": None}}
        moi = [{"goc": ct.pk, "sl": D(30), "hsd": self.ngay(120)}]
        with self.assertRaisesMessage(NghiepVuError, "bắt buộc chọn lý do"):   # 60 + 30 ≠ 100
            xac_nhan_phieu_nhap(p.pk, dong, self.nv, dong_moi=moi)
        self.assertEqual(p.chi_tiet.count(), 1)                                 # rollback cả dòng tách
        dong[ct.pk]["ly_do"] = "THIEU_HANG"
        xac_nhan_phieu_nhap(p.pk, dong, self.nv, dong_moi=moi)
        ct.refresh_from_db()
        self.assertEqual(ct.ly_do_chenh_lech, "THIEU_HANG")

    def test_nhap_han_da_qua_phai_xac_nhan_lai_kem_ly_do(self):
        from .services import luu_nhap_doi_soat
        p = PhieuNhap.objects.create(ma_phieu_nhap="PN-T2", id_ncc=self.ncc, nguoi_tao=self.nv)
        ct = ChiTietPhieuNhap.objects.create(ma_phieu_nhap=p, id_sp=self.sp, so_luong_dat=10, don_gia_nhap=20000)
        chuyen_trang_thai_giao(p, PhieuNhap.DANG_GIAO, self.nv)
        dong = {ct.pk: {"sl": D(10), "hsd": self.ngay(-2), "ly_do": None}}
        luu_nhap_doi_soat(p.pk, dong, None)                     # không chặn lưu nháp
        with self.assertRaisesMessage(NghiepVuError, "Lô hàng cận hạn/đã hết hạn"):
            xac_nhan_phieu_nhap(p.pk, dong, self.nv)
        self.sp.refresh_from_db()
        self.assertEqual(self.sp.ton_kho, 0)                    # rollback, chưa cộng tồn
        xac_nhan_phieu_nhap(p.pk, dong, self.nv, ly_do_can_han="NCC đổi trả trong tuần")
        ct.refresh_from_db()
        self.assertIn("đã hết hạn", ct.ghi_chu_doi_soat)
        self.assertIn("NCC đổi trả trong tuần", ct.ghi_chu_doi_soat)

    def test_sua_han_lo_ghi_nhat_ky(self):
        from .services import sua_han_lo
        p = self.nhap(20, 20000, hsd=self.ngay(60))
        lo = self.lo(p)
        with self.assertRaises(NghiepVuError):                  # bắt buộc lý do
            sua_han_lo(lo.pk, self.ngay(100), "", self.nv)
        sua_han_lo(lo.pk, self.ngay(100), "Nhập nhầm hạn", self.nv)
        lo.refresh_from_db()
        self.sp.refresh_from_db()
        self.assertEqual((lo.han_su_dung, lo.so_luong_con_lai, self.sp.ton_kho), (self.ngay(100), 20, 20))
        self.assertEqual(self.sp.han_su_dung, self.ngay(100))
        nk = NhatKyKho.objects.get(loai_giao_dich=NhatKyKho.SUA_HAN_LO)
        self.assertEqual((nk.lo_id, nk.han_cu, nk.han_moi, nk.nguoi_thuc_hien, nk.ly_do, nk.sl_thay_doi),
                         (lo.pk, self.ngay(60), self.ngay(100), self.nv, "Nhập nhầm hạn", 0))
        # báo cáo N-X-T không tính nhật ký sửa hạn
        from .views.baocao import tinh_nxt
        r = tinh_nxt(self.today, self.today, SanPham.objects.filter(pk=self.sp.pk))[0]
        self.assertEqual((r["nhap"], r["kiem"], r["cuoi"]), (20, 0, 20))

    # ---- FEFO
    def test_fefo_tru_qua_2_lo_khong_han_xep_cuoi(self):
        c = self.nhap(20, 20000, hsd=None)                      # không hạn → xếp cuối dù nhập trước
        b = self.nhap(50, 20000, hsd=self.ngay(40))
        a = self.nhap(30, 20000, hsd=self.ngay(10))
        px = self.xuat_xn(40)
        self.assertEqual([self.lo(x).so_luong_con_lai for x in (a, b, c)], [0, 40, 20])
        pb = list(px.chi_tiet.get().phan_bo.values_list("lo__ma_phieu_nhap", "so_luong"))
        self.assertEqual(pb, [(a.pk, 30), (b.pk, 10)])
        self.assertEqual(self.sp.han_su_dung, self.ngay(40))
        self.assertKhopTon()

    def test_cung_han_lo_nhap_truoc_tru_truoc(self):
        p1 = self.nhap(10, 20000, hsd=self.ngay(30))
        p2 = self.nhap(10, 20000, hsd=self.ngay(30))
        PhieuNhap.objects.filter(pk=p2.pk).update(ngay_xac_nhan=timezone.now() + timedelta(hours=1))
        self.xuat_xn(4)
        self.assertEqual((self.lo(p1).so_luong_con_lai, self.lo(p2).so_luong_con_lai), (6, 10))

    def test_xuat_vuot_ton_bi_rollback(self):
        a = self.nhap(10, 20000, hsd=self.ngay(20))
        p = self.xuat(15)
        with self.assertRaises(NghiepVuError):
            xac_nhan_phieu_xuat(p.pk, self.nv)
        self.sp.refresh_from_db()
        p.refresh_from_db()
        self.assertEqual((self.sp.ton_kho, self.lo(a).so_luong_con_lai, p.trang_thai), (10, 10, PhieuXuat.CHUA_XAC_NHAN))
        self.assertFalse(PhanBoLoXuat.objects.exists())

    def test_tru_ton_fefo_khong_du_hang_trong_cac_lo(self):
        from .services import tru_ton_fefo
        self.nhap(10, 20000, hsd=self.ngay(20))
        with self.assertRaisesMessage(NghiepVuError, "Không đủ hàng trong các lô"):
            tru_ton_fefo(self.sp.pk, D(11))

    def test_ban_hang_chi_lay_lo_con_han(self):
        het = self.nhap(10, 20000, hsd=self.ngay(-1))
        tot = self.nhap(20, 20000, hsd=self.ngay(60))
        with self.assertRaisesMessage(NghiepVuError, "lô đã hết hạn chỉ được xuất với lý do Hủy hàng"):
            xac_nhan_phieu_xuat(self.xuat(25).pk, self.nv)
        self.xuat_xn(20)                                        # bán được phần còn hạn, lô hết hạn giữ nguyên
        self.assertEqual((self.lo(het).so_luong_con_lai, self.lo(tot).so_luong_con_lai), (10, 0))
        with self.assertRaises(NghiepVuError):
            xac_nhan_phieu_xuat(self.xuat(1, PhieuXuat.DIEU_CHINH).pk, self.nv)
        self.xuat_xn(10, PhieuXuat.HUY_HANG)                    # lô hết hạn chỉ hủy
        self.assertEqual(self.sp.ton_kho, 0)

    def test_lo_ve_0_thi_het_canh_bao(self):
        from .services import canh_bao_han_su_dung
        self.nhap(10, 20000, hsd=self.ngay(-3))
        self.nhap(5, 20000, hsd=self.ngay(5))
        self.assertEqual(sorted(l.muc_han for l in canh_bao_han_su_dung()), ["DA_HET_HAN", "SAP_HET_HAN"])
        self.xuat_xn(10, PhieuXuat.HUY_HANG)
        self.assertEqual([l.muc_han for l in canh_bao_han_su_dung()], ["SAP_HET_HAN"])
        self.xuat_xn(5)
        self.assertEqual(canh_bao_han_su_dung(), [])

    def test_dashboard_tab_het_han_hien_theo_lo(self):
        p = self.nhap(10, 20000, hsd=self.ngay(-3))
        self.client.force_login(self.nv)
        r = self.client.get("/?tab=het_han")
        self.assertTrue(r.context["theo_lo"])
        self.assertEqual([lo.pk for lo in r.context["page"]], [self.lo(p).pk])
        self.assertContains(r, f"/xuat-kho/tao/?sp={self.sp.pk}&sl=10&ly_do=HUY_HANG")

    # ---- hủy phiếu
    def test_huy_phieu_xuat_tra_ve_dung_lo(self):
        from .services import huy_phieu_xuat
        a = self.nhap(30, 20000, hsd=self.ngay(10))
        b = self.nhap(50, 20000, hsd=self.ngay(40))
        px = self.xuat_xn(40)
        self.xuat_xn(5)                                         # phiếu khác lấy tiếp từ lô B
        huy_phieu_xuat(px.pk, self.admin, "Khách trả hàng")
        self.sp.refresh_from_db()
        self.assertEqual((self.lo(a).so_luong_con_lai, self.lo(b).so_luong_con_lai, self.sp.ton_kho), (30, 45, 75))
        self.assertKhopTon()

    def test_khong_huy_phieu_nhap_khi_lo_da_xuat_bot(self):
        from .services import huy_phieu_nhap
        a = self.nhap(30, 20000, hsd=self.ngay(10))
        self.xuat_xn(1)
        with self.assertRaisesMessage(NghiepVuError, "đã được xuất"):
            huy_phieu_nhap(a.pk, self.admin, "Nhập nhầm")
        b = self.nhap(10, 20000, hsd=self.ngay(50))
        huy_phieu_nhap(b.pk, self.admin, "Nhập nhầm")
        self.sp.refresh_from_db()
        self.assertEqual((self.sp.ton_kho, self.lo(b).so_luong_con_lai), (29, 0))
        self.assertKhopTon()

    # ---- kiểm kê
    def kiem(self, dem):
        p = PhieuKiemKe.objects.create(ma_phieu_kiem=next_doc_code("KK"), nguoi_tao=self.nv)
        ct = ChiTietPhieuKiemKe.objects.create(ma_phieu_kiem=p, id_sp=self.sp, don_vi="Hộp")
        ghi_dem(p, 1, {ct.pk: D(dem)}, {})
        p.refresh_from_db()
        if p.can_dem_lan_2:
            ghi_dem(p, 2, {ct.pk: D(dem)}, {})
            p.refresh_from_db()
        ct.refresh_from_db()
        return p, ct

    def test_kiem_ke_thieu_tu_xuat_lo_hsd_cu_nhat(self):
        a = self.nhap(30, 20000, hsd=self.ngay(10))
        b = self.nhap(50, 20000, hsd=self.ngay(40))
        p, ct = self.kiem(45)                                   # thiếu 35
        self.assertFalse(ct.can_khai_hsd)
        gui_duyet(p)                                            # hàng thiếu không cần nhập HSD
        duyet_kiem_ke(p.pk, self.admin)
        self.assertEqual((self.lo(a).so_luong_con_lai, self.lo(b).so_luong_con_lai), (0, 45))
        self.assertKhopTon()

    def test_kiem_ke_thua_bat_buoc_khai_hsd_hoac_ly_do(self):
        a = self.nhap(50, 20000, hsd=self.ngay(25))
        b = self.nhap(50, 20000, hsd=self.ngay(39))
        p, ct = self.kiem(105)                                  # thừa 5
        with self.assertRaisesMessage(NghiepVuError, "Nhập hạn sử dụng"):
            gui_duyet(p)
        with self.assertRaisesMessage(NghiepVuError, "phải bằng đúng số hàng thừa 5"):
            gui_duyet(p, {ct.pk: {"dong": [(self.ngay(39), D(105))]}})
        with self.assertRaisesMessage(NghiepVuError, "Không nhập HSD"):
            gui_duyet(p, {ct.pk: {"dong": [(None, D(5))]}})
        with self.assertRaisesMessage(NghiepVuError, "ghi lý do"):
            gui_duyet(p, {ct.pk: {"khong_hsd": True, "ly_do": "  "}})
        self.assertEqual(p.trang_thai, PhieuKiemKe.DANG_KIEM)
        gui_duyet(p, {ct.pk: {"dong": [(self.ngay(39), D(5))]}})
        duyet_kiem_ke(p.pk, self.admin)
        self.sp.refresh_from_db()
        self.assertEqual((self.lo(a).so_luong_con_lai, self.lo(b).so_luong_con_lai, self.sp.ton_kho), (50, 55, 105))
        self.assertFalse(PhieuNhap.objects.filter(pk=f"PN-{p.pk}").exists())   # cùng hạn → cộng vào lô có sẵn
        self.assertKhopTon()

    def test_kiem_ke_thua_hsd_moi_tao_lo(self):
        from .services import huy_phieu_nhap
        a = self.nhap(30, 20000, hsd=self.ngay(10))
        p, ct = self.kiem(34)
        gui_duyet(p, {ct.pk: {"dong": [(self.ngay(200), D(3)), (self.ngay(10), D(1))]}})
        duyet_kiem_ke(p.pk, self.admin)
        lo_moi = ChiTietPhieuNhap.objects.get(ma_phieu_nhap=f"PN-{p.pk}")
        self.assertEqual((lo_moi.so_luong_con_lai, lo_moi.han_su_dung), (3, self.ngay(200)))
        self.assertEqual(self.lo(a).so_luong_con_lai, 31)
        self.sp.refresh_from_db()
        self.assertEqual((self.sp.ton_kho, self.sp.han_su_dung), (34, self.ngay(10)))
        self.assertKhopTon()
        with self.assertRaises(NghiepVuError):                  # phiếu hệ thống không hủy được
            huy_phieu_nhap(f"PN-{p.pk}", self.admin, "x")

    def test_kiem_ke_thua_khong_nhap_hsd_vao_lo_cu_nhat(self):
        a = self.nhap(20, 20000, hsd=self.ngay(30))
        b = self.nhap(20, 20000, hsd=self.ngay(10))             # lô có hạn cũ nhất
        p, ct = self.kiem(43)
        gui_duyet(p, {ct.pk: {"khong_hsd": True, "ly_do": "Bao bì không in hạn"}})
        ct.refresh_from_db()
        self.assertEqual(ct.ly_do_khong_hsd, "Bao bì không in hạn")
        duyet_kiem_ke(p.pk, self.admin)
        self.assertEqual((self.lo(a).so_luong_con_lai, self.lo(b).so_luong_con_lai), (20, 23))
        self.assertFalse(PhieuNhap.objects.filter(pk=f"PN-{p.pk}").exists())
        self.assertKhopTon()

    def test_kiem_ke_thua_khong_con_lo_tao_lo_khong_hsd(self):
        p, ct = self.kiem(3)                                    # hệ thống 0, chưa có lô nào
        gui_duyet(p, {ct.pk: {"khong_hsd": True, "ly_do": "Hàng mẫu"}})
        duyet_kiem_ke(p.pk, self.admin)
        lo_moi = ChiTietPhieuNhap.objects.get(ma_phieu_nhap=f"PN-{p.pk}")
        self.assertEqual((lo_moi.so_luong_con_lai, lo_moi.han_su_dung), (3, None))
        self.assertKhopTon()

    def test_dem_ve_0_khong_can_khai_hsd(self):
        self.nhap(5, 20000, hsd=self.ngay(30))
        p, _ = self.kiem(0)
        gui_duyet(p)
        duyet_kiem_ke(p.pk, self.admin)
        self.sp.refresh_from_db()
        self.assertEqual(self.sp.ton_kho, 0)
        self.assertKhopTon()

    def test_view_hang_thieu_khong_hien_bang_hsd(self):
        a = self.nhap(30, 20000, hsd=self.ngay(10))
        b = self.nhap(50, 20000, hsd=self.ngay(40))
        p, ct = self.kiem(45)
        self.client.force_login(self.nv)
        r = self.client.get(f"/kiem-ke/{p.pk}/")
        self.assertFalse(r.context["hsd_sua"])
        self.assertNotContains(r, "Hạn sử dụng hàng thừa")
        self.client.post(f"/kiem-ke/{p.pk}/gui-duyet/")
        p.refresh_from_db()
        self.assertEqual(p.trang_thai, PhieuKiemKe.CHO_DUYET)
        self.client.force_login(self.admin)
        r = self.client.get(f"/kiem-ke/{p.pk}/")
        self.assertEqual(r.context["bang_hsd"][0]["du_kien"],
                         [{"nhan": self.ngay(10).strftime("%d/%m/%Y"), "sl": 30},
                          {"nhan": self.ngay(40).strftime("%d/%m/%Y"), "sl": 5}])
        self.client.post(f"/kiem-ke/{p.pk}/duyet/")
        self.assertEqual((self.lo(a).so_luong_con_lai, self.lo(b).so_luong_con_lai), (0, 45))

    def test_view_hang_thua_khai_hsd_va_duyet(self):
        a = self.nhap(50, 20000, hsd=self.ngay(25))
        b = self.nhap(50, 20000, hsd=self.ngay(39))
        p, ct = self.kiem(105)
        self.client.force_login(self.admin)                     # chỉ Quản trị viên có bảng nhập HSD hàng thừa
        r = self.client.get(f"/kiem-ke/{p.pk}/")
        self.assertTrue(r.context["hsd_sua"])
        it = r.context["bang_hsd"][0]
        self.assertEqual((it["loai"], it["sl"]), ("thua", 5))
        self.assertEqual([g["hsd"] for g in it["goi_y"]], [self.ngay(25).isoformat(), self.ngay(39).isoformat()])
        self.assertContains(r, "Hạn sử dụng hàng thừa")
        self.client.post(f"/kiem-ke/{p.pk}/gui-duyet/", {                       # có số lượng nhưng thiếu HSD
            f"hsd_ngay_{ct.pk}": [self.ngay(25).isoformat(), ""], f"hsd_sl_{ct.pk}": ["3", "2"]})
        p.refresh_from_db()
        self.assertEqual(p.trang_thai, PhieuKiemKe.DANG_KIEM)
        self.client.post(f"/kiem-ke/{p.pk}/gui-duyet/", {
            f"hsd_ngay_{ct.pk}": [self.ngay(25).isoformat(), self.ngay(300).isoformat()],
            f"hsd_sl_{ct.pk}": ["3", "2"]})
        p.refresh_from_db()
        self.assertEqual(p.trang_thai, PhieuKiemKe.CHO_DUYET)
        self.client.post(f"/kiem-ke/{p.pk}/duyet/")
        self.assertEqual((self.lo(a).so_luong_con_lai, self.lo(b).so_luong_con_lai), (53, 50))
        self.assertEqual(ChiTietPhieuNhap.objects.get(ma_phieu_nhap=f"PN-{p.pk}").han_su_dung, self.ngay(300))
        self.assertKhopTon()

    def test_view_hang_thua_khong_nhap_hsd(self):
        a = self.nhap(10, 20000, hsd=self.ngay(25))
        p, ct = self.kiem(12)
        self.client.force_login(self.admin)
        self.client.post(f"/kiem-ke/{p.pk}/gui-duyet/", {f"hsd_khong_{ct.pk}": "1", f"hsd_lydo_{ct.pk}": "Không in HSD"})
        p.refresh_from_db()
        self.assertEqual(p.trang_thai, PhieuKiemKe.CHO_DUYET)
        r = self.client.get(f"/kiem-ke/{p.pk}/")
        self.assertContains(r, "Không in HSD")
        self.client.post(f"/kiem-ke/{p.pk}/duyet/")
        self.assertEqual(self.lo(a).so_luong_con_lai, 12)
        self.assertKhopTon()

    def test_view_nhan_vien_gui_duyet_khong_nhap_hsd(self):
        a = self.nhap(20, 20000, hsd=self.ngay(30))
        b = self.nhap(20, 20000, hsd=self.ngay(10))             # lô có hạn cũ nhất
        p, ct = self.kiem(43)                                   # thừa 3
        self.client.force_login(self.nv)
        r = self.client.get(f"/kiem-ke/{p.pk}/")
        self.assertFalse(r.context["hsd_sua"])
        self.assertNotContains(r, "Hạn sử dụng hàng thừa")
        self.assertNotContains(r, "Tồn hệ thống được ẩn")
        # HSD nhân viên cố gửi lên bị bỏ qua
        self.client.post(f"/kiem-ke/{p.pk}/gui-duyet/", {f"hsd_ngay_{ct.pk}": [self.ngay(300).isoformat()],
                                                        f"hsd_sl_{ct.pk}": ["3"]})
        p.refresh_from_db()
        ct.refresh_from_db()
        self.assertEqual(p.trang_thai, PhieuKiemKe.CHO_DUYET)
        self.assertFalse(ct.da_khai_hsd)
        self.client.force_login(self.admin)
        r = self.client.get(f"/kiem-ke/{p.pk}/")
        self.assertNotContains(r, "Khi duyệt:")
        self.assertNotContains(r, "Chưa khai HSD")
        self.client.post(f"/kiem-ke/{p.pk}/duyet/")
        p.refresh_from_db()
        self.assertEqual(p.trang_thai, PhieuKiemKe.HOAN_THANH)
        self.assertEqual((self.lo(a).so_luong_con_lai, self.lo(b).so_luong_con_lai), (20, 23))
        self.assertKhopTon()

    def test_view_nhan_vien_khong_duoc_huy_phieu_kiem_ke(self):
        self.nhap(10, 20000, hsd=self.ngay(25))
        p, ct = self.kiem(10)
        self.client.force_login(self.nv)                        # nv là người tạo phiếu nhưng vẫn không được hủy
        r = self.client.get(f"/kiem-ke/{p.pk}/")
        self.assertNotContains(r, "Hủy phiếu")
        self.client.post(f"/kiem-ke/{p.pk}/huy/")
        p.refresh_from_db()
        self.assertEqual(p.trang_thai, PhieuKiemKe.DANG_KIEM)
        self.client.force_login(self.admin)
        r = self.client.get(f"/kiem-ke/{p.pk}/")
        self.assertContains(r, "Hủy phiếu")
        self.client.post(f"/kiem-ke/{p.pk}/huy/")
        p.refresh_from_db()
        self.assertEqual(p.trang_thai, PhieuKiemKe.DA_HUY)

    def test_dem_lan_1_khong_ghi_de(self):
        self.nhap(5, 20000)
        p, ct = self.kiem(5)
        with self.assertRaisesMessage(NghiepVuError, "đã có kết quả đếm lần 1"):
            ghi_dem(p, 1, {ct.pk: D(9)}, {})

    def test_view_sua_han_lo(self):
        p = self.nhap(20, 20000, hsd=self.ngay(60))
        lo = self.lo(p)
        self.client.force_login(self.nv)
        self.client.post(f"/nhap-kho/lo/{lo.pk}/sua-han/", {"han_moi": self.ngay(90).isoformat(), "ly_do": "Sai hạn"})
        lo.refresh_from_db()
        self.assertEqual(lo.han_su_dung, self.ngay(90))
        r = self.client.get(f"/nhap-kho/{p.pk}/")
        self.assertContains(r, "Lịch sử sửa hạn lô")
        self.assertContains(r, "Sai hạn")

    def test_view_doi_soat_tach_lo(self):
        p = PhieuNhap.objects.create(ma_phieu_nhap="PN-T4", id_ncc=self.ncc, nguoi_tao=self.nv)
        ct = ChiTietPhieuNhap.objects.create(ma_phieu_nhap=p, id_sp=self.sp, so_luong_dat=10, don_gia_nhap=20000)
        chuyen_trang_thai_giao(p, PhieuNhap.DANG_GIAO, self.nv)
        self.client.force_login(self.nv)
        self.assertEqual(self.client.get(f"/nhap-kho/{p.pk}/doi-soat/").status_code, 200)
        self.client.post(f"/nhap-kho/{p.pk}/doi-soat/", {
            "action": "xac_nhan", f"sl_{ct.pk}": "6", f"hsd_{ct.pk}": self.ngay(100).isoformat(),
            "moi_goc": str(ct.pk), "moi_sl": "4", "moi_hsd": self.ngay(150).isoformat(),
        })
        p.refresh_from_db()
        self.assertEqual(p.trang_thai, PhieuNhap.DA_XAC_NHAN)
        self.assertEqual(sorted(p.chi_tiet.values_list("so_luong_con_lai", flat=True)), [4, 6])


class SsRopTest(Base):
    """Chức năng 2: tồn kho an toàn (SS) và điểm đặt hàng lại (ROP)."""

    def setUp(self):
        super().setUp()
        self.today = timezone.localdate()
        self.now = timezone.now()

    def ban(self, ngay_truoc, sl, sp=None):
        """Phiếu xuất Bán hàng đã xác nhận cách hôm nay `ngay_truoc` ngày (chỉ dữ liệu lịch sử cho công thức)."""
        luc = self.now - timedelta(days=ngay_truoc)
        p = PhieuXuat.objects.create(ma_phieu_xuat=next_doc_code("PX"), nguoi_tao=self.nv, ly_do_xuat=PhieuXuat.BAN_HANG,
                                     trang_thai=PhieuXuat.DA_XAC_NHAN, ngay_xac_nhan=luc)
        ChiTietPhieuXuat.objects.create(ma_phieu_xuat=p, id_sp=sp or self.sp, so_luong_xuat=sl)

    def nhap_lt(self, so_ngay_cho, truoc=10):
        """Phiếu nhập đã xác nhận, chờ hàng `so_ngay_cho` ngày (ngày xác nhận − ngày tạo)."""
        xn = self.now - timedelta(days=truoc)
        p = PhieuNhap.objects.create(ma_phieu_nhap=next_doc_code("PN"), id_ncc=self.ncc, nguoi_tao=self.nv,
                                     ngay_tao=xn - timedelta(days=so_ngay_cho), trang_thai=PhieuNhap.DA_XAC_NHAN,
                                     trang_thai_giao=PhieuNhap.DA_GIAO, ngay_xac_nhan=xn)
        ChiTietPhieuNhap.objects.create(ma_phieu_nhap=p, id_sp=self.sp, so_luong_dat=1, don_gia_nhap=1)

    def tinh(self):
        from .services import tinh_ss_rop
        tk = tinh_ss_rop()
        self.sp.refresh_from_db()
        return tk

    def test_nhu_cau_deu_ss_bang_0_rop_bang_d_nhan_lt(self):
        for i in range(90):                                   # bán đều 10/ngày suốt 90 ngày
            self.ban(i, 10)
        self.nhap_lt(3)
        self.tinh()
        sp = self.sp
        self.assertTrue(sp.du_du_lieu_ss)
        self.assertEqual((sp.nhu_cau_tb, sp.do_lech_nhu_cau, sp.lead_time, sp.ss, sp.rop), (10, 0, 3, 0, 30))
        self.assertIsNotNone(sp.ngay_tinh_rop)
        SanPham.objects.filter(pk=sp.pk).update(ton_kho=50)
        sp.refresh_from_db()
        self.assertEqual(sp.goi_y_dat(14), 120)               # 10 × (3 + 14) + 0 − 50

    def test_cong_thuc_ss_rop_nhu_cau_dao_dong(self):
        import math
        import statistics
        ban = {i: (20 if i % 2 else 0) for i in range(90)}    # ngày có ngày không → σd > 0
        for i, sl in ban.items():
            if sl:
                self.ban(i, sl)
        self.nhap_lt(4, truoc=30)
        self.nhap_lt(6, truoc=20)                             # LT = (4 + 6) / 2 = 5
        self.tinh()
        chuoi = [ban[i] for i in range(90)]
        d, sd = statistics.fmean(chuoi), statistics.stdev(chuoi)
        z = statistics.NormalDist().inv_cdf(0.95)
        self.assertAlmostEqual(float(self.sp.do_lech_nhu_cau), sd, places=3)
        self.assertEqual(self.sp.lead_time, 5)
        self.assertEqual(self.sp.ss, math.ceil(z * sd * math.sqrt(5)))
        self.assertEqual(self.sp.rop, math.ceil(d * 5 + z * sd * math.sqrt(5)))

    def test_lt_chi_lay_5_phieu_gan_nhat_toi_thieu_1_va_mac_dinh(self):
        for i in range(40):
            self.ban(i, 1)
        self.tinh()
        self.assertEqual(self.sp.lead_time, 7)                # chưa có phiếu nhập → lead_time_mac_dinh
        self.nhap_lt(0)                                       # nhận ngay trong ngày → tối thiểu 1
        self.tinh()
        self.assertEqual(self.sp.lead_time, 1)
        for k in range(5):                                    # 5 phiếu gần hơn, mỗi phiếu chờ 2 ngày
            self.nhap_lt(2, truoc=5 - k)
        self.tinh()
        self.assertEqual(self.sp.lead_time, 2)

    def test_chua_du_du_lieu(self):
        self.sp.nguong_toi_thieu = 15
        self.sp.save()
        for i in range(10):                                   # lần bán đầu tiên mới cách 9 ngày
            self.ban(i, 5)
        tk = self.tinh()
        self.assertEqual(tk["chua_du"], 1)
        self.assertFalse(self.sp.du_du_lieu_ss)
        self.assertIsNone(self.sp.ss)
        self.assertEqual(self.sp.rop, 15)                     # ROP = ngưỡng tối thiểu

    def test_ban_hang_ngoai_cua_so_va_ly_do_khac_khong_tinh(self):
        for i in range(30, 40):
            self.ban(i, 9)
        self.ban(200, 1000)                                   # ngoài 90 ngày → không vào nhu cầu
        p = PhieuXuat.objects.create(ma_phieu_xuat="PX-HUY", nguoi_tao=self.nv, ly_do_xuat=PhieuXuat.HUY_HANG,
                                     trang_thai=PhieuXuat.DA_XAC_NHAN, ngay_xac_nhan=self.now)
        ChiTietPhieuXuat.objects.create(ma_phieu_xuat=p, id_sp=self.sp, so_luong_xuat=500)  # hủy hàng → không tính
        self.tinh()
        self.assertEqual(self.sp.nhu_cau_tb, 1)               # 10 ngày × 9 / 90 ngày

    def test_canh_bao_ton_kho_theo_ss_rop(self):
        sp = self.sp
        sp.ss, sp.rop = D(10), D(25)
        for ton, muc in ((0, "HET_HANG"), (5, "DUOI_AN_TOAN"), (10, "DUOI_AN_TOAN"), (11, "CAN_DAT_HANG"),
                         (25, "CAN_DAT_HANG"), (26, "AN_TOAN")):
            sp.ton_kho = D(ton)
            self.assertEqual(sp.muc_ton, muc, ton)
        sp.ss, sp.rop, sp.nguong_toi_thieu, sp.ton_kho = None, None, D(10), D(8)   # chưa tính → dùng ngưỡng
        self.assertEqual(sp.muc_ton, "CAN_DAT_HANG")

    def test_dashboard_bang_ss_rop_va_tao_phieu_nhap_goi_y(self):
        SanPham.objects.filter(pk=self.sp.pk).update(ton_kho=5, ss=10, rop=25, nhu_cau_tb=2, lead_time=3,
                                                     du_du_lieu_ss=True)
        self.client.force_login(self.nv)
        r = self.client.get("/?tab=duoi_an_toan")
        self.assertEqual([s.pk for s in r.context["page"]], [self.sp.pk])
        self.assertContains(r, f"/nhap-kho/tao/?sp={self.sp.pk}&sl=39")   # 2 × (3 + 14) + 10 − 5
        self.assertNotContains(r, "Tính lại SS/ROP")                       # nhân viên không có nút

    def test_quyen_tinh_lai_va_cau_hinh(self):
        from .models import CauHinhTonKho
        self.client.force_login(self.nv)
        self.client.post("/ton-kho/tinh-lai-ss-rop/")
        self.sp.refresh_from_db()
        self.assertIsNone(self.sp.ngay_tinh_rop)
        self.assertEqual(self.client.get("/ton-kho/cau-hinh/").status_code, 302)
        self.client.post("/ton-kho/cau-hinh/", {"muc_phuc_vu": "0.99", "so_ngay_du_lieu": "60",
                                                "lead_time_mac_dinh": "5", "chu_ky_dat_hang": "7"})
        self.assertEqual(CauHinhTonKho.lay().muc_phuc_vu, D("0.95"))

        self.client.force_login(self.admin)
        self.assertEqual(self.client.get("/ton-kho/cau-hinh/").status_code, 200)
        self.client.post("/ton-kho/cau-hinh/", {"muc_phuc_vu": "1.5", "so_ngay_du_lieu": "60",
                                                "lead_time_mac_dinh": "5", "chu_ky_dat_hang": "7"})
        self.assertEqual(CauHinhTonKho.lay().muc_phuc_vu, D("0.95"))          # giá trị sai → không lưu
        self.client.post("/ton-kho/cau-hinh/", {"muc_phuc_vu": "0.99", "so_ngay_du_lieu": "60",
                                                "lead_time_mac_dinh": "5", "chu_ky_dat_hang": "7", "tinh_lai": "1"})
        cfg = CauHinhTonKho.lay()
        self.assertEqual((cfg.muc_phuc_vu, cfg.so_ngay_du_lieu, cfg.lead_time_mac_dinh, cfg.chu_ky_dat_hang),
                         (D("0.99"), 60, 5, 7))
        self.sp.refresh_from_db()
        self.assertIsNotNone(self.sp.ngay_tinh_rop)
        self.client.post("/ton-kho/tinh-lai-ss-rop/", {"next": "https://evil.example/"})
        self.assertEqual(self.client.post("/ton-kho/tinh-lai-ss-rop/", {"next": "https://evil.example/"}).url, "/")

    def test_lenh_tinh_ss_rop_va_api(self):
        from io import StringIO
        from django.core.management import call_command
        for i in range(40):
            self.ban(i, 3)
        call_command("tinh_ss_rop", stdout=StringIO())
        self.sp.refresh_from_db()
        self.assertIsNotNone(self.sp.rop)
        raw = tao_api_key("test", self.admin)
        r = self.client.get(f"/api/san-pham/{self.sp.ma_sp}/", HTTP_X_API_KEY=raw)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(D(str(r.json()["rop"])), self.sp.rop)
        self.assertIn("ss", r.json())

    def test_chi_tiet_san_pham_hien_thi_ss_rop(self):
        for i in range(40):
            self.ban(i, 3)
        self.tinh()
        self.client.force_login(self.nv)
        r = self.client.get(f"/san-pham/?xem={self.sp.pk}")
        for chu in ("Nhu cầu TB/ngày (d)", "Độ lệch chuẩn nhu cầu (σd)", "Lead time (LT)", "Tồn kho an toàn (SS)",
                    "Điểm đặt hàng lại (ROP)", "Ngày tính"):
            self.assertContains(r, chu)


class DashboardGiaoDienTest(Base):
    """Dashboard giao diện mới: menu dọc bên trái, Danh sách cảnh báo nằm trước Biến động kho & Lịch hết hạn."""

    def test_dashboard_moi(self):
        self.nhap(10, 20000, hsd=timezone.localdate() - timedelta(days=2))
        for user, la_admin in ((self.admin, True), (self.nv, False)):
            self.client.force_login(user)
            for url in ("/", "/?tab=het_han", "/?tab=can_dat", "/?tab=tat_ca&page=2"):
                r = self.client.get(url)
                self.assertEqual(r.status_code, 200, url)
                html = r.content.decode()
                self.assertLess(html.index("Danh sách cảnh báo"), html.index("Lịch hết hạn"))
                self.assertLess(html.index("Danh sách cảnh báo"), html.index("Nhập kho</button>") if "Nhập kho</button>" in html else html.index("Lịch hết hạn"))
                self.assertEqual("/ton-kho/tinh-lai-ss-rop/" in html, la_admin)
                self.assertEqual("/tai-khoan/" in html, la_admin)          # menu dọc theo quyền
            r = self.client.get("/?tab=het_han")
            self.assertEqual(len(r.context["page"]), 1)
        self.assertEqual(self.client.get("/dashboard/mau-1/").status_code, 404)  # đã bỏ trang mẫu
