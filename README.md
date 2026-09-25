# FANWEB INDUSTRIAL

Website giới thiệu quạt thổi khí công nghiệp bằng Flask, thiết kế để chạy local hoặc deploy trên Vercel và dùng Supabase PostgreSQL + Storage.

## Kiến trúc production

- Frontend + Flask routes: Vercel Python Functions
- Source code: GitHub
- Database: Supabase PostgreSQL
- Product images: Supabase Storage (`product-images`)
- Admin: session login trong Flask

Vercel dùng filesystem tạm thời, vì vậy không lưu SQLite hoặc ảnh upload local trong production. Database URL nên dùng Supabase transaction pooler (port 6543) và SQLAlchemy `NullPool` cho môi trường serverless.

## Setup local

```bash
python -m venv .venv
.venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
set AUTO_CREATE_DB=1  # Windows CMD
# export AUTO_CREATE_DB=1  # macOS/Linux
python app.py
```

Mặc định local dùng SQLite nếu không có `DATABASE_URL`.

## Setup Supabase

1. Mở Supabase SQL Editor.
2. Chạy toàn bộ `supabase_schema.sql`.
3. Vào Dashboard > Connect và lấy **Transaction pooler** connection string.
4. Tạo bucket `product-images` (file SQL đã tạo bucket).
5. Lấy Secret Key / service_role key để đặt vào Vercel Environment Variables. Chỉ dùng key này ở server-side, không đưa vào JavaScript/browser.

## Vercel Environment Variables

Bắt buộc:

- `SECRET_KEY`
- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`
- `DATABASE_URL`
- `DB_SSLMODE=require`
- `SUPABASE_URL`
- `SUPABASE_SECRET_KEY`
- `SUPABASE_STORAGE_BUCKET=product-images`

## Vercel

Project này dùng `api/index.py` làm Flask entrypoint. Chỉ cần import repository GitHub `sadaorile/fanweb` vào Vercel và đặt Environment Variables.

## Admin

Đường dẫn: `/admin/dang-nhap`

Tài khoản initial được tạo từ `ADMIN_USERNAME` / `ADMIN_PASSWORD` nếu bảng `admin` đang trống. Hãy đổi mật khẩu mạnh trước production.
