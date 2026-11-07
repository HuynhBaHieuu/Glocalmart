from django.urls import path

from .views import auth, baocao, catalog, dashboard, kiemke, nhap, taikhoan, tonkho, xuat

urlpatterns = [
    path("login/", auth.login_view, name="login"),
    path("logout/", auth.logout_view, name="logout"),
    path("", dashboard.dashboard, name="dashboard"),
    path("canh-bao/xuat-excel/", dashboard.dashboard_export, name="dashboard_export"),
    path("ton-kho/tinh-lai-ss-rop/", tonkho.tinh_lai_ss_rop, name="tinh_lai_ss_rop"),
    path("ton-kho/cau-hinh/", tonkho.cau_hinh_ton_kho, name="cau_hinh_ton_kho"),

    # danh mục
    path("danh-muc/", catalog.danh_muc_list, name="danh_muc"),
    path("danh-muc/luu/", catalog.danh_muc_save, name="danh_muc_save"),
    path("danh-muc/<int:pk>/xoa/", catalog.danh_muc_delete, name="danh_muc_delete"),

    # sản phẩm
    path("san-pham/", catalog.san_pham_list, name="san_pham"),
    path("san-pham/luu/", catalog.san_pham_save, name="san_pham_save"),
    path("san-pham/xuat-excel/", catalog.san_pham_export, name="san_pham_export"),
    path("san-pham/<int:pk>/trang-thai/", catalog.san_pham_toggle, name="san_pham_toggle"),
    path("san-pham/<int:pk>/xoa/", catalog.san_pham_delete, name="san_pham_delete"),

    # nhà cung cấp
    path("nha-cung-cap/", catalog.ncc_list, name="ncc"),
    path("nha-cung-cap/luu/", catalog.ncc_save, name="ncc_save"),
    path("nha-cung-cap/xuat-excel/", catalog.ncc_export, name="ncc_export"),
    path("nha-cung-cap/<int:pk>/trang-thai/", catalog.ncc_toggle, name="ncc_toggle"),

    # nhập kho
    path("nhap-kho/", nhap.nhap_list, name="nhap"),
    path("nhap-kho/xuat-excel/", nhap.nhap_export, name="nhap_export"),
    path("nhap-kho/tao/", nhap.nhap_create, name="nhap_create"),
    path("nhap-kho/lo/<int:pk>/sua-han/", nhap.nhap_sua_han_lo, name="nhap_sua_han_lo"),
    path("nhap-kho/<str:ma>/", nhap.nhap_detail, name="nhap_detail"),
    path("nhap-kho/<str:ma>/giao-hang/", nhap.nhap_giao_hang, name="nhap_giao_hang"),
    path("nhap-kho/<str:ma>/doi-soat/", nhap.nhap_doi_soat, name="nhap_doi_soat"),
    path("nhap-kho/<str:ma>/in/", nhap.nhap_print, name="nhap_print"),
    path("nhap-kho/<str:ma>/huy/", nhap.nhap_cancel, name="nhap_cancel"),
    path("nhap-kho/<str:ma>/xoa/", nhap.nhap_delete, name="nhap_delete"),

    # xuất kho
    path("xuat-kho/", xuat.xuat_list, name="xuat"),
    path("xuat-kho/tao/", xuat.xuat_form, name="xuat_create"),
    path("xuat-kho/<str:ma>/", xuat.xuat_detail, name="xuat_detail"),
    path("xuat-kho/<str:ma>/sua/", xuat.xuat_form, name="xuat_edit"),
    path("xuat-kho/<str:ma>/xac-nhan/", xuat.xuat_confirm, name="xuat_confirm"),
    path("xuat-kho/<str:ma>/in/", xuat.xuat_print, name="xuat_print"),
    path("xuat-kho/<str:ma>/huy/", xuat.xuat_cancel, name="xuat_cancel"),
    path("xuat-kho/<str:ma>/xoa/", xuat.xuat_delete, name="xuat_delete"),

    # kiểm kê
    path("kiem-ke/", kiemke.kiem_list, name="kiem"),
    path("kiem-ke/tao/", kiemke.kiem_create, name="kiem_create"),
    path("kiem-ke/<str:ma>/", kiemke.kiem_detail, name="kiem_detail"),
    path("kiem-ke/<str:ma>/dem/", kiemke.kiem_dem, name="kiem_dem"),
    path("kiem-ke/<str:ma>/gui-duyet/", kiemke.kiem_gui_duyet, name="kiem_gui_duyet"),
    path("kiem-ke/<str:ma>/duyet/", kiemke.kiem_duyet, name="kiem_duyet"),
    path("kiem-ke/<str:ma>/tu-choi/", kiemke.kiem_tu_choi, name="kiem_tu_choi"),
    path("kiem-ke/<str:ma>/dem-lai/", kiemke.kiem_dem_lai, name="kiem_dem_lai"),
    path("kiem-ke/<str:ma>/huy/", kiemke.kiem_huy, name="kiem_huy"),
    path("kiem-ke/<str:ma>/xoa/", kiemke.kiem_xoa, name="kiem_xoa"),

    # báo cáo
    path("bao-cao/", baocao.bao_cao, name="bao_cao"),
    path("bao-cao/xuat/", baocao.bao_cao_export, name="bao_cao_export"),

    # tài khoản
    path("tai-khoan/", taikhoan.tai_khoan_list, name="tai_khoan"),
    path("tai-khoan/luu/", taikhoan.tai_khoan_save, name="tai_khoan_save"),
    path("tai-khoan/xuat-excel/", taikhoan.tai_khoan_export, name="tai_khoan_export"),
    path("tai-khoan/<int:pk>/khoa/", taikhoan.tai_khoan_lock, name="tai_khoan_lock"),
    path("tai-khoan/<int:pk>/kich-hoat/", taikhoan.tai_khoan_active, name="tai_khoan_active"),
    path("tai-khoan/api-key/", taikhoan.api_keys, name="api_keys"),
    path("tai-khoan/api-key/<int:pk>/thu-hoi/", taikhoan.api_key_revoke, name="api_key_revoke"),
    path("tai-khoan/nhat-ky/", taikhoan.audit_logs, name="audit_logs"),
    path("doi-mat-khau/", taikhoan.doi_mat_khau, name="doi_mat_khau"),
]
