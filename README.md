# G'Local Mart & Cafe — Hệ thống Quản lý kho (WMS)

Website quản lý kho và chuỗi cung ứng cho cửa hàng G'Local Mart & Cafe: Nhập – Xuất – Tồn, kiểm kê mù 2 bước,
cảnh báo tồn kho / hạn sử dụng thời gian thực, báo cáo Excel/PDF, phân quyền và REST API.

**Công nghệ:** Python 3.12 · Django 5.1 · Django REST Framework · PostgreSQL (Supabase) · Tailwind CSS + Alpine.js ·
openpyxl (Excel) · ReportLab (PDF) · Deploy trên Vercel.

## Tài khoản demo

| Vai trò | Username | Mật khẩu |
|---|---|---|
| Quản trị viên | `admin` | `Admin@123` |
| Quản trị viên | `quanly` | `Admin@123` |
| Nhân viên | `nvkho_002` … `nvkho_005` | `Nhanvien@123` |
| Nhân viên (đang bị khóa) | `nvkho_006` | `Nhanvien@123` |

## Chức năng theo đặc tả

| Phân hệ | Đã cài đặt |
|---|---|
| Đăng nhập & phân quyền | Đăng nhập username/mật khẩu (hash), khóa tự động sau 5 lần sai, reset bộ đếm khi đúng, Admin mở khóa / vô hiệu hóa mềm, không tự đăng ký. Nhân viên bị ẩn & chặn mọi thao tác xóa. |
| Danh mục | Cây cha – con, tên không trùng trong cùng cha, danh mục đang hoạt động chỉ xóa được khi trống; Admin xóa được danh mục đã ngừng hoạt động (SP chuyển sang danh mục cha hoặc “Chưa phân loại”), không cho chọn chính nó làm cha. |
| Sản phẩm | Mã SP duy nhất, giá vốn bình quân tự tính, tồn kho chỉ đọc, ngưỡng tối thiểu, HSD chỉ hiển thị (= hạn sớm nhất của các lô còn hàng) + số ngày cảnh báo, danh sách lô theo thứ tự FEFO trong drawer, ảnh (Supabase Storage), xóa → tự chuyển Ngừng bán nếu đã có giao dịch, xuất Excel. |
| Nhà cung cấp | CRUD, ngừng hoạt động (xóa mềm), xuất Excel. |
| Nhập kho | Tạo phiếu (xem trước trước khi lưu) → Chờ giao → Đang giao → Đối soát (SL thực nhận, **HSD nhập tay từng lô**, “+ Lô” khi cùng SP giao về 2 hạn, lý do chênh lệch tính theo tổng SP, lô cận hạn/hết hạn phải xác nhận lại kèm lý do) → Đã giao: mỗi dòng thành 1 **lô** (`so_luong_con_lai`), cộng tồn, giá vốn bình quân. “Sửa hạn lô” sau khi nhập (bắt buộc lý do, ghi nhật ký kho). Hủy phiếu đã xác nhận chỉ khi lô chưa bị xuất bớt. In phiếu có cột HSD. |
| Xuất kho | Lý do Bán hàng / Hủy hàng / Điều chỉnh, kiểm tra tồn thời gian thực (khóa dòng `SELECT … FOR UPDATE`), chặn xuất âm. Khi xác nhận: trừ theo **FEFO** (hạn tăng dần, không hạn xếp cuối, cùng hạn thì lô nhập trước), ghi phân bổ lô; không đủ → rollback “Không đủ hàng trong các lô”. Lô hết hạn chỉ xuất được với Hủy hàng. Hủy phiếu đã xác nhận trả hàng về đúng lô đã lấy. |
| Kiểm kê | Tối đa 30 SP/phiếu, đếm mù lần 1 (ẩn tồn hệ thống), gắn cờ & đếm lần 2 dòng lệch, gửi duyệt (phần **thừa** phải nhập tay HSD), Quản lý xem chênh lệch + giá trị thất thoát → Duyệt: thiếu trừ theo FEFO, thừa tạo lô mới `PN-KK-…` / Từ chối / Xóa. Danh sách chỉ hiện phiếu đã gửi duyệt. |
| Báo cáo & cảnh báo | Dashboard: Hết hàng / Dưới mức an toàn (tồn ≤ SS) / Cần đặt hàng (tồn ≤ ROP) / Đã hết hạn / Sắp hết hạn, 2 biểu đồ tròn. Bảng tồn kho: Tồn, SS, ROP, Gợi ý đặt + “Tạo phiếu nhập” điền sẵn số lượng gợi ý. Cảnh báo hạn **theo lô** + “Tạo phiếu xuất”; Admin xuất Excel từng tab. Báo cáo N-X-T (bỏ qua nhật ký sửa hạn) theo thời gian / danh mục / sản phẩm, xuất Excel & PDF (chỉ Admin). |
| Tồn kho an toàn & ROP | SS = Z·σd·√LT, ROP = d·LT + SS từ lịch sử bán 90 ngày và lead time 5 phiếu nhập gần nhất; lưu sẵn vào sản phẩm, tính hằng ngày bằng `python manage.py tinh_ss_rop` hoặc nút “Tính lại SS/ROP” (Admin). Trang Cấu hình SS/ROP (mức phục vụ, số ngày dữ liệu, lead time mặc định, chu kỳ đặt hàng) chỉ Admin. Chưa đủ 30 ngày bán → “Chưa đủ dữ liệu”, ROP = ngưỡng tối thiểu. API sản phẩm trả thêm `ss`, `rop`. |
| REST API | `GET /api/san-pham/`, `/api/san-pham/<ma_sp>/`, `/api/ton-kho/<ma_sp>/`, `/api/danh-muc/` — header `X-API-Key`. Admin tạo / thu hồi key trong *Quản lý tài khoản → REST API Key*. |
| Nguyên tắc chung | Mã chứng từ `PREFIX-YYMM-####` reset theo tháng, mọi thay đổi tồn qua `post_stock_move()` và ghi `nhat_ky_kho`, mọi thao tác ghi lưu `audit_log`, chứng từ đã xác nhận chỉ được Hủy kèm lý do (hoàn tồn tự động). |

Khác biệt so với tech stack gốc (do chạy serverless trên Vercel): không dùng Celery/Redis — cảnh báo được tính
thời gian thực mỗi lần mở trang; PDF dùng ReportLab thay cho WeasyPrint (WeasyPrint cần thư viện hệ thống).

## Cấu trúc

```
config/            settings, urls, wsgi (entry cho Vercel)
wms/models.py      ERD: nguoi_dung, danh_muc, san_pham, nha_cung_cap, phieu_nhap/xuat/kiem_ke + chi tiết, nhat_ky_kho, audit_log, api_key, doc_sequence
wms/services.py    nghiệp vụ: next_doc_code, post_stock_move, xác nhận nhập/xuất, đếm/duyệt kiểm kê, lô FEFO (tru_ton_fefo, sua_han_lo, canh_bao_han_su_dung), tinh_ss_rop
wms/lo.py          chuyển tồn kho cũ sang lô (migration 0003, lệnh `kiem_tra_lo`)
wms/views/         dashboard, catalog, nhap, xuat, kiemke, baocao, taikhoan, auth
wms/api*.py        REST API + xác thực API Key
wms/tests.py       59 test cho các quy tắc nghiệp vụ
templates/         giao diện theo Figma
```

## Chạy local

```bash
python -m venv .venv && .venv\Scripts\activate      # Windows
pip install -r requirements.txt
python manage.py migrate          # không có DATABASE_URL → dùng SQLite
python manage.py seed_demo        # tạo dữ liệu demo (thêm --reset để tạo lại)
python manage.py runserver
python manage.py test wms         # chạy kiểm thử
python manage.py tinh_ss_rop       # tính SS/ROP (nên chạy hằng ngày)
```

## Deploy: Supabase + Vercel

### 1. Supabase (database)
1. Tạo project tại https://supabase.com — **Region: West EU (Ireland)** (trùng region `dub1` của Vercel trong `vercel.json` để truy vấn nhanh; nếu đổi region Supabase thì đổi `regions` tương ứng).
2. Bấm nút **Connect** trên thanh trên cùng → tab *Connection String* → Method: **Transaction pooler** (cổng `6543`), thay `[YOUR-PASSWORD]`.
   Không dùng *Direct connection* vì chỉ có IPv6, Vercel không kết nối được.
3. Tạo bảng và dữ liệu demo từ máy local:
   ```bash
   set DATABASE_URL=postgresql://postgres.xxxx:MATKHAU@aws-0-eu-west-1.pooler.supabase.com:6543/postgres
   python manage.py migrate
   python manage.py seed_demo
   ```
4. (Tùy chọn, để upload ảnh sản phẩm) *Storage* → tạo bucket **public** tên `products`; lấy `service_role` key ở *Project Settings → API*.

### 2. Vercel
1. Đẩy code lên GitHub, vào https://vercel.com/new → Import repository (Framework Preset: **Other**).
2. *Environment Variables*:
   - `SECRET_KEY` — chuỗi ngẫu nhiên dài
   - `DATABASE_URL` — chuỗi Transaction pooler ở trên
   - (tùy chọn) `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`, `SUPABASE_BUCKET=products`
3. Deploy. `vercel.json` đã cấu hình build Python và region `dub1`.

Nếu dùng tên miền riêng, thêm vào `ALLOWED_HOSTS` và `CSRF_TRUSTED_ORIGINS` (phân tách bằng dấu phẩy).
