import os
import re
import secrets
import unicodedata
import mimetypes
from datetime import datetime
from functools import wraps
from pathlib import Path

from flask import Flask, abort, flash, redirect, render_template, request, session, url_for
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename
from sqlalchemy.pool import NullPool
import requests

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_DIR = BASE_DIR / 'static' / 'uploads'
if not os.getenv('VERCEL'):
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'change-this-secret-key')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = str(UPLOAD_DIR)
app.config['ALLOWED_IMAGE_EXTENSIONS'] = {'png', 'jpg', 'jpeg', 'webp'}
app.config['SUPABASE_URL'] = os.getenv('SUPABASE_URL', '').rstrip('/')
app.config['SUPABASE_SECRET_KEY'] = os.getenv('SUPABASE_SECRET_KEY') or os.getenv('SUPABASE_SERVICE_ROLE_KEY', '')
app.config['SUPABASE_STORAGE_BUCKET'] = os.getenv('SUPABASE_STORAGE_BUCKET', 'product-images')
app.config['ADMIN_USERNAME'] = os.getenv('ADMIN_USERNAME', 'admin')
app.config['ADMIN_PASSWORD'] = os.getenv('ADMIN_PASSWORD', 'admin123')
app.config['AUTO_CREATE_DB'] = os.getenv('AUTO_CREATE_DB', '0') == '1'

database_url = os.getenv('DATABASE_URL', f"sqlite:///{BASE_DIR / 'fanweb.db'}")
if database_url.startswith('postgres://'):
    database_url = 'postgresql+psycopg://' + database_url[len('postgres://'):]
elif database_url.startswith('postgresql://'):
    database_url = 'postgresql+psycopg://' + database_url[len('postgresql://'):]

engine_options = {}
if database_url.startswith('postgresql+psycopg://'):
    engine_options.update({
        'poolclass': NullPool,
        'connect_args': {'sslmode': os.getenv('DB_SSLMODE', 'require')},
    })
app.config['SQLALCHEMY_DATABASE_URI'] = database_url
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = engine_options

db = SQLAlchemy(app)

_schema_ready = False

def ensure_production_schema():
    global _schema_ready
    if _schema_ready:
        return
    try:
        # Idempotent bootstrap for Vercel/Supabase. Safe on every cold start.
        db.create_all()
        # Backfill legacy single-image URLs into the gallery table.
        for product in Product.query.all():
            if product.image_url and not product.images:
                db.session.add(ProductImage(product=product, image_url=product.image_url, sort_order=0, is_cover=True))

        # Seed the initial admin/products only when the FANWEB tables are empty.
        if not db.session.execute(db.select(Admin).filter_by(username=app.config['ADMIN_USERNAME'])).scalar_one_or_none():
            admin = Admin(username=app.config['ADMIN_USERNAME'])
            admin.set_password(app.config['ADMIN_PASSWORD'])
            db.session.add(admin)
        if Product.query.count() == 0:
            samples = [
                Product(sku='FP-CB-100', name='Quạt ly tâm cao áp FP-CB 100', slug='quat-ly-tam-cao-ap-fp-cb-100', category='Quạt ly tâm cao áp', short_description='Dòng quạt nhỏ gọn cho tủ điện, máy sấy và hệ thống hút bụi.', description='Thiết kế cánh cong tối ưu lưu lượng và áp suất, phù hợp các hệ thống cần luồng khí ổn định.', airflow='1.200–2.800 m³/h', pressure='800–1.600 Pa', motor='2.2 kW', voltage='380V / 3P', speed='2.900 rpm', featured=True),
                Product(sku='FP-CB-200', name='Quạt ly tâm công nghiệp FP-CB 200', slug='quat-ly-tam-cong-nghiep-fp-cb-200', category='Quạt ly tâm', short_description='Phù hợp xưởng sản xuất, hút mùi và cấp khí.', description='Kết cấu chắc chắn, dễ bảo trì và có thể tùy chỉnh động cơ theo yêu cầu.', airflow='2.500–5.500 m³/h', pressure='900–1.900 Pa', motor='3.0–4.0 kW', voltage='380V / 3P', speed='2.900 rpm', featured=True),
                Product(sku='FP-TB-250', name='Quạt hướng trục FP-TB 250', slug='quat-huong-truc-fp-tb-250', category='Quạt hướng trục', short_description='Giải pháp thông gió nhà xưởng và làm mát cục bộ.', description='Thiết kế hướng trục cho lưu lượng lớn, tiếng ồn tối ưu theo cấu hình cánh.', airflow='4.000–8.000 m³/h', pressure='250–650 Pa', motor='1.5–2.2 kW', voltage='380V / 3P', speed='1.450 rpm', featured=False),
                Product(sku='FP-BL-315', name='Quạt thổi khí công suất lớn FP-BL 315', slug='quat-thoi-khi-cong-suat-lon-fp-bl-315', category='Quạt thổi khí', short_description='Dùng cho cấp khí, đẩy bụi và các hệ thống đường ống công nghiệp.', description='Khung vỏ thép sơn công nghiệp, cân bằng động rotor và tùy chọn truyền động trực tiếp hoặc dây đai.', airflow='6.500–12.000 m³/h', pressure='1.200–2.600 Pa', motor='5.5–7.5 kW', voltage='380V / 3P', speed='1.450 rpm', featured=True),
            ]
            db.session.add_all(samples)
        db.session.commit()
        _schema_ready = True
    except Exception:
        db.session.rollback()
        raise



@app.before_request
def bootstrap_on_vercel():
    if os.getenv('VERCEL'):
        ensure_production_schema()

def slugify(text: str) -> str:
    value = (text or '').strip().lower()
    # Keep product URLs ASCII-only so browsers, sharing and SEO are predictable.
    value = unicodedata.normalize('NFKD', value)
    value = ''.join(ch for ch in value if not unicodedata.combining(ch))
    value = value.replace('đ', 'd').replace('ð', 'd')
    value = re.sub(r'[^a-z0-9\s-]', '', value)
    value = re.sub(r'[-\s]+', '-', value).strip('-')
    return value or secrets.token_hex(4)


class Admin(db.Model):
    __tablename__ = 'fanweb_admin'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Product(db.Model):
    __tablename__ = 'fanweb_product'
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(80), unique=True, nullable=False)
    name = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(220), unique=True, nullable=False)
    category = db.Column(db.String(120), default='Quạt ly tâm')
    short_description = db.Column(db.String(500), default='')
    description = db.Column(db.Text, default='')
    airflow = db.Column(db.String(120), default='')
    pressure = db.Column(db.String(120), default='')
    motor = db.Column(db.String(120), default='')
    voltage = db.Column(db.String(120), default='')
    speed = db.Column(db.String(120), default='')
    image_url = db.Column(db.String(500), default='')
    featured = db.Column(db.Boolean, default=False)
    active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    images = db.relationship(
        'ProductImage',
        back_populates='product',
        cascade='all, delete-orphan',
        order_by='ProductImage.sort_order.asc(), ProductImage.id.asc()'
    )


class ProductImage(db.Model):
    __tablename__ = 'fanweb_product_image'
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('fanweb_product.id', ondelete='CASCADE'), nullable=False, index=True)
    image_url = db.Column(db.String(700), nullable=False)
    sort_order = db.Column(db.Integer, default=0, nullable=False)
    is_cover = db.Column(db.Boolean, default=False, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    product = db.relationship('Product', back_populates='images')


class Inquiry(db.Model):
    __tablename__ = 'fanweb_inquiry'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(50), nullable=False)
    email = db.Column(db.String(160), default='')
    product = db.Column(db.String(200), default='')
    message = db.Column(db.Text, default='')
    status = db.Column(db.String(30), default='new')
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


@app.context_processor
def inject_globals():
    return {
        'site_name': 'FANPRO INDUSTRIAL',
        'is_admin': bool(session.get('admin_id')),
        'current_year': datetime.now().year,
    }


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get('admin_id'):
            return redirect(url_for('admin_login', next=request.path))
        return view(*args, **kwargs)
    return wrapped


def allowed_image(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_IMAGE_EXTENSIONS']


def save_uploads(file_storages):
    urls = []
    for file_storage in (file_storages or []):
        if file_storage and file_storage.filename:
            urls.append(save_upload(file_storage))
    return urls


def save_upload(file_storage):
    if not file_storage or not file_storage.filename:
        return ''
    if not allowed_image(file_storage.filename):
        raise ValueError('Định dạng ảnh không được hỗ trợ. Dùng PNG, JPG, JPEG hoặc WEBP.')

    # Vercel filesystem is ephemeral, so production uploads go to Supabase Storage.
    if app.config['SUPABASE_URL'] and app.config['SUPABASE_SECRET_KEY']:
        ext = file_storage.filename.rsplit('.', 1)[1].lower()
        object_name = f"products/{secrets.token_hex(8)}.{ext}"
        bucket = app.config['SUPABASE_STORAGE_BUCKET']
        content_type = file_storage.mimetype or mimetypes.guess_type(file_storage.filename)[0] or 'application/octet-stream'
        data = file_storage.read()
        endpoint = f"{app.config['SUPABASE_URL']}/storage/v1/object/{bucket}/{object_name}"
        resp = requests.post(
            endpoint,
            headers={
                'Authorization': f"Bearer {app.config['SUPABASE_SECRET_KEY']}",
                'apikey': app.config['SUPABASE_SECRET_KEY'],
                'Content-Type': content_type,
                'x-upsert': 'true',
                'Cache-Control': '31536000',
            },
            data=data,
            timeout=30,
        )
        if resp.status_code >= 400:
            raise ValueError(f'Supabase Storage upload lỗi: {resp.text[:300]}')
        return f"{app.config['SUPABASE_URL']}/storage/v1/object/public/{bucket}/{object_name}"

    # Local development fallback only.
    ext = file_storage.filename.rsplit('.', 1)[1].lower()
    filename = f"{secrets.token_hex(8)}.{ext}"
    target = UPLOAD_DIR / secure_filename(filename)
    file_storage.save(target)
    return url_for('static', filename=f'uploads/{filename}')


@app.route('/')
def home():
    featured = Product.query.filter_by(active=True, featured=True).order_by(Product.id.desc()).limit(4).all()
    latest = Product.query.filter_by(active=True).order_by(Product.id.desc()).limit(6).all()
    return render_template('home.html', featured=featured, latest=latest)


@app.route('/gioi-thieu')
def about():
    return render_template('about.html')


@app.route('/san-pham')
def products():
    q = request.args.get('q', '').strip()
    category = request.args.get('category', '').strip()
    query = Product.query.filter_by(active=True)
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(Product.name.ilike(like), Product.sku.ilike(like), Product.short_description.ilike(like)))
    if category:
        query = query.filter_by(category=category)
    items = query.order_by(Product.featured.desc(), Product.id.desc()).all()
    categories = [row[0] for row in db.session.query(Product.category).filter(Product.active.is_(True)).distinct().order_by(Product.category).all()]
    return render_template('products.html', products=items, categories=categories, q=q, category=category)


@app.route('/san-pham/<path:slug>')
def product_detail(slug):
    product = Product.query.filter_by(slug=slug, active=True).first()
    if not product:
        # Backward compatibility for old Vietnamese/Unicode slugs.
        target = slugify(slug)
        for candidate in Product.query.filter_by(active=True).all():
            if slugify(candidate.slug) == target or slugify(candidate.name) == target:
                product = candidate
                canonical = url_for('product_detail', slug=slugify(candidate.name))
                if request.path != canonical:
                    return redirect(canonical, code=301)
                break
    if not product:
        abort(404)
    related = Product.query.filter(Product.active.is_(True), Product.category == product.category, Product.id != product.id).limit(3).all()
    return render_template('product_detail.html', product=product, related=related)


@app.route('/lien-he', methods=['GET', 'POST'])
def contact():
    prefill_product = request.args.get('product', '')
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip()
        email = request.form.get('email', '').strip()
        product = request.form.get('product', '').strip()
        message = request.form.get('message', '').strip()
        if not name or not phone:
            flash('Vui lòng nhập họ tên và số điện thoại.', 'error')
            return render_template('contact.html', prefill_product=product)
        db.session.add(Inquiry(name=name, phone=phone, email=email, product=product, message=message))
        db.session.commit()
        flash('Đã gửi yêu cầu. Bộ phận tư vấn sẽ liên hệ với bạn sớm.', 'success')
        return redirect(url_for('contact'))
    return render_template('contact.html', prefill_product=prefill_product)


@app.get('/health')
def health():
    try:
        row = db.session.execute(db.text(
            "select current_database() as db, current_schema() as schema, "
            "to_regclass('public.fanweb_admin') as admin_table, "
            "to_regclass('public.fanweb_product') as product_table, "
            "to_regclass('public.fanweb_inquiry') as inquiry_table, "
            "to_regclass('public.fanweb_product_image') as image_table"
        )).mappings().one()
        return {
            'status': 'ok',
            'database': row['db'],
            'schema': row['schema'],
            'fanweb_tables': {
                'admin': row['admin_table'],
                'product': row['product_table'],
                'inquiry': row['inquiry_table'],
                'images': row['image_table']
            }
        }, 200
    except Exception as exc:
        db.session.rollback()
        return {'status': 'error', 'database': 'unavailable', 'detail': str(exc)[:300]}, 503


@app.route('/admin/dang-nhap', methods=['GET', 'POST'])
def admin_login():
    if session.get('admin_id'):
        return redirect(url_for('admin_dashboard'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        admin = Admin.query.filter_by(username=username).first()
        if not admin and username == app.config['ADMIN_USERNAME'] and secrets.compare_digest(password, app.config['ADMIN_PASSWORD']):
            admin = Admin(username=username)
            admin.set_password(password)
            db.session.add(admin)
            db.session.commit()
        if admin and admin.check_password(password):
            session.clear()
            session['admin_id'] = admin.id
            session['admin_username'] = admin.username
            return redirect(request.args.get('next') or url_for('admin_dashboard'))
        flash('Tên đăng nhập hoặc mật khẩu không đúng.', 'error')
    return render_template('admin/login.html')


@app.route('/admin/dang-xuat')
def admin_logout():
    session.clear()
    return redirect(url_for('home'))


@app.route('/admin')
@admin_required
def admin_dashboard():
    stats = {
        'products': Product.query.count(),
        'active_products': Product.query.filter_by(active=True).count(),
        'featured': Product.query.filter_by(featured=True, active=True).count(),
        'new_inquiries': Inquiry.query.filter_by(status='new').count(),
    }
    recent = Inquiry.query.order_by(Inquiry.id.desc()).limit(6).all()
    return render_template('admin/dashboard.html', stats=stats, recent=recent)


@app.route('/admin/san-pham')
@admin_required
def admin_products():
    q = request.args.get('q', '').strip()
    query = Product.query
    if q:
        like = f'%{q}%'
        query = query.filter(db.or_(Product.name.ilike(like), Product.sku.ilike(like)))
    items = query.order_by(Product.id.desc()).all()
    return render_template('admin/products.html', products=items, q=q)


@app.route('/admin/san-pham/them', methods=['GET', 'POST'])
@admin_required
def admin_product_add():
    if request.method == 'POST':
        try:
            product = Product(
                sku=request.form.get('sku', '').strip(),
                name=request.form.get('name', '').strip(),
                slug=slugify(request.form.get('name', '')),
                category=request.form.get('category', '').strip() or 'Quạt ly tâm',
                short_description=request.form.get('short_description', '').strip(),
                description=request.form.get('description', '').strip(),
                airflow=request.form.get('airflow', '').strip(),
                pressure=request.form.get('pressure', '').strip(),
                motor=request.form.get('motor', '').strip(),
                voltage=request.form.get('voltage', '').strip(),
                speed=request.form.get('speed', '').strip(),
                image_url=request.form.get('image_url', '').strip(),
                featured=request.form.get('featured') == 'on',
                active=request.form.get('active') == 'on',
            )
            image_files = request.files.getlist('image_files')
            if not product.sku or not product.name:
                raise ValueError('SKU và tên sản phẩm là bắt buộc.')
            db.session.add(product)
            db.session.flush()
            cover_url = request.form.get('image_url', '').strip()
            urls = save_uploads(image_files)
            if cover_url:
                urls.insert(0, cover_url)
            for index, image_url in enumerate(urls):
                db.session.add(ProductImage(product_id=product.id, image_url=image_url, sort_order=index, is_cover=(index == 0)))
            if urls:
                product.image_url = urls[0]
            db.session.commit()
            flash('Đã thêm sản phẩm.', 'success')
            return redirect(url_for('admin_products'))
        except Exception as exc:
            db.session.rollback()
            flash(f'Không thể thêm sản phẩm: {exc}', 'error')
    return render_template('admin/product_form.html', product=None, title='Thêm sản phẩm')


@app.route('/admin/san-pham/<int:product_id>/sua', methods=['GET', 'POST'])
@admin_required
def admin_product_edit(product_id):
    product = Product.query.get_or_404(product_id)
    if request.method == 'POST':
        try:
            product.sku = request.form.get('sku', '').strip()
            product.name = request.form.get('name', '').strip()
            new_slug = slugify(request.form.get('name', ''))
            clash = Product.query.filter(Product.slug == new_slug, Product.id != product.id).first()
            product.slug = f"{new_slug}-{product.id}" if clash else new_slug
            product.category = request.form.get('category', '').strip() or 'Quạt ly tâm'
            product.short_description = request.form.get('short_description', '').strip()
            product.description = request.form.get('description', '').strip()
            product.airflow = request.form.get('airflow', '').strip()
            product.pressure = request.form.get('pressure', '').strip()
            product.motor = request.form.get('motor', '').strip()
            product.voltage = request.form.get('voltage', '').strip()
            product.speed = request.form.get('speed', '').strip()
            product.image_url = request.form.get('image_url', '').strip() or product.image_url
            product.featured = request.form.get('featured') == 'on'
            product.active = request.form.get('active') == 'on'
            image_files = request.files.getlist('image_files')
            if not product.sku or not product.name:
                raise ValueError('SKU và tên sản phẩm là bắt buộc.')
            urls = save_uploads(image_files)
            if urls:
                start_order = max([img.sort_order for img in product.images], default=-1) + 1
                for offset, image_url in enumerate(urls):
                    db.session.add(ProductImage(
                        product_id=product.id,
                        image_url=image_url,
                        sort_order=start_order + offset,
                        is_cover=False
                    ))
                if not product.image_url:
                    product.image_url = urls[0]
            db.session.commit()
            flash('Đã cập nhật sản phẩm.', 'success')
            return redirect(url_for('admin_products'))
        except Exception as exc:
            db.session.rollback()
            flash(f'Không thể cập nhật: {exc}', 'error')
    return render_template('admin/product_form.html', product=product, title='Chỉnh sửa sản phẩm')


@app.post('/admin/san-pham/<int:product_id>/anh/<int:image_id>/cover')
@admin_required
def admin_product_image_cover(product_id, image_id):
    product = Product.query.get_or_404(product_id)
    image = ProductImage.query.filter_by(id=image_id, product_id=product.id).first_or_404()
    for item in product.images:
        item.is_cover = (item.id == image.id)
    product.image_url = image.image_url
    db.session.commit()
    flash('Đã chọn ảnh đại diện.', 'success')
    return redirect(url_for('admin_product_edit', product_id=product.id))


@app.post('/admin/san-pham/<int:product_id>/anh/<int:image_id>/xoa')
@admin_required
def admin_product_image_delete(product_id, image_id):
    product = Product.query.get_or_404(product_id)
    image = ProductImage.query.filter_by(id=image_id, product_id=product.id).first_or_404()
    was_cover = image.is_cover or product.image_url == image.image_url
    db.session.delete(image)
    db.session.flush()
    remaining = ProductImage.query.filter_by(product_id=product.id).order_by(ProductImage.sort_order.asc(), ProductImage.id.asc()).all()
    if was_cover:
        for index, item in enumerate(remaining):
            item.sort_order = index
            item.is_cover = (index == 0)
        product.image_url = remaining[0].image_url if remaining else ''
    db.session.commit()
    flash('Đã xóa ảnh sản phẩm.', 'success')
    return redirect(url_for('admin_product_edit', product_id=product.id))


@app.post('/admin/san-pham/<int:product_id>/xoa')
@admin_required
def admin_product_delete(product_id):
    product = Product.query.get_or_404(product_id)
    db.session.delete(product)
    db.session.commit()
    flash('Đã xóa sản phẩm.', 'success')
    return redirect(url_for('admin_products'))


@app.route('/admin/yeu-cau')
@admin_required
def admin_inquiries():
    inquiries = Inquiry.query.order_by(Inquiry.id.desc()).all()
    return render_template('admin/inquiries.html', inquiries=inquiries)


@app.post('/admin/yeu-cau/<int:inquiry_id>/trang-thai')
@admin_required
def admin_inquiry_status(inquiry_id):
    inquiry = Inquiry.query.get_or_404(inquiry_id)
    inquiry.status = request.form.get('status', 'new')
    db.session.commit()
    flash('Đã cập nhật trạng thái yêu cầu.', 'success')
    return redirect(url_for('admin_inquiries'))


def initialize_data():
    if app.config['AUTO_CREATE_DB']:
        db.create_all()
    if not db.session.execute(db.select(Admin).filter_by(username=app.config['ADMIN_USERNAME'])).scalar_one_or_none():
        admin = Admin(username=app.config['ADMIN_USERNAME'])
        admin.set_password(app.config['ADMIN_PASSWORD'])
        db.session.add(admin)
    if Product.query.count() == 0:
        samples = [
            Product(sku='FP-CB-100', name='Quạt ly tâm cao áp FP-CB 100', slug='quat-ly-tam-cao-ap-fp-cb-100', category='Quạt ly tâm cao áp', short_description='Dòng quạt nhỏ gọn cho tủ điện, máy sấy và hệ thống hút bụi.', description='Thiết kế cánh cong tối ưu lưu lượng và áp suất, phù hợp các hệ thống cần luồng khí ổn định.', airflow='1.200–2.800 m³/h', pressure='800–1.600 Pa', motor='2.2 kW', voltage='380V / 3P', speed='2.900 rpm', featured=True),
            Product(sku='FP-CB-200', name='Quạt ly tâm công nghiệp FP-CB 200', slug='quat-ly-tam-cong-nghiep-fp-cb-200', category='Quạt ly tâm', short_description='Phù hợp xưởng sản xuất, hút mùi và cấp khí.', description='Kết cấu chắc chắn, dễ bảo trì và có thể tùy chỉnh động cơ theo yêu cầu.', airflow='2.500–5.500 m³/h', pressure='900–1.900 Pa', motor='3.0–4.0 kW', voltage='380V / 3P', speed='2.900 rpm', featured=True),
            Product(sku='FP-TB-250', name='Quạt hướng trục FP-TB 250', slug='quat-huong-truc-fp-tb-250', category='Quạt hướng trục', short_description='Giải pháp thông gió nhà xưởng và làm mát cục bộ.', description='Thiết kế hướng trục cho lưu lượng lớn, tiếng ồn tối ưu theo cấu hình cánh.', airflow='4.000–8.000 m³/h', pressure='250–650 Pa', motor='1.5–2.2 kW', voltage='380V / 3P', speed='1.450 rpm', featured=False),
            Product(sku='FP-BL-315', name='Quạt thổi khí công suất lớn FP-BL 315', slug='quat-thoi-khi-cong-suat-lon-fp-bl-315', category='Quạt thổi khí', short_description='Dùng cho cấp khí, đẩy bụi và các hệ thống đường ống công nghiệp.', description='Khung vỏ thép sơn công nghiệp, cân bằng động rotor và tùy chọn truyền động trực tiếp hoặc dây đai.', airflow='6.500–12.000 m³/h', pressure='1.200–2.600 Pa', motor='5.5–7.5 kW', voltage='380V / 3P', speed='1.450 rpm', featured=True),
        ]
        db.session.add_all(samples)
    db.session.commit()
    print('Database initialized. Admin: admin / admin123')


@app.cli.command('init-db')
def init_db_command():
    db.create_all()
    initialize_data()
    print('Database initialized.')


@app.cli.command('seed')
def seed_command():
    initialize_data()
    db.session.commit()
    print('Seed completed.')


app.config['SESSION_COOKIE_SECURE'] = os.getenv('SESSION_COOKIE_SECURE', '1' if os.getenv('VERCEL') else '0') == '1'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'

# Local development bootstrap only. Vercel bootstraps lazily in before_request.
if not os.getenv('VERCEL') and app.config['AUTO_CREATE_DB']:
    with app.app_context():
        initialize_data()
        db.session.commit()


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 5000)), debug=os.getenv('FLASK_DEBUG', '1') == '1')
