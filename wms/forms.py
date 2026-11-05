from django import forms
from django.contrib.auth.password_validation import validate_password

from .models import DanhMuc, NguoiDung, NhaCungCap, SanPham

REQUIRED = "Vui lòng không bỏ trống"
UNIQUE = "Đã tồn tại trong hệ thống"


class BaseForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for f in self.fields.values():
            f.error_messages.setdefault("required", REQUIRED)
            f.error_messages["required"] = REQUIRED
            f.error_messages["unique"] = UNIQUE
            f.error_messages["invalid"] = f.error_messages.get("invalid", "Giá trị không hợp lệ")

    def validate_unique(self):
        try:
            self.instance.validate_unique(exclude=self._get_validation_exclusions())
        except forms.ValidationError as e:
            for field, errs in e.message_dict.items():
                self.add_error(field if field in self.fields else None, UNIQUE)


class DanhMucForm(BaseForm):
    class Meta:
        model = DanhMuc
        fields = ["ma_danhmuc", "ten_danhmuc", "id_dmcha", "mo_ta", "is_active"]

    def clean(self):
        data = super().clean()
        ten, cha = (data.get("ten_danhmuc") or "").strip(), data.get("id_dmcha")
        if ten:
            dup = DanhMuc.objects.filter(ten_danhmuc__iexact=ten, id_dmcha=cha).exclude(pk=self.instance.pk)
            if dup.exists():
                self.add_error("ten_danhmuc", "Tên danh mục đã tồn tại trong cùng danh mục cha")
        if cha and self.instance.pk:
            node, seen = cha, set()
            while node and node.pk not in seen:
                if node.pk == self.instance.pk:
                    self.add_error("id_dmcha", "Không thể chọn chính nó hoặc danh mục con làm danh mục cha")
                    break
                seen.add(node.pk)
                node = node.id_dmcha
        return data


class SanPhamForm(BaseForm):
    class Meta:
        model = SanPham
        fields = [
            # han_su_dung không nhập tay: = hạn sớm nhất của các lô còn hàng (services.cap_nhat_hsd_san_pham)
            "ma_sp", "ten_sp", "mo_ta", "id_danhmuc", "don_vi", "gia_ban", "nguong_toi_thieu", "so_ngay_canh_bao",
        ]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["id_danhmuc"].queryset = DanhMuc.objects.filter(is_active=True) | DanhMuc.objects.filter(
            pk=getattr(self.instance, "id_danhmuc_id", None)
        )
        self.fields["nguong_toi_thieu"].required = False
        self.fields["so_ngay_canh_bao"].required = False

    def clean_gia_ban(self):
        v = self.cleaned_data["gia_ban"]
        if v is not None and v < 0:
            raise forms.ValidationError("Không nhỏ hơn 0")
        return v

    def clean_nguong_toi_thieu(self):
        v = self.cleaned_data.get("nguong_toi_thieu") or 0
        if v < 0:
            raise forms.ValidationError("Không nhỏ hơn 0")
        return v

    def clean_so_ngay_canh_bao(self):
        v = self.cleaned_data.get("so_ngay_canh_bao")
        if v is None:
            return 30
        if v < 0:
            raise forms.ValidationError("Không nhỏ hơn 0")
        return v


class NhaCungCapForm(BaseForm):
    class Meta:
        model = NhaCungCap
        fields = ["ma_ncc", "ten_ncc", "so_dien_thoai", "email", "dia_chi", "trang_thai"]

    def clean_so_dien_thoai(self):
        v = "".join(ch for ch in self.cleaned_data["so_dien_thoai"] if ch.isdigit() or ch == "+")
        if len(v) < 9 or len(v) > 12:
            raise forms.ValidationError("Số điện thoại không hợp lệ")
        return self.cleaned_data["so_dien_thoai"].strip()


class NguoiDungForm(BaseForm):
    mat_khau = forms.CharField(required=False, widget=forms.PasswordInput)

    class Meta:
        model = NguoiDung
        fields = ["ma_nv", "ho_ten", "vai_tro", "email", "ten_dang_nhap"]

    def clean_mat_khau(self):
        pw = self.cleaned_data.get("mat_khau")
        if not self.instance.pk and not pw:
            raise forms.ValidationError(REQUIRED)
        if pw:
            try:
                validate_password(pw)
            except forms.ValidationError:
                raise forms.ValidationError("Mật khẩu tối thiểu 6 ký tự")
        return pw

    def save(self, commit=True):
        user = super().save(commit=False)
        if self.cleaned_data.get("mat_khau"):
            user.set_password(self.cleaned_data["mat_khau"])
        if commit:
            user.save()
        return user
