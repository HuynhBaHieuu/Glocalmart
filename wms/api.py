"""REST API cho hệ thống bên ngoài (Client App) — xác thực bằng header X-API-Key."""
from django.db.models import Q
from django.utils import timezone
from rest_framework import generics, serializers
from rest_framework.decorators import api_view
from rest_framework.response import Response

from .api_auth import ApiKeyAuthentication, tao_api_key  # noqa: F401
from .models import DanhMuc, SanPham


class DanhMucSerializer(serializers.ModelSerializer):
    danh_muc_cha = serializers.CharField(source="id_dmcha.ma_danhmuc", default=None)
    so_san_pham = serializers.IntegerField(read_only=True)

    class Meta:
        model = DanhMuc
        fields = ["ma_danhmuc", "ten_danhmuc", "danh_muc_cha", "mo_ta", "so_san_pham"]


class SanPhamSerializer(serializers.ModelSerializer):
    danh_muc = serializers.CharField(source="id_danhmuc.ten_danhmuc")
    ma_danh_muc = serializers.CharField(source="id_danhmuc.ma_danhmuc")
    trang_thai = serializers.SerializerMethodField()
    canh_bao_ton = serializers.CharField(source="muc_ton")
    canh_bao_han = serializers.CharField(source="muc_han")

    class Meta:
        model = SanPham
        fields = [
            "ma_sp", "ten_sp", "mo_ta", "ma_danh_muc", "danh_muc", "don_vi", "gia_ban", "ton_kho",
            "nguong_toi_thieu", "han_su_dung", "anh_sp", "trang_thai", "canh_bao_ton", "canh_bao_han",
        ]

    def get_trang_thai(self, obj):
        return "DANG_BAN" if obj.trang_thai == 1 else "NGUNG_BAN"


class SanPhamList(generics.ListAPIView):
    """GET /api/san-pham/?ma=SP-0001&danh_muc=DM001&q=sữa"""

    serializer_class = SanPhamSerializer

    def get_queryset(self):
        qs = SanPham.objects.select_related("id_danhmuc")
        p = self.request.query_params
        if p.get("ma"):
            qs = qs.filter(ma_sp__iexact=p["ma"])
        if p.get("danh_muc"):
            dm = p["danh_muc"]
            qs = qs.filter(Q(id_danhmuc__ma_danhmuc__iexact=dm) | Q(id_danhmuc__id_dmcha__ma_danhmuc__iexact=dm))
        if p.get("q"):
            qs = qs.filter(Q(ten_sp__icontains=p["q"]) | Q(ma_sp__icontains=p["q"]))
        if p.get("trang_thai") == "DANG_BAN":
            qs = qs.filter(trang_thai=1)
        return qs


class SanPhamDetail(generics.RetrieveAPIView):
    """GET /api/san-pham/<ma_sp>/"""

    serializer_class = SanPhamSerializer
    lookup_field = "ma_sp"
    queryset = SanPham.objects.select_related("id_danhmuc")


class DanhMucList(generics.ListAPIView):
    serializer_class = DanhMucSerializer
    pagination_class = None

    def get_queryset(self):
        from django.db.models import Count

        return DanhMuc.objects.filter(is_active=True).select_related("id_dmcha").annotate(so_san_pham=Count("san_pham"))


@api_view(["GET"])
def ton_kho(request, ma_sp):
    """GET /api/ton-kho/<ma_sp>/ — tra cứu nhanh tồn kho thời gian thực."""
    sp = SanPham.objects.filter(ma_sp__iexact=ma_sp).first()
    if not sp:
        return Response({"detail": "Không tìm thấy sản phẩm."}, status=404)
    return Response({
        "ma_sp": sp.ma_sp,
        "ten_sp": sp.ten_sp,
        "don_vi": sp.don_vi,
        "ton_kho": sp.ton_kho,
        "canh_bao_ton": sp.muc_ton,
        "thoi_diem": timezone.now(),
    })
