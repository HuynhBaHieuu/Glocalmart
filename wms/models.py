"""Mô hình dữ liệu theo ERD trong đặc tả G'Local Mart & Cafe WMS.

Quy ước: số lượng NUMERIC(14,3) theo đơn vị gốc, tiền NUMERIC(16,0) VND.
"""
from decimal import Decimal

from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.utils import timezone

QTY = dict(max_digits=14, decimal_places=3)
MONEY = dict(max_digits=16, decimal_places=0)


# ---------------------------------------------------------------- NGUOI_DUNG
class NguoiDungManager(BaseUserManager):
    def create_user(self, ten_dang_nhap, password=None, **extra):
        if not ten_dang_nhap:
            raise ValueError("Thiếu tên đăng nhập")
        user = self.model(ten_dang_nhap=ten_dang_nhap, **extra)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, ten_dang_nhap, password=None, **extra):
        extra.setdefault("vai_tro", NguoiDung.ADMIN)
        extra.setdefault("ho_ten", "Quản trị viên")
        extra.setdefault("ma_nv", "AD001")
        extra.setdefault("email", f"{ten_dang_nhap}@glocal.vn")
        return self.create_user(ten_dang_nhap, password, **extra)


class NguoiDung(AbstractBaseUser):
    ADMIN = "ADMIN"
    NHAN_VIEN = "NHAN_VIEN"
    VAI_TRO = [(ADMIN, "Quản trị viên"), (NHAN_VIEN, "Nhân viên")]
    MAX_SAI = 5

    id_nv = models.AutoField(primary_key=True)
    ma_nv = models.CharField("Mã NV", max_length=20, unique=True)
    ten_dang_nhap = models.CharField("Tên đăng nhập", max_length=50, unique=True)
    password = models.CharField("Mật khẩu", max_length=128, db_column="mat_khau_hash")
    ho_ten = models.CharField("Họ và tên", max_length=100)
    email = models.EmailField(unique=True)
    vai_tro = models.CharField(max_length=20, choices=VAI_TRO, default=NHAN_VIEN)
    is_active = models.BooleanField(default=True)
    so_lan_sai = models.IntegerField(default=0)
    is_locked = models.BooleanField(default=False)
    ngay_tao = models.DateTimeField(auto_now_add=True)
    ngay_cap_nhat = models.DateTimeField(auto_now=True)

    objects = NguoiDungManager()
    USERNAME_FIELD = "ten_dang_nhap"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        db_table = "nguoi_dung"
        ordering = ["id_nv"]

    def __str__(self):
        return self.ho_ten

    @property
    def is_admin(self):
        return self.vai_tro == self.ADMIN

    @property
    def initials(self):
        parts = [p for p in self.ho_ten.split() if p]
        if not parts:
            return "?"
        if len(parts) == 1:
            return parts[0][:2].upper()
        return (parts[-1][0] + parts[0][0] + (parts[1][0] if len(parts) > 2 else "")).upper()[:3]


# ---------------------------------------------------------------- DANH_MUC
class DanhMuc(models.Model):
    id_danhmuc = models.AutoField(primary_key=True)
    ma_danhmuc = models.CharField("Mã danh mục", max_length=20, unique=True)
    ten_danhmuc = models.CharField("Tên danh mục", max_length=100)
    id_dmcha = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="con", db_column="id_dmcha",
        verbose_name="Danh mục cha",
    )
    mo_ta = models.CharField("Mô tả", max_length=255, blank=True, default="")
    is_active = models.BooleanField(default=True)
    ngay_tao = models.DateTimeField(auto_now_add=True)
    ngay_cap_nhat = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "danh_muc"
        ordering = ["ma_danhmuc"]

    def __str__(self):
        return self.ten_danhmuc

    @property
    def duong_dan(self):
        names, node, seen = [], self, set()
        while node and node.pk not in seen:
            seen.add(node.pk)
            names.append(node.ten_danhmuc)
            node = node.id_dmcha
        return " › ".join(reversed(names))


# ---------------------------------------------------------------- SAN_PHAM
class SanPham(models.Model):
    DANG_HOAT_DONG = 1
    NGUNG_HOAT_DONG = 0

    id_sp = models.AutoField(primary_key=True)
    ma_sp = models.CharField("Mã SP", max_length=30, unique=True)
    ten_sp = models.CharField("Tên sản phẩm", max_length=200)
    mo_ta = models.CharField("Mô tả ngắn", max_length=255, blank=True, default="")
    id_danhmuc = models.ForeignKey(DanhMuc, on_delete=models.PROTECT, related_name="san_pham", db_column="id_danhmuc",
                                   verbose_name="Danh mục")
    don_vi = models.CharField("Đơn vị tính", max_length=30)
    gia_ban = models.DecimalField("Giá bán", **MONEY, default=0)
    gia_von = models.DecimalField("Giá vốn", **MONEY, default=0)
    ton_kho = models.DecimalField("Tồn kho", **QTY, default=0)
    nguong_toi_thieu = models.DecimalField("Ngưỡng tối thiểu", **QTY, default=0)
    # Không nhập tay: = hạn sớm nhất của các lô còn hàng (services.cap_nhat_hsd_san_pham)
    han_su_dung = models.DateField("Hạn sử dụng", null=True, blank=True)
    so_ngay_canh_bao = models.IntegerField("Số ngày cảnh báo", default=30)
    anh_sp = models.CharField("Ảnh", max_length=500, null=True, blank=True)
    # ---- tồn kho an toàn (SS) & điểm đặt hàng lại (ROP): tính bởi services.tinh_ss_rop, KHÔNG tính khi mở trang
    ss = models.DecimalField("Tồn kho an toàn (SS)", **QTY, null=True, blank=True)
    rop = models.DecimalField("Điểm đặt hàng lại (ROP)", **QTY, null=True, blank=True)
    ngay_tinh_rop = models.DateTimeField("Ngày tính SS/ROP", null=True, blank=True)
    nhu_cau_tb = models.DecimalField("Nhu cầu TB/ngày (d)", max_digits=14, decimal_places=4, null=True, blank=True)
    do_lech_nhu_cau = models.DecimalField("Độ lệch chuẩn nhu cầu (σd)", max_digits=14, decimal_places=4, null=True,
                                          blank=True)
    lead_time = models.DecimalField("Lead time (ngày)", max_digits=8, decimal_places=2, null=True, blank=True)
    du_du_lieu_ss = models.BooleanField("Đủ dữ liệu tính SS", default=False)
    trang_thai = models.IntegerField(default=DANG_HOAT_DONG, choices=[(1, "Đang bán"), (0, "Ngừng bán")])
    ngay_tao = models.DateTimeField(auto_now_add=True)
    ngay_cap_nhat = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "san_pham"
        ordering = ["ma_sp"]

    def __str__(self):
        return f"{self.ma_sp} - {self.ten_sp}"

    # ---- cảnh báo tồn kho theo SS / ROP
    @property
    def rop_ap_dung(self):
        """ROP dùng để cảnh báo; chưa tính lần nào thì tạm dùng ngưỡng tối thiểu."""
        return self.rop if self.rop is not None else self.nguong_toi_thieu

    @property
    def muc_ton(self):
        """ton = 0 → Hết hàng · 0 < ton ≤ SS → Dưới mức an toàn · SS < ton ≤ ROP → Cần đặt hàng · còn lại an toàn."""
        if self.ton_kho <= 0:
            return "HET_HANG"
        if self.ss is not None and self.ton_kho <= self.ss:
            return "DUOI_AN_TOAN"
        if self.ton_kho <= self.rop_ap_dung:
            return "CAN_DAT_HANG"
        return "AN_TOAN"

    def goi_y_dat(self, chu_ky_dat_hang):
        """Gợi ý đặt = max(0, d·(LT + chu kỳ đặt hàng) + SS − tồn), làm tròn lên.
        Chưa có nhu cầu bán (d = 0 / chưa tính): đặt cho đủ ROP."""
        import math
        d, lt = self.nhu_cau_tb or 0, self.lead_time or 0
        if d > 0 and lt > 0:
            can = d * (lt + chu_ky_dat_hang) + (self.ss or 0) - self.ton_kho
        else:
            can = self.rop_ap_dung - self.ton_kho
        return max(0, math.ceil(can))

    # ---- cảnh báo hạn sử dụng
    @property
    def so_ngay_con_lai(self):
        if not self.han_su_dung:
            return None
        return (self.han_su_dung - timezone.localdate()).days

    @property
    def muc_han(self):
        d = self.so_ngay_con_lai
        if d is None:
            return None
        if d < 0:
            return "DA_HET_HAN"
        if d <= self.so_ngay_canh_bao:
            return "SAP_HET_HAN"
        return "CON_HAN"

    @property
    def da_het_han(self):
        return self.muc_han == "DA_HET_HAN"

    def lo_con_hang(self):
        """Các lô còn hàng, theo thứ tự FEFO (hạn tăng dần, không hạn xếp cuối, cùng hạn thì nhập trước)."""
        return thu_tu_fefo(ChiTietPhieuNhap.objects.filter(id_sp=self, ma_phieu_nhap__trang_thai=PhieuNhap.DA_XAC_NHAN,
                                                           so_luong_con_lai__gt=0))

    @property
    def ton_con_han(self):
        """Số lượng thuộc các lô chưa hết hạn (được phép bán / điều chỉnh)."""
        hom_nay = timezone.localdate()
        return sum((lo.so_luong_con_lai for lo in self.lo_con_hang()
                    if lo.han_su_dung is None or lo.han_su_dung >= hom_nay), Decimal(0))

    @property
    def co_giao_dich(self):
        return (
            self.ct_nhap.exists() or self.ct_xuat.exists() or self.ct_kiem.exists() or self.nhat_ky.exists()
        )


# ---------------------------------------------------------------- CAU_HINH_TON_KHO
class CauHinhTonKho(models.Model):
    """Tham số tính SS / ROP — chỉ có 1 bản ghi (pk = 1), chỉ Admin được sửa."""
    muc_phuc_vu = models.DecimalField("Mức phục vụ", max_digits=5, decimal_places=4, default=Decimal("0.95"))
    so_ngay_du_lieu = models.PositiveIntegerField("Số ngày dữ liệu bán hàng", default=90)
    lead_time_mac_dinh = models.PositiveIntegerField("Lead time mặc định (ngày)", default=7)
    chu_ky_dat_hang = models.PositiveIntegerField("Chu kỳ đặt hàng (ngày)", default=14)
    nguoi_cap_nhat = models.ForeignKey("NguoiDung", null=True, blank=True, on_delete=models.SET_NULL)
    ngay_cap_nhat = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "cau_hinh_ton_kho"

    @classmethod
    def lay(cls):
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


# ---------------------------------------------------------------- NHA_CUNG_CAP
class NhaCungCap(models.Model):
    id_ncc = models.AutoField(primary_key=True)
    ma_ncc = models.CharField("Mã NCC", max_length=20, unique=True)
    ten_ncc = models.CharField("Tên nhà cung cấp", max_length=200)
    so_dien_thoai = models.CharField("Số điện thoại", max_length=20)
    email = models.EmailField(null=True, blank=True)
    dia_chi = models.CharField("Địa chỉ", max_length=255)
    trang_thai = models.IntegerField(default=1, choices=[(1, "Đang hoạt động"), (0, "Ngừng hoạt động")])
    ngay_tao = models.DateTimeField(auto_now_add=True)
    ngay_cap_nhat = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "nha_cung_cap"
        ordering = ["ma_ncc"]

    def __str__(self):
        return self.ten_ncc


# ---------------------------------------------------------------- DOC_SEQUENCE
class DocSequence(models.Model):
    """Bộ đếm mã chứng từ PREFIX-YYMM-####, reset mỗi tháng."""

    prefix = models.CharField(max_length=10)
    ky = models.CharField(max_length=4)  # YYMM
    so_cuoi = models.IntegerField(default=0)

    class Meta:
        db_table = "doc_sequence"
        unique_together = [("prefix", "ky")]


# ---------------------------------------------------------------- PHIEU_NHAP
class PhieuNhap(models.Model):
    CHO_GIAO, DANG_GIAO, DA_GIAO = "CHO_GIAO", "DANG_GIAO", "DA_GIAO"
    TRANG_THAI_GIAO = [(CHO_GIAO, "Chờ giao"), (DANG_GIAO, "Đang giao"), (DA_GIAO, "Đã giao")]
    CHUA_XAC_NHAN, DA_XAC_NHAN, DA_HUY = "CHUA_XAC_NHAN", "DA_XAC_NHAN", "DA_HUY"
    TRANG_THAI = [(CHUA_XAC_NHAN, "Chưa xác nhận"), (DA_XAC_NHAN, "Đã xác nhận"), (DA_HUY, "Đã hủy")]
    # Phiếu hệ thống chứa phần tồn kho cũ không thuộc lô nhập nào (xem wms/lo.py)
    MA_TON_DAU = "PN-TONDAU"

    ma_phieu_nhap = models.CharField(max_length=20, primary_key=True)
    id_ncc = models.ForeignKey(NhaCungCap, on_delete=models.PROTECT, related_name="phieu_nhap", db_column="id_ncc")
    nguoi_tao = models.ForeignKey(NguoiDung, on_delete=models.PROTECT, related_name="phieu_nhap_tao")
    ngay_tao = models.DateTimeField(default=timezone.now)
    ngay_du_kien_nhan = models.DateField(null=True, blank=True)
    trang_thai_giao = models.CharField(max_length=20, choices=TRANG_THAI_GIAO, default=CHO_GIAO)
    ngay_cap_nhat_giao = models.DateTimeField(null=True, blank=True)
    trang_thai = models.CharField(max_length=20, choices=TRANG_THAI, default=CHUA_XAC_NHAN)
    nguoi_xac_nhan = models.ForeignKey(NguoiDung, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="phieu_nhap_xac_nhan")
    ngay_xac_nhan = models.DateTimeField(null=True, blank=True)
    ghi_chu = models.TextField(null=True, blank=True)
    ghi_chu_doi_soat = models.TextField(null=True, blank=True)
    ly_do_huy = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "phieu_nhap"
        ordering = ["-ngay_tao"]

    def __str__(self):
        return self.ma_phieu_nhap

    @property
    def la_phieu_he_thong(self):
        """Phiếu do hệ thống tạo: Tồn đầu kỳ, hoặc PN-KK-… chứa lô hàng thừa khi kiểm kê."""
        return self.ma_phieu_nhap == self.MA_TON_DAU or self.ma_phieu_nhap.startswith("PN-KK-")

    @property
    def tong_tien(self):
        return sum((ct.thanh_tien for ct in self.chi_tiet.all()), Decimal(0))

    @property
    def tong_tien_thuc(self):
        return sum((ct.thanh_tien_thuc for ct in self.chi_tiet.all()), Decimal(0))


class ChiTietPhieuNhap(models.Model):
    THIEU_HANG, HU_HONG, GIAO_NHAM = "THIEU_HANG", "HU_HONG", "GIAO_NHAM"
    LY_DO = [(THIEU_HANG, "Thiếu hàng"), (HU_HONG, "Hư hỏng"), (GIAO_NHAM, "Giao nhầm")]

    id_chi_tiet = models.AutoField(primary_key=True)
    ma_phieu_nhap = models.ForeignKey(PhieuNhap, on_delete=models.CASCADE, related_name="chi_tiet",
                                      db_column="ma_phieu_nhap")
    id_sp = models.ForeignKey(SanPham, on_delete=models.PROTECT, related_name="ct_nhap", db_column="id_sp")
    so_luong_dat = models.DecimalField(**QTY)
    don_gia_nhap = models.DecimalField(**MONEY)
    so_luong_thuc_nhan = models.DecimalField(**QTY, null=True, blank=True)
    han_su_dung = models.DateField(null=True, blank=True)
    ly_do_chenh_lech = models.CharField(max_length=20, choices=LY_DO, null=True, blank=True)
    ghi_chu_doi_soat = models.TextField(null=True, blank=True)
    # Mỗi dòng của phiếu đã xác nhận là 1 LÔ; đây là số lượng của lô còn trong kho.
    so_luong_con_lai = models.DecimalField("SL còn lại của lô", **QTY, default=0)

    class Meta:
        db_table = "chi_tiet_phieu_nhap"
        ordering = ["id_chi_tiet"]
        constraints = [
            models.CheckConstraint(condition=models.Q(so_luong_con_lai__gte=0), name="ct_nhap_sl_con_lai_khong_am"),
        ]

    @property
    def thanh_tien(self):
        return self.so_luong_dat * self.don_gia_nhap

    # ---- lô hàng
    @property
    def la_dong_tach(self):
        """Dòng thêm lúc đối soát để nhận cùng sản phẩm với hạn sử dụng khác (không có SL đặt)."""
        return self.so_luong_dat == 0

    @property
    def so_ngay_con_lai(self):
        return None if not self.han_su_dung else (self.han_su_dung - timezone.localdate()).days

    @property
    def muc_han(self):
        d = self.so_ngay_con_lai
        if d is None:
            return None
        if d < 0:
            return "DA_HET_HAN"
        return "SAP_HET_HAN" if d <= self.id_sp.so_ngay_canh_bao else "CON_HAN"

    @property
    def thanh_tien_thuc(self):
        sl = self.so_luong_thuc_nhan if self.so_luong_thuc_nhan is not None else self.so_luong_dat
        return sl * self.don_gia_nhap

    @property
    def chenh_lech(self):
        if self.so_luong_thuc_nhan is None:
            return None
        return self.so_luong_thuc_nhan - self.so_luong_dat


# ---------------------------------------------------------------- PHIEU_XUAT
class PhieuXuat(models.Model):
    BAN_HANG, HUY_HANG, DIEU_CHINH = "BAN_HANG", "HUY_HANG", "DIEU_CHINH"
    LY_DO = [(BAN_HANG, "Bán hàng"), (HUY_HANG, "Hủy hàng (hỏng/hết hạn)"), (DIEU_CHINH, "Điều chỉnh")]
    CHUA_XAC_NHAN, DA_XAC_NHAN, DA_HUY = "CHUA_XAC_NHAN", "DA_XAC_NHAN", "DA_HUY"
    TRANG_THAI = [(CHUA_XAC_NHAN, "Chưa xác nhận"), (DA_XAC_NHAN, "Đã xác nhận"), (DA_HUY, "Đã hủy")]

    ma_phieu_xuat = models.CharField(max_length=20, primary_key=True)
    nguoi_tao = models.ForeignKey(NguoiDung, on_delete=models.PROTECT, related_name="phieu_xuat_tao")
    ngay_tao = models.DateTimeField(default=timezone.now)
    ly_do_xuat = models.CharField(max_length=20, choices=LY_DO)
    trang_thai = models.CharField(max_length=20, choices=TRANG_THAI, default=CHUA_XAC_NHAN)
    nguoi_xac_nhan = models.ForeignKey(NguoiDung, null=True, blank=True, on_delete=models.PROTECT,
                                       related_name="phieu_xuat_xac_nhan")
    ngay_xac_nhan = models.DateTimeField(null=True, blank=True)
    ghi_chu = models.TextField(null=True, blank=True)
    ly_do_huy = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "phieu_xuat"
        ordering = ["-ngay_tao"]

    def __str__(self):
        return self.ma_phieu_xuat

    @property
    def tong_so_luong(self):
        return sum((ct.so_luong_xuat for ct in self.chi_tiet.all()), Decimal(0))

    @property
    def tong_gia_tri(self):
        return sum((ct.so_luong_xuat * ct.id_sp.gia_ban for ct in self.chi_tiet.all()), Decimal(0))


class ChiTietPhieuXuat(models.Model):
    id_chi_tiet = models.AutoField(primary_key=True)
    ma_phieu_xuat = models.ForeignKey(PhieuXuat, on_delete=models.CASCADE, related_name="chi_tiet",
                                      db_column="ma_phieu_xuat")
    id_sp = models.ForeignKey(SanPham, on_delete=models.PROTECT, related_name="ct_xuat", db_column="id_sp")
    so_luong_xuat = models.DecimalField(**QTY)

    class Meta:
        db_table = "chi_tiet_phieu_xuat"
        ordering = ["id_chi_tiet"]


class PhanBoLoXuat(models.Model):
    """Phiếu xuất đã lấy bao nhiêu từ lô nào — để hủy phiếu thì trả về đúng lô."""
    ct_xuat = models.ForeignKey(ChiTietPhieuXuat, on_delete=models.CASCADE, related_name="phan_bo")
    lo = models.ForeignKey(ChiTietPhieuNhap, on_delete=models.PROTECT, related_name="phan_bo_xuat")
    so_luong = models.DecimalField(**QTY)

    class Meta:
        db_table = "phan_bo_lo_xuat"
        ordering = ["id"]


def thu_tu_fefo(qs):
    return qs.order_by(models.F("han_su_dung").asc(nulls_last=True), "ma_phieu_nhap__ngay_xac_nhan",
                       "ma_phieu_nhap__ngay_tao", "id_chi_tiet")


# ---------------------------------------------------------------- PHIEU_KIEM_KE
class PhieuKiemKe(models.Model):
    DANG_KIEM, CHO_DUYET, HOAN_THANH, BI_TU_CHOI, DA_HUY = (
        "DANG_KIEM", "CHO_DUYET", "HOAN_THANH", "BI_TU_CHOI", "DA_HUY",
    )
    TRANG_THAI = [
        (DANG_KIEM, "Đang kiểm"),
        (CHO_DUYET, "Chờ duyệt"),
        (HOAN_THANH, "Hoàn thành"),
        (BI_TU_CHOI, "Từ chối"),
        (DA_HUY, "Đã hủy"),
    ]
    MAX_SAN_PHAM = 30

    ma_phieu_kiem = models.CharField(max_length=20, primary_key=True)
    nguoi_tao = models.ForeignKey(NguoiDung, on_delete=models.PROTECT, related_name="phieu_kiem_tao")
    nguoi_duyet = models.ForeignKey(NguoiDung, null=True, blank=True, on_delete=models.PROTECT,
                                    related_name="phieu_kiem_duyet")
    trang_thai = models.CharField(max_length=20, choices=TRANG_THAI, default=DANG_KIEM)
    ngay_tao = models.DateTimeField(default=timezone.now)
    ngay_gui_duyet = models.DateTimeField(null=True, blank=True)
    ngay_duyet = models.DateTimeField(null=True, blank=True)
    ly_do_tu_choi = models.TextField(null=True, blank=True)
    ghi_chu = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "phieu_kiem_ke"
        ordering = ["-ngay_tao"]

    def __str__(self):
        return self.ma_phieu_kiem

    @property
    def da_dem_lan_1(self):
        return all(ct.sl_dem_lan_1 is not None for ct in self.chi_tiet.all())

    @property
    def can_dem_lan_2(self):
        return any(ct.co_chenh_lech and ct.sl_dem_lan_2 is None for ct in self.chi_tiet.all())

    @property
    def gia_tri_chenh_lech(self):
        return sum((ct.gia_tri_chenh_lech for ct in self.chi_tiet.all()), Decimal(0))


class ChiTietPhieuKiemKe(models.Model):
    id_chi_tiet = models.AutoField(primary_key=True)
    ma_phieu_kiem = models.ForeignKey(PhieuKiemKe, on_delete=models.CASCADE, related_name="chi_tiet",
                                      db_column="ma_phieu_kiem")
    id_sp = models.ForeignKey(SanPham, on_delete=models.PROTECT, related_name="ct_kiem", db_column="id_sp")
    gia_von = models.DecimalField(**MONEY, default=0)
    sl_dem_lan_1 = models.DecimalField(**QTY, null=True, blank=True)
    sl_dem_lan_2 = models.DecimalField(**QTY, null=True, blank=True)
    sl_he_thong = models.DecimalField(**QTY, null=True, blank=True)  # ẩn khi đếm mù
    co_chenh_lech = models.BooleanField(default=False)
    sl_chenh_lech = models.DecimalField(**QTY, default=0)
    don_vi = models.CharField(max_length=30)
    ghi_chu = models.CharField(max_length=255, blank=True, default="")
    hsd_thua_da_khai_bao = models.BooleanField(default=False)
    han_su_dung_thua = models.DateField(null=True, blank=True)  # NULL + đã khai báo = hàng không có HSD

    class Meta:
        db_table = "chi_tiet_phieu_kiem_ke"
        ordering = ["id_chi_tiet"]

    @property
    def sl_dem_thuc_te(self):
        return self.sl_dem_lan_2 if self.sl_dem_lan_2 is not None else self.sl_dem_lan_1

    @property
    def gia_tri_chenh_lech(self):
        return (self.sl_chenh_lech or 0) * (self.gia_von or 0)

    @property
    def sl_thua(self):
        return self.sl_chenh_lech if self.sl_chenh_lech and self.sl_chenh_lech > 0 else 0


# ---------------------------------------------------------------- NHAT_KY_KHO
class NhatKyKho(models.Model):
    NHAP_KHO, XUAT_KHO, KIEM_KE, SUA_HAN_LO = "NHAP_KHO", "XUAT_KHO", "KIEM_KE", "SUA_HAN_LO"
    LOAI = [(NHAP_KHO, "Nhập kho"), (XUAT_KHO, "Xuất kho"), (KIEM_KE, "Kiểm kê"), (SUA_HAN_LO, "Sửa hạn lô")]
    # loại làm thay đổi số lượng — báo cáo N-X-T chỉ tính các loại này
    LOAI_BIEN_DONG = [NHAP_KHO, XUAT_KHO, KIEM_KE]

    id_nhat_ky = models.AutoField(primary_key=True)
    loai_giao_dich = models.CharField(max_length=20, choices=LOAI)
    ma_phieu_kiem = models.ForeignKey(PhieuKiemKe, null=True, blank=True, on_delete=models.PROTECT,
                                      db_column="ma_phieu_kiem", related_name="nhat_ky")
    ma_phieu_xuat = models.ForeignKey(PhieuXuat, null=True, blank=True, on_delete=models.PROTECT,
                                      db_column="ma_phieu_xuat", related_name="nhat_ky")
    ma_phieu_nhap = models.ForeignKey(PhieuNhap, null=True, blank=True, on_delete=models.PROTECT,
                                      db_column="ma_phieu_nhap", related_name="nhat_ky")
    id_sp = models.ForeignKey(SanPham, on_delete=models.PROTECT, related_name="nhat_ky", db_column="id_sp")
    sl_truoc = models.DecimalField(**QTY)
    sl_sau = models.DecimalField(**QTY)
    sl_thay_doi = models.DecimalField(**QTY)
    nguoi_thuc_hien = models.ForeignKey(NguoiDung, on_delete=models.PROTECT, related_name="nhat_ky_kho")
    ngay_tao = models.DateTimeField(default=timezone.now)
    # chỉ dùng cho SUA_HAN_LO
    lo = models.ForeignKey("ChiTietPhieuNhap", null=True, blank=True, on_delete=models.PROTECT, related_name="nhat_ky",
                           db_column="id_lo")
    han_cu = models.DateField(null=True, blank=True)
    han_moi = models.DateField(null=True, blank=True)
    ly_do = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "nhat_ky_kho"
        ordering = ["-ngay_tao", "-id_nhat_ky"]

    @property
    def ma_chung_tu(self):
        return self.ma_phieu_nhap_id or self.ma_phieu_xuat_id or self.ma_phieu_kiem_id


# ---------------------------------------------------------------- AUDIT_LOG & API_KEY
class AuditLog(models.Model):
    nguoi_dung = models.ForeignKey(NguoiDung, null=True, blank=True, on_delete=models.SET_NULL)
    hanh_dong = models.CharField(max_length=30)
    doi_tuong = models.CharField(max_length=50)
    ma_doi_tuong = models.CharField(max_length=50, blank=True, default="")
    chi_tiet = models.TextField(blank=True, default="")
    ip = models.CharField(max_length=64, blank=True, default="")
    ngay_tao = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "audit_log"
        ordering = ["-ngay_tao"]


class ApiKey(models.Model):
    ten = models.CharField("Tên ứng dụng", max_length=100)
    tien_to = models.CharField(max_length=12, unique=True)
    key_hash = models.CharField(max_length=64, unique=True)
    is_active = models.BooleanField(default=True)
    nguoi_tao = models.ForeignKey(NguoiDung, null=True, on_delete=models.SET_NULL)
    ngay_tao = models.DateTimeField(auto_now_add=True)
    lan_dung_cuoi = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "api_key"
        ordering = ["-ngay_tao"]
