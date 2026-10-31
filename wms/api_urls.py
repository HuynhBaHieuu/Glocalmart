from django.urls import path

from . import api

urlpatterns = [
    path("san-pham/", api.SanPhamList.as_view(), name="api_san_pham"),
    path("san-pham/<str:ma_sp>/", api.SanPhamDetail.as_view(), name="api_san_pham_detail"),
    path("danh-muc/", api.DanhMucList.as_view(), name="api_danh_muc"),
    path("ton-kho/<str:ma_sp>/", api.ton_kho, name="api_ton_kho"),
]
