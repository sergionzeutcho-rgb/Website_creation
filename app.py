import os
import uuid
import requests
import stripe
import smtplib
from email.message import EmailMessage
from urllib.parse import urlparse
from flask import Flask, render_template, render_template_string, request, jsonify, redirect, url_for, flash, send_from_directory, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_ckeditor import CKEditor
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect, CSRFError
from paypalcheckoutsdk.core import PayPalHttpClient, SandboxEnvironment, LiveEnvironment
from paypalcheckoutsdk.orders import OrdersCreateRequest, OrdersCaptureRequest
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.utils import secure_filename
from datetime import datetime, date, timedelta
from dotenv import load_dotenv

load_dotenv()

def get_bool_env(name, default=False):
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {'1', 'true', 'yes', 'on'}

def send_email(to_email, subject, body, from_email=None, html_body=None):
    smtp_host = app.config.get('SMTP_HOST')
    smtp_port = app.config.get('SMTP_PORT')
    smtp_user = app.config.get('SMTP_USERNAME')
    smtp_pass = app.config.get('SMTP_PASSWORD')
    use_tls = app.config.get('SMTP_USE_TLS')
    sender = from_email or app.config.get('SMTP_FROM')

    if not smtp_host or not sender:
        raise RuntimeError('SMTP is not configured')

    msg = EmailMessage()
    msg['Subject'] = subject
    msg['From'] = sender
    msg['To'] = to_email
    msg.set_content(body or '')
    if html_body:
        msg.add_alternative(html_body, subtype='html')

    with smtplib.SMTP(smtp_host, smtp_port) as server:
        if use_tls:
            server.starttls()
        if smtp_user and smtp_pass:
            server.login(smtp_user, smtp_pass)
        server.send_message(msg)

def build_order_confirmation_body(order):
    currency_symbol = CURRENCY_SYMBOLS.get(order.currency or app.config['DEFAULT_CURRENCY'], '£')
    lines = [
        'Thank you for your order with Atelier Gourmand by OC!',
        '',
        f'Order number: {order.order_number}',
        f'Pickup date: {order.pickup_date}',
        f'Pickup time: {order.pickup_time}',
        '',
        'Items:'
    ]
    for item in order.items:
        line_total = item.total_price
        lines.append(f"- {item.product_name} x{item.quantity} ({currency_symbol}{line_total:.2f})")
    lines.extend([
        '',
        f'Total: {currency_symbol}{order.total:.2f}',
        '',
        f"Special instructions: {order.notes or 'None'}",
        '',
        'We look forward to welcoming you.'
    ])
    return '\n'.join(lines)


def build_order_confirmation_html(order):
    settings = SiteSettings.query.first()
    currency_symbol = CURRENCY_SYMBOLS.get(order.currency or app.config['DEFAULT_CURRENCY'], '£')
    return render_template(
        'emails/order_confirmation.html',
        order=order,
        settings=settings,
        currency_symbol=currency_symbol,
    )


def build_invoice_html(order):
    settings = SiteSettings.query.first()
    currency_symbol = CURRENCY_SYMBOLS.get(order.currency or app.config['DEFAULT_CURRENCY'], '£')
    invoice_number = order.order_number
    invoice_date = order.created_at.date()
    return render_invoice_template(order, settings, currency_symbol, invoice_number, invoice_date, for_email=True)


def build_order_number(settings=None):
    prefix = os.getenv('ORDER_PREFIX', 'ORD').strip() or 'ORD'
    date_fmt = os.getenv('ORDER_DATE_FMT', '%Y%m%d').strip() or '%Y%m%d'
    separator = os.getenv('ORDER_SEPARATOR', '-').strip() or '-'
    pad = int(os.getenv('ORDER_SEQ_PAD', '3') or 3)

    today = datetime.utcnow().date()
    start = datetime.combine(today, datetime.min.time())
    end = datetime.combine(today, datetime.max.time())
    daily_count = Order.query.filter(Order.created_at >= start, Order.created_at <= end).count() + 1

    date_part = datetime.utcnow().strftime(date_fmt)
    seq_part = str(daily_count).zfill(pad)
    return f"{prefix}{separator}{date_part}{separator}{seq_part}"


def render_invoice_template(order, settings, currency_symbol, invoice_number, invoice_date, for_email=False):
    template_html = None
    if settings and settings.invoice_template_path:
        fs_path = os.path.join(app.root_path, settings.invoice_template_path.lstrip('/'))
        if os.path.exists(fs_path):
            with open(fs_path, 'r', encoding='utf-8') as f:
                template_html = f.read()

    context = {
        'order': order,
        'settings': settings,
        'currency_symbol': currency_symbol,
        'invoice_number': invoice_number,
        'invoice_date': invoice_date,
    }

    if template_html:
        # Allow custom uploaded template with same context as defaults
        return render_template_string(template_html, **context)

    return render_template(
        'emails/invoice.html' if for_email else 'admin/order_invoice.html',
        **context,
    )

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)

secret_key = os.getenv('SECRET_KEY')
if not secret_key:
    if os.getenv('FLASK_ENV') == 'production':
        raise RuntimeError('SECRET_KEY must be set in production')
    secret_key = 'dev-secret-key-change-in-production'

app.config['SECRET_KEY'] = secret_key
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///atelier.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', 'static/uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size
app.config['SESSION_COOKIE_SECURE'] = get_bool_env(
    'SESSION_COOKIE_SECURE', os.getenv('FLASK_ENV') == 'production'
)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = os.getenv('SESSION_COOKIE_SAMESITE', 'Lax')
app.config['REMEMBER_COOKIE_SECURE'] = get_bool_env(
    'REMEMBER_COOKIE_SECURE', os.getenv('FLASK_ENV') == 'production'
)
app.config['REMEMBER_COOKIE_HTTPONLY'] = True
app.config['REMEMBER_COOKIE_SAMESITE'] = os.getenv('REMEMBER_COOKIE_SAMESITE', 'Lax')
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=8)
app.config['PREFERRED_URL_SCHEME'] = os.getenv('PREFERRED_URL_SCHEME', 'https')
app.config['WTF_CSRF_TIME_LIMIT'] = 3600
app.config['STRIPE_PUBLIC_KEY'] = os.getenv('STRIPE_PUBLIC_KEY')
app.config['STRIPE_SECRET_KEY'] = os.getenv('STRIPE_SECRET_KEY')
app.config['STRIPE_WEBHOOK_SECRET'] = os.getenv('STRIPE_WEBHOOK_SECRET')
app.config['PAYPAL_CLIENT_ID'] = os.getenv('PAYPAL_CLIENT_ID')
app.config['PAYPAL_CLIENT_SECRET'] = os.getenv('PAYPAL_CLIENT_SECRET')
app.config['PAYPAL_WEBHOOK_ID'] = os.getenv('PAYPAL_WEBHOOK_ID')
app.config['PAYPAL_MODE'] = os.getenv('PAYPAL_MODE', 'sandbox')
app.config['PAYMENT_BASE_URL'] = os.getenv('PAYMENT_BASE_URL')
app.config['PAYMENT_SUCCESS_PATH'] = os.getenv('PAYMENT_SUCCESS_PATH', '/payment/success')
app.config['PAYMENT_CANCEL_PATH'] = os.getenv('PAYMENT_CANCEL_PATH', '/payment/cancel')
app.config['DEFAULT_CURRENCY'] = os.getenv('DEFAULT_CURRENCY', 'GBP').upper()
app.config['BASE_CURRENCY'] = os.getenv('BASE_CURRENCY', 'GBP').upper()
app.config['AUTO_CURRENCY_BY_IP'] = get_bool_env('AUTO_CURRENCY_BY_IP', True)
app.config['CURRENCY_RATES'] = os.getenv('CURRENCY_RATES', '')
app.config['GEOIP_COUNTRY_HEADER'] = os.getenv('GEOIP_COUNTRY_HEADER')
app.config['SMTP_HOST'] = os.getenv('SMTP_HOST')
app.config['SMTP_PORT'] = int(os.getenv('SMTP_PORT', '587'))
app.config['SMTP_USERNAME'] = os.getenv('SMTP_USERNAME')
app.config['SMTP_PASSWORD'] = os.getenv('SMTP_PASSWORD')
app.config['SMTP_USE_TLS'] = get_bool_env('SMTP_USE_TLS', True)
app.config['SMTP_FROM'] = os.getenv('SMTP_FROM')

# Allowed extensions for uploads
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'mp4', 'mov', 'avi'}
TEMPLATE_EXTENSIONS = {'html', 'htm'}

CURRENCY_SYMBOLS = {
    'GBP': '£',
    'EUR': '€',
    'USD': '$',
    'CAD': 'C$',
}

COUNTRY_TO_CURRENCY = {
    'GB': 'GBP',
    'UK': 'GBP',
    'IE': 'EUR',
    'FR': 'EUR',
    'DE': 'EUR',
    'ES': 'EUR',
    'IT': 'EUR',
    'NL': 'EUR',
    'BE': 'EUR',
    'LU': 'EUR',
    'US': 'USD',
    'CA': 'CAD',
}

# Import db from models and initialize with app
from models import (db, User, Customer, Product, ProductVariant, ProductImage, HeroSection, MaisonSection, 
                    Booking, SiteSettings, AvailableTimeSlot, BlockedDate, BlockedTimeSlot, BookingSettings,
                    Cart, CartItem, Order, OrderItem, NavigationItem, Discount, DeliveryZone)

db.init_app(app)
ckeditor = CKEditor(app)
csrf = CSRFProtect(app)
limiter = Limiter(get_remote_address, app=app, default_limits=[])

login_manager = LoginManager(app)
login_manager.login_view = 'admin_login'
login_manager.session_protection = 'strong'

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'products'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'hero'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'maison'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'invoices'), exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def allowed_template_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in TEMPLATE_EXTENSIONS

def build_base_url():
    if app.config['PAYMENT_BASE_URL']:
        return app.config['PAYMENT_BASE_URL'].rstrip('/')
    return request.url_root.rstrip('/')

def parse_currency_rates(raw_rates):
    rates = {}
    if not raw_rates:
        return rates
    for pair in raw_rates.split(','):
        if ':' not in pair:
            continue
        code, value = pair.split(':', 1)
        code = code.strip().upper()
        try:
            rates[code] = float(value.strip())
        except ValueError:
            continue
    return rates

def get_country_code():
    header_name = app.config.get('GEOIP_COUNTRY_HEADER')
    if header_name:
        country = request.headers.get(header_name)
        if country:
            return country.upper()
    for name in ['CF-IPCountry', 'X-Appengine-Country', 'X-Country-Code']:
        country = request.headers.get(name)
        if country:
            return country.upper()
    return None

def get_order_currency():
    if app.config['AUTO_CURRENCY_BY_IP']:
        country = get_country_code()
        if country and country in COUNTRY_TO_CURRENCY:
            return COUNTRY_TO_CURRENCY[country]
    return app.config['DEFAULT_CURRENCY']

def get_currency_rate(base_currency, target_currency):
    if base_currency == target_currency:
        return 1.0
    rates = parse_currency_rates(app.config['CURRENCY_RATES'])
    return rates.get(target_currency)

def convert_amount(amount, rate):
    return round(amount * rate, 2)


def get_current_customer():
    customer_id = session.get('customer_id')
    if not customer_id:
        return None
    return Customer.query.get(customer_id)

def get_paypal_environment():
    mode = app.config['PAYPAL_MODE'].lower()
    if mode == 'live':
        return LiveEnvironment(
            client_id=app.config['PAYPAL_CLIENT_ID'],
            client_secret=app.config['PAYPAL_CLIENT_SECRET']
        )
    return SandboxEnvironment(
        client_id=app.config['PAYPAL_CLIENT_ID'],
        client_secret=app.config['PAYPAL_CLIENT_SECRET']
    )

def get_paypal_client():
    return PayPalHttpClient(get_paypal_environment())

def get_paypal_api_base():
    return 'https://api-m.paypal.com' if app.config['PAYPAL_MODE'].lower() == 'live' else 'https://api-m.sandbox.paypal.com'

def get_paypal_access_token():
    response = requests.post(
        f"{get_paypal_api_base()}/v1/oauth2/token",
        auth=(app.config['PAYPAL_CLIENT_ID'], app.config['PAYPAL_CLIENT_SECRET']),
        data={'grant_type': 'client_credentials'},
        timeout=15
    )
    response.raise_for_status()
    return response.json().get('access_token')

def verify_paypal_webhook(event, headers):
    webhook_id = app.config.get('PAYPAL_WEBHOOK_ID')
    if not webhook_id:
        return False
    token = get_paypal_access_token()
    payload = {
        'auth_algo': headers.get('PAYPAL-AUTH-ALGO'),
        'cert_url': headers.get('PAYPAL-CERT-URL'),
        'transmission_id': headers.get('PAYPAL-TRANSMISSION-ID'),
        'transmission_sig': headers.get('PAYPAL-TRANSMISSION-SIG'),
        'transmission_time': headers.get('PAYPAL-TRANSMISSION-TIME'),
        'webhook_id': webhook_id,
        'event': event,
    }
    response = requests.post(
        f"{get_paypal_api_base()}/v1/notifications/verify-webhook-signature",
        headers={'Authorization': f"Bearer {token}", 'Content-Type': 'application/json'},
        json=payload,
        timeout=15
    )
    response.raise_for_status()
    return response.json().get('verification_status') == 'SUCCESS'

def get_or_create_cart():
    """Get existing cart or create new one for session"""
    if 'cart_id' not in session:
        # Create new cart
        session_id = str(uuid.uuid4())
        cart = Cart(session_id=session_id)
        db.session.add(cart)
        db.session.commit()
        session['cart_id'] = cart.id
    else:
        cart = Cart.query.get(session['cart_id'])
        if not cart:
            # Session cart was deleted, create new one
            session_id = str(uuid.uuid4())
            cart = Cart(session_id=session_id)
            db.session.add(cart)
            db.session.commit()
            session['cart_id'] = cart.id
    return cart

def is_safe_next(next_url):
    if not next_url:
        return False
    parsed = urlparse(next_url)
    if parsed.scheme or parsed.netloc:
        return False
    if next_url.startswith('//'):
        return False
    return next_url.startswith('/')

@app.context_processor
def inject_cart_count():
    """Make cart count available in all templates"""
    cart_count = 0
    current_customer = get_current_customer()
    if 'cart_id' in session:
        cart = Cart.query.get(session['cart_id'])
        if cart:
            cart_count = sum(item.quantity for item in cart.items)
    return {'cart_count': cart_count, 'current_customer': current_customer}

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.before_request
def enforce_https():
    if get_bool_env('FORCE_HTTPS', False) and not request.is_secure:
        return redirect(request.url.replace('http://', 'https://', 1), code=301)

@app.after_request
def set_security_headers(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
    response.headers['Permissions-Policy'] = 'geolocation=(), microphone=(), camera=()'
    response.headers['Content-Security-Policy'] = (
        "default-src 'self'; "
        "img-src 'self' data: https:; "
        "style-src 'self' 'unsafe-inline' https:; "
        "script-src 'self' 'unsafe-inline' https:; "
        "font-src 'self' data: https:; "
        "connect-src 'self' https:; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    if request.is_secure or get_bool_env('FORCE_HTTPS', False):
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    return response

@app.errorhandler(CSRFError)
def handle_csrf_error(error):
    if request.accept_mimetypes.best == 'application/json' or request.is_json:
        return jsonify({'error': 'CSRF token missing or invalid'}), 400
    flash('Your session has expired. Please try again.', 'error')
    return redirect(request.referrer or url_for('index'))

# Public routes
@app.route('/')
def index():
    hero = HeroSection.query.first()
    products = Product.query.filter_by(is_active=True).order_by(Product.order).all()
    maison = MaisonSection.query.first()
    settings = SiteSettings.query.first()
    nav_items = NavigationItem.query.filter_by(is_active=True).order_by(NavigationItem.order).all()
    order_currency = get_order_currency()
    currency_symbol = CURRENCY_SYMBOLS.get(order_currency, order_currency + ' ')
    entrance_config = {
        'enabled': settings.entrance_enabled if settings and settings.entrance_enabled is not None else True,
        'title': (settings.entrance_title if settings and settings.entrance_title else (settings.site_title if settings and settings.site_title else 'Atelier Gourmand')),
        'subtitle': (settings.entrance_subtitle if settings and settings.entrance_subtitle else 'by OC - London'),
        'description': (settings.entrance_description if settings and settings.entrance_description else 'Handcrafted patisserie'),
        'extra_text': settings.entrance_extra_text if settings else None,
        'logo_url': (settings.entrance_logo_url or settings.logo_url) if settings else None,
        'duration_ms': settings.entrance_duration_ms if settings and settings.entrance_duration_ms else 2000,
        'fade_ms': settings.entrance_fade_ms if settings and settings.entrance_fade_ms else 800,
    }
    return render_template('index.html', hero=hero, products=products, maison=maison, settings=settings, nav_items=nav_items, currency_symbol=currency_symbol, entrance_config=entrance_config)

@app.route('/api/products')
def api_products():
    products = Product.query.filter_by(is_active=True).order_by(Product.order).all()
    return jsonify([{
        'id': p.id,
        'name': p.name,
        'description': p.description,
        'price': p.price,
        'image': p.image_url,
        'order': p.order
    } for p in products])

@app.route('/api/hero')
def api_hero():
    hero = HeroSection.query.first()
    if hero:
        return jsonify({
            'title': hero.title,
            'subtitle': hero.subtitle,
            'description': hero.description,
            'image': hero.image_url,
            'location': hero.location,
            'hours': hero.hours
        })
    return jsonify({})

@limiter.limit('20 per minute')
@app.route('/api/booking', methods=['POST'])
def api_booking():
    data = request.json
    
    # Validate required fields
    if not data.get('email'):
        return jsonify({'error': 'Email is required'}), 400
    
    pickup_date = datetime.fromisoformat(data['pickup_date']).date()
    pickup_time = data['pickup_time']
    
    # Check if booking is enabled
    settings = BookingSettings.query.first()
    if settings and not settings.booking_enabled:
        return jsonify({'error': 'Bookings are currently disabled'}), 400
    
    # Check if date is blocked
    if BlockedDate.query.filter_by(date=pickup_date).first():
        return jsonify({'error': 'Selected date is not available'}), 400
    
    # Check if specific time slot is blocked
    if BlockedTimeSlot.query.filter_by(date=pickup_date, time_slot=pickup_time).first():
        return jsonify({'error': 'Selected time slot is not available'}), 400
    
    # Check max bookings per slot
    if settings:
        existing_bookings = Booking.query.filter_by(
            pickup_date=pickup_date,
            pickup_time=pickup_time,
            status='confirmed'
        ).count()
        if existing_bookings >= settings.max_bookings_per_slot:
            return jsonify({'error': 'This time slot is fully booked'}), 400
    
    booking = Booking(
        pickup_date=pickup_date,
        pickup_time=pickup_time,
        email=data['email'],
        phone=data.get('phone'),
        notes=data.get('notes')
    )
    db.session.add(booking)
    db.session.commit()
    session['pickup_confirmed'] = True
    session['pickup_date'] = pickup_date.isoformat()
    session['pickup_time'] = pickup_time
    session['booking_email'] = data.get('email')
    session['booking_phone'] = data.get('phone')
    session.modified = True
    return jsonify({
        'message': 'Booking confirmed',
        'id': booking.id,
        'redirect_url': url_for('index') + '#seasonal'
    }), 201

@app.route('/api/confirm-pickup', methods=['POST'])
def api_confirm_pickup():
    if not session.get('pickup_confirmed'):
        return jsonify({'error': 'Pickup slot not confirmed'}), 400

    data = request.get_json(silent=True) or {}
    pickup_date = session.get('pickup_date')
    pickup_time = session.get('pickup_time')
    email = data.get('email') or session.get('booking_email')
    name = (data.get('name') or '').strip()
    notes = (data.get('notes') or '').strip()

    if not pickup_date or not pickup_time:
        return jsonify({'error': 'Pickup details are missing'}), 400
    if not email:
        return jsonify({'error': 'Email is required'}), 400

    settings = SiteSettings.query.first()
    from_email = app.config.get('SMTP_FROM') or (settings.contact_email if settings else None)
    subject = 'Pickup slot confirmation - Atelier Gourmand by OC'
    greeting = f"Hello {name}," if name else "Hello,"
    instructions = notes if notes else 'None'
    body = (
        f"{greeting}\n\n"
        "Your pickup slot is confirmed with the following details:\n"
        f"Date: {pickup_date}\n"
        f"Time: {pickup_time}\n\n"
        f"Special instructions: {instructions}\n\n"
        "If you need to make changes, please reply to this email."
    )

    try:
        send_email(email, subject, body, from_email=from_email)
    except Exception:
        return jsonify({'error': 'Unable to send confirmation email'}), 500

    return jsonify({'message': 'Confirmation email sent'}), 200

@app.route('/api/available-slots')
def api_available_slots():
    """Get available time slots sorted chronologically"""
    slots = AvailableTimeSlot.query.filter_by(is_active=True).order_by(AvailableTimeSlot.time_slot).all()
    return jsonify([{'time': slot.time_slot} for slot in slots])


@csrf.exempt
@app.route('/api/pickup-selection', methods=['POST'])
def api_pickup_selection():
    data = request.get_json(silent=True) or {}
    pickup_date_str = data.get('pickup_date')
    pickup_time = data.get('pickup_time')

    if not pickup_date_str or not pickup_time:
        return jsonify({'error': 'Pickup date and time are required'}), 400

    try:
        pickup_date = datetime.fromisoformat(pickup_date_str).date()
    except Exception:
        return jsonify({'error': 'Invalid pickup date'}), 400

    settings = BookingSettings.query.first()
    if settings and not settings.booking_enabled:
        return jsonify({'error': 'Bookings are currently disabled'}), 400

    if BlockedDate.query.filter_by(date=pickup_date).first():
        return jsonify({'error': 'Selected date is not available'}), 400

    if BlockedTimeSlot.query.filter_by(date=pickup_date, time_slot=pickup_time).first():
        return jsonify({'error': 'Selected time slot is not available'}), 400

    if settings:
        existing = Booking.query.filter_by(
            pickup_date=pickup_date,
            pickup_time=pickup_time,
            status='confirmed'
        ).count()
        if existing >= settings.max_bookings_per_slot:
            return jsonify({'error': 'This time slot is fully booked'}), 400

    current_customer = get_current_customer()
    email = data.get('email') or session.get('booking_email') or (current_customer.email if current_customer else None)
    phone = data.get('phone') or session.get('booking_phone') or (current_customer.phone if current_customer else None)

    session['pickup_confirmed'] = True
    session['pickup_date'] = pickup_date.isoformat()
    session['pickup_time'] = pickup_time
    if email:
        session['booking_email'] = email
    if phone:
        session['booking_phone'] = phone
    session.modified = True

    return jsonify({'message': 'Pickup slot saved', 'pickup_date': session['pickup_date'], 'pickup_time': pickup_time})


@csrf.exempt
@app.route('/api/pickup-clear', methods=['POST'])
def api_pickup_clear():
    session.pop('pickup_confirmed', None)
    session.pop('pickup_date', None)
    session.pop('pickup_time', None)
        product = Product.query.get_or_404(product_id)
        if product.product_status == 'hidden' or not product.is_active:
            flash('This product is not available.', 'error')
            return redirect(request.referrer or url_for('index'))
        if product.product_status == 'upcoming':
            flash('This product is coming soon.', 'error')
            return redirect(request.referrer or url_for('index'))
    session.pop('booking_phone', None)
    session.modified = True
    return jsonify({'message': 'Pickup slot cleared'}), 200

# E-commerce routes
@app.route('/product/<slug>')
def product_detail(slug):
    """Product detail page"""
    # Try with slug first, fallback to ID for backwards compatibility
    product = Product.query.filter_by(is_active=True).filter(
        (Product.slug == slug) | (Product.id == slug)
    ).first_or_404()
    settings = SiteSettings.query.first()
    order_currency = get_order_currency()
    currency_symbol = CURRENCY_SYMBOLS.get(order_currency, order_currency + ' ')
    prefill_pickup_date = session.get('pickup_date')
    prefill_pickup_time = session.get('pickup_time')
    pickup_confirmed = session.get('pickup_confirmed', False)
    return render_template(
        'product_detail.html',
        product=product,
        settings=settings,
        currency_symbol=currency_symbol,
        prefill_pickup_date=prefill_pickup_date,
        prefill_pickup_time=prefill_pickup_time,
        pickup_confirmed=pickup_confirmed
    )

@app.route('/cart')
def view_cart():
    """View shopping cart"""
    cart = get_or_create_cart()
    settings = SiteSettings.query.first()
    subtotal = sum(item.quantity * item.price_at_add for item in cart.items)
    order_currency = get_order_currency()
    base_currency = app.config['BASE_CURRENCY']
    fx_rate = get_currency_rate(base_currency, order_currency)
    if fx_rate is None:
        order_currency = base_currency
        fx_rate = 1.0
    display_subtotal = convert_amount(subtotal, fx_rate)
    currency_symbol = CURRENCY_SYMBOLS.get(order_currency, order_currency + ' ')
    pickup_confirmed = session.get('pickup_confirmed')
    pickup_date = session.get('pickup_date')
    pickup_time = session.get('pickup_time')
    return render_template(
        'cart.html',
        cart=cart,
        subtotal=subtotal,
        display_subtotal=display_subtotal,
        currency_symbol=currency_symbol,
        settings=settings,
        pickup_confirmed=pickup_confirmed,
        pickup_date=pickup_date,
        pickup_time=pickup_time,
    )

@app.route('/cart/add', methods=['POST'])
def add_to_cart():
    """Add product to cart"""
    try:
        product_id = request.form.get('product_id', type=int)
        variant_id = request.form.get('variant_id', type=int) if request.form.get('variant_id') else None
        quantity = request.form.get('quantity', 1, type=int)
        
        product = Product.query.get_or_404(product_id)
        variant = ProductVariant.query.get(variant_id) if variant_id else None

        if product.product_status == 'hidden' or not product.is_active:
            flash('This product is not available.', 'error')
            return redirect(request.referrer or url_for('index'))
        if product.product_status == 'upcoming':
            flash('This product is coming soon.', 'error')
            return redirect(request.referrer or url_for('index'))
        
        price = product.price
        if variant and variant.price_modifier:
            price += variant.price_modifier
        
        cart = get_or_create_cart()
        
        existing_item = CartItem.query.filter_by(
            cart_id=cart.id,
            product_id=product_id,
            variant_id=variant_id
        ).first()

        if product.track_inventory and not product.allow_backorder:
            desired_quantity = quantity + (existing_item.quantity if existing_item else 0)
            available = product.stock_quantity
            if variant and variant.stock_quantity is not None:
                available = variant.stock_quantity if available is None else min(available, variant.stock_quantity)
            if available is not None and desired_quantity > available:
                flash('Not enough stock available.', 'error')
                return redirect(request.referrer or url_for('product_detail', slug=product.slug or product.id))
        
        if existing_item:
            existing_item.quantity += quantity
            existing_item.updated_at = datetime.utcnow()
        else:
            cart_item = CartItem(
                cart_id=cart.id,
                product_id=product_id,
                variant_id=variant_id,
                quantity=quantity,
                price_at_add=price
            )
            db.session.add(cart_item)
        
        db.session.commit()
        flash(f'{product.name} added to cart!', 'success')
        next_url = request.form.get('next')
        if is_safe_next(next_url):
            return redirect(next_url)
        return redirect(request.referrer or url_for('index'))
    except Exception as e:
        flash(f'Error adding to cart: {str(e)}', 'error')
        return redirect(request.referrer or url_for('index'))

@app.route('/cart/update/<int:item_id>', methods=['POST'])
def update_cart_item(item_id):
    """Update cart item quantity"""
    try:
        quantity = request.form.get('quantity', 1, type=int)
        cart = get_or_create_cart()
        cart_item = CartItem.query.filter_by(id=item_id, cart_id=cart.id).first_or_404()
        
        if quantity > 0:
            cart_item.quantity = quantity
            cart_item.updated_at = datetime.utcnow()
            db.session.commit()
            flash('Cart updated!', 'success')
        else:
            db.session.delete(cart_item)
            db.session.commit()
            flash('Item removed from cart!', 'success')
        
        return redirect(url_for('view_cart'))
    except Exception as e:
        flash(f'Error updating cart: {str(e)}', 'error')
        return redirect(url_for('view_cart'))

@app.route('/cart/remove/<int:item_id>', methods=['POST'])
def remove_from_cart(item_id):
    """Remove item from cart"""
    try:
        cart = get_or_create_cart()
        cart_item = CartItem.query.filter_by(id=item_id, cart_id=cart.id).first_or_404()
        db.session.delete(cart_item)
        db.session.commit()
        flash('Item removed from cart!', 'success')
    except Exception as e:
        flash(f'Error removing item: {str(e)}', 'error')
    return redirect(url_for('view_cart'))

@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    """Checkout page"""
    cart = get_or_create_cart()
    current_customer = get_current_customer()
    
    if not cart.items:
        flash('Your cart is empty!', 'warning')
        return redirect(url_for('index'))

    # Allow choosing/booking a slot directly on checkout if none was picked earlier
    if request.method == 'POST':
        fulfillment_method = request.form.get('fulfillment_method', 'pickup')
    
    order_currency = get_order_currency()
    base_currency = app.config['BASE_CURRENCY']
    fx_rate = get_currency_rate(base_currency, order_currency)
    if fx_rate is None:
        order_currency = base_currency
        fx_rate = 1.0

    settings = SiteSettings.query.first()
    stripe_public_key = app.config['STRIPE_PUBLIC_KEY'] or (settings.stripe_public_key if settings else None)
    stripe_secret_key = app.config['STRIPE_SECRET_KEY'] or (settings.stripe_secret_key if settings else None)
    paypal_client_id = app.config['PAYPAL_CLIENT_ID'] or (settings.paypal_client_id if settings else None)
    paypal_client_secret = app.config['PAYPAL_CLIENT_SECRET']
    allow_test_checkout = bool(settings.allow_test_checkout) if settings else False

    available_payment_methods = []
    if stripe_public_key and stripe_secret_key:
        available_payment_methods.append('stripe')
    if paypal_client_id and paypal_client_secret:
        available_payment_methods.append('paypal')
    if not available_payment_methods and not allow_test_checkout:
        # Fallback to test checkout when live gateways are missing
        allow_test_checkout = True
    if not available_payment_methods and not allow_test_checkout:
        flash('Online card payments are not configured yet.', 'error')
        return redirect(url_for('view_cart'))

    if request.method == 'POST':
        try:
            customer_name = (request.form.get('name') or (current_customer.name if current_customer else None))
            customer_email = (request.form.get('email') or '').strip().lower()
            customer_phone = request.form.get('phone') or (current_customer.phone if current_customer else None)
            pickup_date_str = request.form.get('pickup_date') or session.get('pickup_date')
            pickup_time = request.form.get('pickup_time') or session.get('pickup_time')
            notes = request.form.get('notes')
            payment_method = request.form.get('payment_method')
            is_test_checkout = request.form.get('test_checkout') == '1'
            account_choice = request.form.get('account_choice', 'guest')
            account_password = request.form.get('account_password') or ''
            account_password_confirm = request.form.get('account_password_confirm') or ''
            new_customer = None

            if is_test_checkout and allow_test_checkout:
                payment_method = 'test'
            if not payment_method:
                if available_payment_methods:
                    payment_method = available_payment_methods[0]
                elif allow_test_checkout:
                    payment_method = 'test'

            if not pickup_date_str or not pickup_time:
                flash('Pickup date and time are required.', 'error')
                return redirect(url_for('checkout'))

            pickup_date = datetime.strptime(pickup_date_str, '%Y-%m-%d').date()

            if current_customer:
                account_choice = 'existing'
                customer_email = current_customer.email
                if not customer_name:
                    customer_name = current_customer.name
                if not customer_phone and current_customer.phone:
                    customer_phone = current_customer.phone

            if account_choice == 'create' and not current_customer:
                if not customer_email or not account_password:
                    flash('To create an account, please add your email and a password.', 'error')
                    return redirect(url_for('checkout'))
                if len(account_password) < 8:
                    flash('Password must be at least 8 characters.', 'error')
                    return redirect(url_for('checkout'))
                if account_password != account_password_confirm:
                    flash('Passwords do not match.', 'error')
                    return redirect(url_for('checkout'))
                existing = Customer.query.filter_by(email=customer_email).first()
                if existing:
                    flash('An account with this email already exists. Please sign in.', 'error')
                    return redirect(url_for('customer_login', next=url_for('checkout')))
                new_customer = Customer(
                    name=customer_name,
                    email=customer_email,
                    phone=customer_phone or None,
                    password_hash=generate_password_hash(account_password)
                )
                db.session.add(new_customer)
                db.session.flush()
                session['customer_id'] = new_customer.id
                session.modified = True
                current_customer = new_customer

            if not customer_name or not customer_email:
                flash('Name and email are required.', 'error')
                return redirect(url_for('checkout'))

            if payment_method not in available_payment_methods and not (payment_method == 'test' and allow_test_checkout):
                flash('Selected payment method is unavailable.', 'error')
                return redirect(url_for('checkout'))

            if payment_method == 'stripe' and not (stripe_public_key and stripe_secret_key):
                flash('Stripe payments are not configured yet.', 'error')
                return redirect(url_for('checkout'))
            if payment_method == 'paypal' and not (paypal_client_id and paypal_client_secret):
                flash('PayPal payments are not configured yet.', 'error')
                return redirect(url_for('checkout'))
            
            subtotal = sum(item.quantity * item.price_at_add for item in cart.items)
            tax = 0
            total = subtotal + tax
            display_subtotal = convert_amount(subtotal, fx_rate)
            display_tax = convert_amount(tax, fx_rate)
            display_total = convert_amount(total, fx_rate)
            
            order_number = build_order_number(settings)
            
            order = Order(
                order_number=order_number,
                customer_name=customer_name,
                customer_email=customer_email,
                customer_phone=customer_phone,
                pickup_date=pickup_date,
                pickup_time=pickup_time,
                subtotal=subtotal,
                tax=tax,
                total=total,
                currency=order_currency,
                fx_rate=fx_rate,
                payment_method=payment_method,
                payment_status='pending',
                status='pending',
                notes=notes,
                customer_id=current_customer.id if current_customer else None
            )
            db.session.add(order)
            db.session.flush()
            
            for cart_item in cart.items:
                order_item = OrderItem(
                    order_id=order.id,
                    product_id=cart_item.product_id,
                    variant_id=cart_item.variant_id,
                    product_name=cart_item.product.name,
                    variant_name=cart_item.variant.name if cart_item.variant else None,
                    quantity=cart_item.quantity,
                    unit_price=cart_item.price_at_add,
                    total_price=cart_item.quantity * cart_item.price_at_add
                )
                db.session.add(order_item)
            
            if payment_method == 'test' and allow_test_checkout:
                order.payment_status = 'paid'
                order.status = 'confirmed'
                db.session.commit()
                for item in cart.items:
                    db.session.delete(item)
                db.session.commit()
                session.pop('cart_id', None)
                try:
                    body = build_order_confirmation_body(order)
                    html_body = build_order_confirmation_html(order)
                    send_email(
                        order.customer_email,
                        f'Order confirmation {order.order_number}',
                        body,
                        from_email=app.config.get('SMTP_FROM') or order.customer_email,
                        html_body=html_body,
                    )
                except Exception:
                    pass
                flash(f'Order {order_number} placed (test mode).', 'success')
                return redirect(url_for('order_confirmation', order_number=order_number))

            if payment_method == 'stripe':
                stripe.api_key = stripe_secret_key
                success_url = f"{build_base_url()}{app.config['PAYMENT_SUCCESS_PATH']}?order_number={order_number}"
                cancel_url = f"{build_base_url()}{app.config['PAYMENT_CANCEL_PATH']}?order_number={order_number}"
                session_obj = stripe.checkout.Session.create(
                    mode='payment',
                    payment_method_types=['card'],
                    line_items=[
                        {
                            'price_data': {
                                'currency': order_currency.lower(),
                                'product_data': {
                                    'name': f"Order {order_number}",
                                },
                                'unit_amount': int(display_total * 100),
                            },
                            'quantity': 1,
                        }
                    ],
                    success_url=success_url,
                    cancel_url=cancel_url,
                    client_reference_id=str(order.id),
                    metadata={
                        'order_number': order_number,
                        'order_id': order.id,
                        'currency': order_currency,
                        'fx_rate': fx_rate,
                    },
                )
                order.payment_intent_id = session_obj.get('payment_intent')
                db.session.commit()
                return redirect(session_obj.url, code=303)

            if payment_method == 'paypal':
                app.config['PAYPAL_CLIENT_ID'] = paypal_client_id
                app.config['PAYPAL_CLIENT_SECRET'] = paypal_client_secret
                success_url = f"{build_base_url()}{app.config['PAYMENT_SUCCESS_PATH']}?order_number={order_number}"
                cancel_url = f"{build_base_url()}{app.config['PAYMENT_CANCEL_PATH']}?order_number={order_number}"
                request_obj = OrdersCreateRequest()
                request_obj.prefer('return=representation')
                request_obj.request_body({
                    'intent': 'CAPTURE',
                    'purchase_units': [
                        {
                            'reference_id': order_number,
                            'amount': {
                                'currency_code': order_currency,
                                'value': f"{display_total:.2f}",
                            },
                        }
                    ],
                    'application_context': {
                        'return_url': success_url,
                        'cancel_url': cancel_url,
                    },
                })
                paypal_client = get_paypal_client()
                response = paypal_client.execute(request_obj)
                order.payment_intent_id = response.result.id
                db.session.commit()
                approval_url = next(
                    (link.href for link in response.result.links if link.rel == 'approve'),
                    None
                )
                if not approval_url:
                    flash('Unable to start PayPal checkout.', 'error')
                    return redirect(url_for('checkout'))
                return redirect(approval_url, code=303)

            for item in cart.items:
                db.session.delete(item)

            db.session.commit()
            session.pop('cart_id', None)

            try:
                body = build_order_confirmation_body(order)
                html_body = build_order_confirmation_html(order)
                send_email(
                    order.customer_email,
                    f'Order confirmation {order.order_number}',
                    body,
                    from_email=app.config.get('SMTP_FROM') or order.customer_email,
                    html_body=html_body,
                )
            except Exception:
                pass

            flash(f'Order {order_number} placed successfully!', 'success')
            return redirect(url_for('order_confirmation', order_number=order_number))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error processing order: {str(e)}', 'error')
            return redirect(url_for('checkout'))
    
    booking_settings = BookingSettings.query.first()
    time_slots = AvailableTimeSlot.query.filter_by(is_active=True).order_by(AvailableTimeSlot.time_slot).all()
    
    subtotal = sum(item.quantity * item.price_at_add for item in cart.items)
    tax = 0
    total = subtotal + tax
    display_subtotal = convert_amount(subtotal, fx_rate)
    display_tax = convert_amount(tax, fx_rate)
    display_total = convert_amount(total, fx_rate)
    currency_symbol = CURRENCY_SYMBOLS.get(order_currency, order_currency + ' ')
    prefill_pickup_date = session.get('pickup_date')
    prefill_pickup_time = session.get('pickup_time')
    prefill_email = session.get('booking_email')
    prefill_phone = session.get('booking_phone')
    prefill_name = current_customer.name if current_customer else None

    if current_customer:
        prefill_email = prefill_email or current_customer.email
        prefill_phone = prefill_phone or current_customer.phone
    
    return render_template('checkout.html', 
                         cart=cart, 
                         subtotal=subtotal, 
                         tax=tax, 
                         total=total,
                         display_subtotal=display_subtotal,
                         display_tax=display_tax,
                         display_total=display_total,
                         currency_symbol=currency_symbol,
                         order_currency=order_currency,
                         settings=settings,
                         booking_settings=booking_settings,
                         time_slots=time_slots,
                         prefill_pickup_date=prefill_pickup_date,
                         prefill_pickup_time=prefill_pickup_time,
                         prefill_name=prefill_name,
                         prefill_email=prefill_email,
                         prefill_phone=prefill_phone,
                         stripe_available='stripe' in available_payment_methods,
                         paypal_available='paypal' in available_payment_methods,
                         available_payment_methods=available_payment_methods,
                         allow_test_checkout=allow_test_checkout)

@app.route('/order/<order_number>')
def order_confirmation(order_number):
    """Order confirmation page"""
    order = Order.query.filter_by(order_number=order_number).first_or_404()
    settings = SiteSettings.query.first()
    currency_symbol = CURRENCY_SYMBOLS.get(order.currency or app.config['DEFAULT_CURRENCY'], '£')
    return render_template('order_confirmation.html', order=order, settings=settings, currency_symbol=currency_symbol)

@app.route('/payment/success')
def payment_success():
    order_number = request.args.get('order_number')
    order = Order.query.filter_by(order_number=order_number).first()
    if not order:
        flash('Order not found.', 'error')
        return redirect(url_for('index'))
    session_key = f'order_email_sent_{order_number}'
    if not session.get(session_key):
        try:
            body = build_order_confirmation_body(order)
            html_body = build_order_confirmation_html(order)
            send_email(
                order.customer_email,
                f'Order confirmation {order.order_number}',
                body,
                from_email=app.config.get('SMTP_FROM') or order.customer_email,
                html_body=html_body,
            )
            session[session_key] = True
            session.modified = True
        except Exception:
            pass
    return redirect(url_for('order_confirmation', order_number=order_number))

@app.route('/payment/cancel')
def payment_cancel():
    order_number = request.args.get('order_number')
    if order_number:
        flash('Payment was canceled. You can try again.', 'warning')
        return redirect(url_for('checkout'))
    flash('Payment was canceled.', 'warning')
    return redirect(url_for('checkout'))

@app.route('/webhooks/stripe', methods=['POST'])
@csrf.exempt
def stripe_webhook():
    if not app.config['STRIPE_WEBHOOK_SECRET']:
        return jsonify({'error': 'Webhook secret not configured'}), 400
    payload = request.get_data()
    sig_header = request.headers.get('Stripe-Signature')
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, app.config['STRIPE_WEBHOOK_SECRET']
        )
    except (ValueError, stripe.error.SignatureVerificationError):
        return jsonify({'error': 'Invalid payload'}), 400

    event_type = event.get('type')
    data_object = event.get('data', {}).get('object', {})
    if event_type in ['checkout.session.completed', 'checkout.session.async_payment_succeeded']:
        order_number = data_object.get('metadata', {}).get('order_number')
        order = Order.query.filter_by(order_number=order_number).first()
        if order:
            order.payment_status = 'paid'
            order.status = 'confirmed'
            db.session.commit()
    elif event_type in ['checkout.session.async_payment_failed', 'payment_intent.payment_failed']:
        order_number = data_object.get('metadata', {}).get('order_number')
        order = Order.query.filter_by(order_number=order_number).first()
        if order:
            order.payment_status = 'failed'
            db.session.commit()

    return jsonify({'status': 'ok'})

@app.route('/webhooks/paypal', methods=['POST'])
@csrf.exempt
def paypal_webhook():
    event = request.get_json(silent=True) or {}
    try:
        verified = verify_paypal_webhook(event, request.headers)
    except Exception:
        return jsonify({'error': 'Webhook verification failed'}), 400
    if not verified:
        return jsonify({'error': 'Invalid webhook signature'}), 400

    event_type = event.get('event_type')
    resource = event.get('resource', {})
    order_id = resource.get('id')
    order = Order.query.filter_by(payment_intent_id=order_id).first()
    if order and event_type in ['CHECKOUT.ORDER.APPROVED', 'PAYMENT.CAPTURE.COMPLETED']:
        order.payment_status = 'paid'
        order.status = 'confirmed'
        db.session.commit()
    elif order and event_type in ['PAYMENT.CAPTURE.DENIED', 'PAYMENT.CAPTURE.REFUNDED']:
        order.payment_status = 'failed'
        db.session.commit()

    return jsonify({'status': 'ok'})


@app.route('/account/login', methods=['GET', 'POST'])
def customer_login():
    next_url = request.args.get('next') or request.form.get('next') or url_for('index')

    if get_current_customer():
        return redirect(next_url if is_safe_next(next_url) else url_for('index'))

    if request.method == 'POST':
        email = (request.form.get('email') or '').strip().lower()
        password = request.form.get('password') or ''
        customer = Customer.query.filter_by(email=email).first()

        if customer and check_password_hash(customer.password_hash, password):
            session['customer_id'] = customer.id
            session.modified = True
            flash('Signed in successfully.', 'success')
            return redirect(next_url if is_safe_next(next_url) else url_for('checkout'))

        flash('Invalid email or password.', 'error')

    settings = SiteSettings.query.first()
    return render_template('account_login.html', next=next_url, settings=settings)


@app.route('/account/register', methods=['GET', 'POST'])
def customer_register():
    next_url = request.args.get('next') or request.form.get('next') or url_for('checkout')

    if get_current_customer():
        return redirect(next_url if is_safe_next(next_url) else url_for('index'))

    if request.method == 'POST':
        name = (request.form.get('name') or '').strip()
        email = (request.form.get('email') or '').strip().lower()
        phone = (request.form.get('phone') or '').strip()
        password = request.form.get('password') or ''
        confirm_password = request.form.get('confirm_password') or ''

        if not name or not email or not password:
            flash('Name, email, and password are required.', 'error')
        elif password != confirm_password:
            flash('Passwords do not match.', 'error')
        elif len(password) < 8:
            flash('Password must be at least 8 characters.', 'error')
        elif Customer.query.filter_by(email=email).first():
            flash('An account with this email already exists.', 'error')
        else:
            customer = Customer(
                name=name,
                email=email,
                phone=phone or None,
                password_hash=generate_password_hash(password)
            )
            db.session.add(customer)
            db.session.commit()
            session['customer_id'] = customer.id
            session.modified = True
            flash('Account created. You are now signed in.', 'success')
            return redirect(next_url if is_safe_next(next_url) else url_for('checkout'))

    settings = SiteSettings.query.first()
    return render_template('account_register.html', next=next_url, settings=settings)


@app.route('/account/logout', methods=['POST'])
def customer_logout():
    next_url = request.form.get('next') or url_for('index')
    session.pop('customer_id', None)
    session.modified = True
    flash('Signed out.', 'success')
    return redirect(next_url if is_safe_next(next_url) else url_for('index'))

# Admin routes
@limiter.limit('5 per minute')
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if current_user.is_authenticated:
        return redirect(url_for('admin_dashboard'))
    
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('admin_dashboard'))
        flash('Invalid email or password', 'error')
    
    return render_template('admin/login.html')

@app.route('/admin/logout', methods=['POST'])
@login_required
def admin_logout():
    logout_user()
    return redirect(url_for('index'))

@app.route('/admin')
@login_required
def admin_dashboard():
    from sqlalchemy import func
    from datetime import timedelta, date
    
    # Basic counts
    total_products = Product.query.count()
    total_orders = Order.query.count()
    pending_orders = Order.query.filter_by(status='pending').count()
    
    # Revenue & Profit calculations
    paid_orders = Order.query.filter(Order.payment_status.in_(['paid', 'completed'])).all()
    total_revenue = sum(order.total for order in paid_orders) if paid_orders else 0
    
    # Calculate profit (assuming 60% margin for simplicity - can be customized per product)
    total_cost = total_revenue * 0.4  # 40% cost of goods
    total_profit = total_revenue - total_cost
    
    # Today's sales
    today = date.today()
    today_orders = Order.query.filter(
        func.date(Order.created_at) == today,
        Order.payment_status.in_(['paid', 'completed'])
    ).all()
    today_revenue = sum(order.total for order in today_orders) if today_orders else 0
    
    # Last 30 days revenue trend
    daily_revenue = []
    daily_labels = []
    for i in range(29, -1, -1):
        day = today - timedelta(days=i)
        day_orders = Order.query.filter(
            func.date(Order.created_at) == day,
            Order.payment_status.in_(['paid', 'completed'])
        ).all()
        revenue = sum(order.total for order in day_orders) if day_orders else 0
        daily_revenue.append(round(revenue, 2))
        daily_labels.append(day.strftime('%d/%m'))
    
    # Top selling products
    top_products = db.session.query(
        OrderItem.product_name,
        func.sum(OrderItem.quantity).label('total_sold'),
        func.sum(OrderItem.total_price).label('total_revenue')
    ).join(Order).filter(
        Order.payment_status.in_(['paid', 'completed'])
    ).group_by(OrderItem.product_name).order_by(func.sum(OrderItem.quantity).desc()).limit(5).all()
    
    # Low stock products
    low_stock_products = Product.query.filter(
        Product.track_inventory == True,
        Product.stock_quantity <= 5
    ).order_by(Product.stock_quantity).limit(10).all()
    
    # Recent orders
    recent_orders = Order.query.order_by(Order.created_at.desc()).limit(10).all()
    
    # Stock stats
    total_stock_value = 0
    products_with_stock = Product.query.filter(Product.track_inventory == True).all()
    for product in products_with_stock:
        total_stock_value += (product.stock_quantity * product.price) if product.price else 0
    
    stats = {
        'total_products': total_products,
        'total_orders': total_orders,
        'pending_orders': pending_orders,
        'total_revenue': round(total_revenue, 2),
        'total_profit': round(total_profit, 2),
        'today_revenue': round(today_revenue, 2),
        'total_stock_value': round(total_stock_value, 2),
        'daily_revenue': daily_revenue,
        'daily_labels': daily_labels
    }
    
    return render_template('admin/dashboard.html', 
                         stats=stats, 
                         top_products=top_products,
                         low_stock_products=low_stock_products,
                         recent_orders=recent_orders)

@app.route('/admin/products')
@login_required
def admin_products():
    products = Product.query.order_by(Product.order).all()
    return render_template('admin/products.html', products=products)

@app.route('/admin/products/new', methods=['GET', 'POST'])
@login_required
def admin_product_new():
    if request.method == 'POST':
        image_url = None
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'products', filename)
                file.save(filepath)
                image_url = f'/static/uploads/products/{filename}'
        
        product = Product(
            name=request.form['name'],
            short_description=request.form.get('short_description'),
            full_description=request.form.get('full_description'),
            description=request.form.get('short_description', ''),  # Backward compatibility
            price=float(request.form['price']) if request.form.get('price') else None,
            image_url=image_url,
            is_active=request.form.get('is_active') == 'on',
            order=int(request.form.get('order', 0))
        )
        db.session.add(product)
        db.session.commit()
        flash('Product created successfully', 'success')
        return redirect(url_for('admin_products'))
    
    return render_template('admin/product_form.html', product=None)

@app.route('/admin/products/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def admin_product_edit(id):
    product = Product.query.get_or_404(id)
    
    if request.method == 'POST':
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'products', filename)
                file.save(filepath)
                product.image_url = f'/static/uploads/products/{filename}'
        
        product.name = request.form['name']
        product.short_description = request.form.get('short_description')
        product.full_description = request.form.get('full_description')
        product.description = request.form.get('short_description', '')  # Backward compatibility
        product.price = float(request.form['price']) if request.form.get('price') else None
        product.is_active = request.form.get('is_active') == 'on'
        product.order = int(request.form.get('order', 0))
        
        db.session.commit()
        flash('Product updated successfully', 'success')
        return redirect(url_for('admin_products'))
    
    return render_template('admin/product_form.html', product=product)

@app.route('/admin/products/<int:id>/delete', methods=['POST'])
@login_required
def admin_product_delete(id):
    product = Product.query.get_or_404(id)
    db.session.delete(product)
    db.session.commit()
    flash('Product deleted successfully', 'success')
    return redirect(url_for('admin_products'))

@app.route('/admin/hero', methods=['GET', 'POST'])
@login_required
def admin_hero():
    hero = HeroSection.query.first()
    if not hero:
        hero = HeroSection()
        db.session.add(hero)
    
    if request.method == 'POST':
        media_type = request.form.get('media_type', 'image')
        hero.media_type = media_type
        
        if media_type == 'image' and 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'hero', filename)
                file.save(filepath)
                hero.image_url = f'/static/uploads/hero/{filename}'
                hero.video_url = None
        elif media_type == 'video' and 'video' in request.files:
            file = request.files['video']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'hero', filename)
                file.save(filepath)
                hero.video_url = f'/static/uploads/hero/{filename}'
                hero.image_url = None
        
        hero.title = request.form['title']
        hero.subtitle = request.form['subtitle']
        hero.description = request.form['description']
        hero.location = request.form['location']
        hero.hours = request.form['hours']
        
        db.session.commit()
        flash('Hero section updated successfully', 'success')
        return redirect(url_for('admin_hero'))
    
    return render_template('admin/hero.html', hero=hero)

@app.route('/admin/maison', methods=['GET', 'POST'])
@login_required
def admin_maison():
    maison = MaisonSection.query.first()
    if not maison:
        maison = MaisonSection()
        db.session.add(maison)
    
    if request.method == 'POST':
        if 'image' in request.files:
            file = request.files['image']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'maison', filename)
                file.save(filepath)
                maison.image_url = f'/static/uploads/maison/{filename}'
        
        maison.title = request.form['title']
        maison.description = request.form['description']
        maison.cta_label = request.form.get('cta_label') or None
        maison.cta_url = request.form.get('cta_url') or None
        
        db.session.commit()
        flash('Maison section updated successfully', 'success')
        return redirect(url_for('admin_maison'))
    
    return render_template('admin/maison.html', maison=maison)

@app.route('/admin/bookings')
@login_required
def admin_bookings():
    status = request.args.get('status', 'all')
    query = Booking.query.order_by(Booking.created_at.desc())
    
    if status != 'all':
        query = query.filter_by(status=status)
    
    bookings = query.all()
    return render_template('admin/bookings.html', bookings=bookings, current_status=status)

@app.route('/admin/bookings/<int:id>/status', methods=['POST'])
@login_required
def admin_booking_status(id):
    booking = Booking.query.get_or_404(id)
    booking.status = request.form['status']
    db.session.commit()
    flash('Booking status updated', 'success')
    return redirect(url_for('admin_bookings'))

@app.route('/admin/bookings/<int:id>/delete', methods=['POST'])
@login_required
def admin_booking_delete(id):
    booking = Booking.query.get_or_404(id)
    db.session.delete(booking)
    db.session.commit()
    flash('Booking deleted', 'success')
    return redirect(url_for('admin_bookings'))

@app.route('/admin/bookings/<int:id>/rebook', methods=['POST'])
@login_required
def admin_booking_rebook(id):
    booking = Booking.query.get_or_404(id)
    new_date = request.form.get('pickup_date')
    new_time = request.form.get('pickup_time')
    message = request.form.get('message')

    if not new_date or not new_time:
        flash('Pickup date and time are required to rebook.', 'error')
        return redirect(url_for('admin_bookings'))

    try:
        booking.pickup_date = datetime.strptime(new_date, '%Y-%m-%d').date()
    except ValueError:
        flash('Invalid date format.', 'error')
        return redirect(url_for('admin_bookings'))

    booking.pickup_time = new_time
    booking.status = 'confirmed'
    db.session.commit()

    if booking.email:
        subject = f'Updated pickup slot for {booking.pickup_date} at {booking.pickup_time}'
        body = message or (
            'Your pickup slot has been updated.\n\n'
            f'Date: {booking.pickup_date}\n'
            f'Time: {booking.pickup_time}\n\n'
            'If this change does not work for you, please reply to this email.'
        )
        try:
            settings = SiteSettings.query.first()
            from_email = app.config.get('SMTP_FROM') or (settings.contact_email if settings else None)
            send_email(booking.email, subject, body, from_email=from_email)
        except Exception:
            flash('Booking updated, but email could not be sent.', 'error')
            return redirect(url_for('admin_bookings'))

    flash('Booking rebooked and email sent.' if booking.email else 'Booking rebooked.', 'success')
    return redirect(url_for('admin_bookings'))

@app.route('/admin/bookings/<int:id>/email', methods=['POST'])
@login_required
def admin_booking_email(id):
    booking = Booking.query.get_or_404(id)
    subject = request.form.get('subject') or 'Update to your pickup booking'
    body = request.form.get('message')
    if not booking.email:
        flash('No email on file for this booking.', 'error')
        return redirect(url_for('admin_bookings'))
    if not body:
        flash('Message body is required.', 'error')
        return redirect(url_for('admin_bookings'))
    try:
        settings = SiteSettings.query.first()
        from_email = app.config.get('SMTP_FROM') or (settings.contact_email if settings else None)
        send_email(booking.email, subject, body, from_email=from_email)
        flash('Email sent to client.', 'success')
    except Exception:
        flash('Unable to send email.', 'error')
    return redirect(url_for('admin_bookings'))

@app.route('/admin/availability')
@login_required
def admin_availability():
    slots = AvailableTimeSlot.query.order_by(AvailableTimeSlot.time_slot).all()
    blocked_dates = BlockedDate.query.order_by(BlockedDate.date).all()
    blocked_slots = BlockedTimeSlot.query.order_by(BlockedTimeSlot.date.desc()).limit(50).all()
    settings = BookingSettings.query.first()
    if not settings:
        settings = BookingSettings()
        db.session.add(settings)
        db.session.commit()
    return render_template('admin/availability.html', 
                         slots=slots, 
                         blocked_dates=blocked_dates, 
                         blocked_slots=blocked_slots,
                         settings=settings)

@app.route('/admin/availability/timeslot', methods=['POST'])
@login_required
def admin_add_timeslot():
    time_slot = request.form['time_slot']
    existing = AvailableTimeSlot.query.filter_by(time_slot=time_slot).first()
    if existing:
        flash('Time slot already exists', 'error')
    else:
        slot = AvailableTimeSlot(
            time_slot=time_slot,
            order=int(request.form.get('order', 0)),
            is_active=request.form.get('is_active') == 'on'
        )
        db.session.add(slot)
        db.session.commit()
        flash('Time slot added successfully', 'success')
    return redirect(url_for('admin_availability'))

@app.route('/admin/availability/timeslot/<int:id>/delete', methods=['POST'])
@login_required
def admin_delete_timeslot(id):
    slot = AvailableTimeSlot.query.get_or_404(id)
    db.session.delete(slot)
    db.session.commit()
    flash('Time slot deleted successfully', 'success')
    return redirect(url_for('admin_availability'))

@app.route('/admin/availability/timeslot/<int:id>/toggle', methods=['POST'])
@login_required
def admin_toggle_timeslot(id):
    slot = AvailableTimeSlot.query.get_or_404(id)
    slot.is_active = not slot.is_active
    db.session.commit()
    flash('Time slot updated successfully', 'success')
    return redirect(url_for('admin_availability'))
# Navigation Management Routes
@app.route('/admin/navigation')
@login_required
def admin_navigation():
    nav_items = NavigationItem.query.order_by(NavigationItem.order).all()
    return render_template('admin/navigation.html', nav_items=nav_items)

@app.route('/admin/navigation/new', methods=['GET', 'POST'])
@login_required
def admin_navigation_new():
    if request.method == 'POST':
        nav_item = NavigationItem(
            label=request.form['label'],
            url=request.form['url'],
            is_cta=request.form.get('is_cta') == 'on',
            is_active=request.form.get('is_active') == 'on',
            order=int(request.form.get('order', 0)),
            target=request.form.get('target', '_self')
        )
        db.session.add(nav_item)
        db.session.commit()
        flash('Navigation item created successfully', 'success')
        return redirect(url_for('admin_navigation'))
    
    return render_template('admin/navigation_form.html', nav_item=None)

@app.route('/admin/navigation/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def admin_navigation_edit(id):
    nav_item = NavigationItem.query.get_or_404(id)
    
    if request.method == 'POST':
        nav_item.label = request.form['label']
        nav_item.url = request.form['url']
        nav_item.is_cta = request.form.get('is_cta') == 'on'
        nav_item.is_active = request.form.get('is_active') == 'on'
        nav_item.order = int(request.form.get('order', 0))
        nav_item.target = request.form.get('target', '_self')
        
        db.session.commit()
        flash('Navigation item updated successfully', 'success')
        return redirect(url_for('admin_navigation'))
    
    return render_template('admin/navigation_form.html', nav_item=nav_item)

@app.route('/admin/navigation/<int:id>/delete', methods=['POST'])
@login_required
def admin_navigation_delete(id):
    nav_item = NavigationItem.query.get_or_404(id)
    db.session.delete(nav_item)
    db.session.commit()
    flash('Navigation item deleted successfully', 'success')
    return redirect(url_for('admin_navigation'))

# Discount routes
@app.route('/admin/discounts')
@login_required
def admin_discounts():
    discounts = Discount.query.order_by(Discount.created_at.desc()).all()
    return render_template('admin/discounts.html', discounts=discounts)

@app.route('/admin/discounts/new', methods=['GET', 'POST'])
@login_required
def admin_discount_new():
    if request.method == 'POST':
        discount = Discount(
            code=request.form['code'].upper(),
            description=request.form.get('description'),
            discount_type=request.form['discount_type'],
            discount_value=float(request.form['discount_value']),
            min_order_amount=float(request.form.get('min_order_amount', 0)),
            max_discount_amount=float(request.form['max_discount_amount']) if request.form.get('max_discount_amount') else None,
            free_delivery='free_delivery' in request.form,
            usage_limit=int(request.form['usage_limit']) if request.form.get('usage_limit') else None,
            per_customer_limit=int(request.form.get('per_customer_limit', 1)),
            is_active='is_active' in request.form
        )
        
        if request.form.get('start_date'):
            discount.start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%dT%H:%M')
        if request.form.get('end_date'):
            discount.end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%dT%H:%M')
        
        db.session.add(discount)
        db.session.commit()
        flash('Discount code created successfully!', 'success')
        return redirect(url_for('admin_discounts'))
    
    return render_template('admin/discount_form.html')

@app.route('/admin/discounts/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def admin_discount_edit(id):
    discount = Discount.query.get_or_404(id)
    
    if request.method == 'POST':
        discount.code = request.form['code'].upper()
        discount.description = request.form.get('description')
        discount.discount_type = request.form['discount_type']
        discount.discount_value = float(request.form['discount_value'])
        discount.min_order_amount = float(request.form.get('min_order_amount', 0))
        discount.max_discount_amount = float(request.form['max_discount_amount']) if request.form.get('max_discount_amount') else None
        discount.free_delivery = 'free_delivery' in request.form
        discount.usage_limit = int(request.form['usage_limit']) if request.form.get('usage_limit') else None
        discount.per_customer_limit = int(request.form.get('per_customer_limit', 1))
        discount.is_active = 'is_active' in request.form
        
        if request.form.get('start_date'):
            discount.start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%dT%H:%M')
        else:
            discount.start_date = None
            
        if request.form.get('end_date'):
            discount.end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%dT%H:%M')
        else:
            discount.end_date = None
        
        db.session.commit()
        flash('Discount code updated successfully!', 'success')
        return redirect(url_for('admin_discounts'))
    
    return render_template('admin/discount_form.html', discount=discount)

@app.route('/admin/discounts/<int:id>/delete', methods=['POST'])
@login_required
def admin_discount_delete(id):
    discount = Discount.query.get_or_404(id)
    db.session.delete(discount)
    db.session.commit()
    flash('Discount code deleted successfully!', 'success')
    return redirect(url_for('admin_discounts'))

# Delivery zones routes
@app.route('/admin/delivery')
@login_required
def admin_delivery():
    settings = SiteSettings.query.first()
    if not settings:
        settings = SiteSettings()
        db.session.add(settings)
        db.session.commit()
    zones = DeliveryZone.query.order_by(DeliveryZone.order).all()
    return render_template('admin/delivery.html', settings=settings, zones=zones)

@app.route('/admin/delivery/settings', methods=['POST'])
@login_required
def admin_delivery_settings_update():
    settings = SiteSettings.query.first()
    if not settings:
        settings = SiteSettings()
        db.session.add(settings)
    
    settings.delivery_enabled = 'delivery_enabled' in request.form
    settings.default_delivery_fee = float(request.form.get('default_delivery_fee', 5.0))
    settings.free_delivery_threshold = float(request.form.get('free_delivery_threshold', 50.0))
    
    db.session.commit()
    flash('Delivery settings updated successfully!', 'success')
    return redirect(url_for('admin_delivery'))

@app.route('/admin/delivery/zones/new', methods=['GET', 'POST'])
@login_required
def admin_delivery_zone_new():
    if request.method == 'POST':
        zone = DeliveryZone(
            name=request.form['name'],
            postcodes=request.form['postcodes'],
            delivery_fee=float(request.form['delivery_fee']),
            min_order_amount=float(request.form.get('min_order_amount', 0)),
            estimated_delivery_time=request.form.get('estimated_delivery_time'),
            is_active='is_active' in request.form
        )
        db.session.add(zone)
        db.session.commit()
        flash('Delivery zone created successfully!', 'success')
        return redirect(url_for('admin_delivery'))
    
    return render_template('admin/delivery_zone_form.html')

@app.route('/admin/delivery/zones/<int:id>/edit', methods=['GET', 'POST'])
@login_required
def admin_delivery_zone_edit(id):
    zone = DeliveryZone.query.get_or_404(id)
    
    if request.method == 'POST':
        zone.name = request.form['name']
        zone.postcodes = request.form['postcodes']
        zone.delivery_fee = float(request.form['delivery_fee'])
        zone.min_order_amount = float(request.form.get('min_order_amount', 0))
        zone.estimated_delivery_time = request.form.get('estimated_delivery_time')
        zone.is_active = 'is_active' in request.form
        
        db.session.commit()
        flash('Delivery zone updated successfully!', 'success')
        return redirect(url_for('admin_delivery'))
    
    return render_template('admin/delivery_zone_form.html', zone=zone)

@app.route('/admin/delivery/zones/<int:id>/delete', methods=['POST'])
@login_required
def admin_delivery_zone_delete(id):
    zone = DeliveryZone.query.get_or_404(id)
    db.session.delete(zone)
    db.session.commit()
    flash('Delivery zone deleted successfully!', 'success')
    return redirect(url_for('admin_delivery'))

@app.route('/admin/availability/block-date', methods=['POST'])
@login_required
def admin_block_date():
    date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
    existing = BlockedDate.query.filter_by(date=date).first()
    if existing:
        flash('Date already blocked', 'error')
    else:
        blocked = BlockedDate(
            date=date,
            reason=request.form.get('reason')
        )
        db.session.add(blocked)
        db.session.commit()
        flash('Date blocked successfully', 'success')
    return redirect(url_for('admin_availability'))

@app.route('/admin/availability/block-date/<int:id>/delete', methods=['POST'])
@login_required
def admin_unblock_date(id):
    blocked = BlockedDate.query.get_or_404(id)
    db.session.delete(blocked)
    db.session.commit()
    flash('Date unblocked successfully', 'success')
    return redirect(url_for('admin_availability'))

@app.route('/admin/availability/block-slot', methods=['POST'])
@login_required
def admin_block_slot():
    date = datetime.strptime(request.form['date'], '%Y-%m-%d').date()
    time_slot = request.form['time_slot']
    existing = BlockedTimeSlot.query.filter_by(date=date, time_slot=time_slot).first()
    if existing:
        flash('Time slot already blocked for this date', 'error')
    else:
        blocked = BlockedTimeSlot(
            date=date,
            time_slot=time_slot,
            reason=request.form.get('reason')
        )
        db.session.add(blocked)
        db.session.commit()
        flash('Time slot blocked successfully', 'success')
    return redirect(url_for('admin_availability'))

@app.route('/admin/availability/block-slot/<int:id>/delete', methods=['POST'])
@login_required
def admin_unblock_slot(id):
    blocked = BlockedTimeSlot.query.get_or_404(id)
    db.session.delete(blocked)
    db.session.commit()
    flash('Time slot unblocked successfully', 'success')
    return redirect(url_for('admin_availability'))

@app.route('/admin/availability/settings', methods=['POST'])
@login_required
def admin_booking_settings():
    settings = BookingSettings.query.first()
    if not settings:
        settings = BookingSettings()
        db.session.add(settings)
    
    settings.max_bookings_per_slot = int(request.form.get('max_bookings_per_slot', 5))
    settings.advance_booking_days = int(request.form.get('advance_booking_days', 30))
    settings.min_advance_hours = int(request.form.get('min_advance_hours', 48))
    settings.booking_enabled = request.form.get('booking_enabled') == 'on'
    
    db.session.commit()
    flash('Booking settings updated successfully', 'success')
    return redirect(url_for('admin_availability'))

@app.route('/admin/settings', methods=['GET', 'POST'])
@login_required
def admin_settings():
    settings = SiteSettings.query.first()
    if not settings:
        settings = SiteSettings()
        db.session.add(settings)
    
    if request.method == 'POST':
        # Upload logo if provided
        if 'logo' in request.files:
            file = request.files['logo']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                settings.logo_url = f'/static/uploads/{filename}'

        # Upload entrance logo if provided
        if 'entrance_logo' in request.files:
            file = request.files['entrance_logo']
            if file and allowed_file(file.filename):
                filename = secure_filename(file.filename)
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(filepath)
                settings.entrance_logo_url = f'/static/uploads/{filename}'

        # Upload custom invoice template (HTML) if provided
        if 'invoice_template' in request.files:
            file = request.files['invoice_template']
            if file and allowed_template_file(file.filename):
                filename = secure_filename(file.filename)
                filename = f'invoice_{filename}'
                filepath = os.path.join(app.config['UPLOAD_FOLDER'], 'invoices', filename)
                file.save(filepath)
                settings.invoice_template_path = f'/static/uploads/invoices/{filename}'

        # Remove custom invoice template if requested
        if request.form.get('remove_invoice_template') == 'on':
            settings.invoice_template_path = None
        
        # Basic settings
        settings.site_title = request.form.get('site_title')
        settings.contact_email = request.form.get('contact_email')
        settings.phone = request.form.get('phone')
        settings.address = request.form.get('address')
        
        # Social media
        settings.instagram = request.form.get('instagram')
        settings.tiktok = request.form.get('tiktok')
        settings.facebook = request.form.get('facebook')
        settings.youtube = request.form.get('youtube')
        
        # Payment integrations
        settings.stripe_public_key = request.form.get('stripe_public_key')
        settings.stripe_secret_key = request.form.get('stripe_secret_key')
        settings.paypal_client_id = request.form.get('paypal_client_id')
        settings.allow_test_checkout = request.form.get('allow_test_checkout') == 'on'
        
        # Chat integrations
        settings.whatsapp_number = request.form.get('whatsapp_number')
        settings.chatway_widget = request.form.get('chatway_widget')
        settings.custom_chat_widget = request.form.get('custom_chat_widget')

        # Copy blocks
        settings.booking_heading = request.form.get('booking_heading')
        settings.booking_body = request.form.get('booking_body')
        settings.seasonal_heading = request.form.get('seasonal_heading')
        settings.seasonal_body = request.form.get('seasonal_body')
        settings.pickup_card_title = request.form.get('pickup_card_title')
        settings.pickup_card_note = request.form.get('pickup_card_note')
        settings.confirmation_title = request.form.get('confirmation_title')
        settings.confirmation_subtitle = request.form.get('confirmation_subtitle')

        # Invoicing
        settings.company_name = request.form.get('company_name')
        settings.company_vat_number = request.form.get('company_vat_number')
        settings.company_registration = request.form.get('company_registration')
        settings.company_invoice_email = request.form.get('company_invoice_email')
        settings.company_invoice_phone = request.form.get('company_invoice_phone')
        settings.company_invoice_address = request.form.get('company_invoice_address')
        settings.company_bank_name = request.form.get('company_bank_name')
        settings.company_bank_account = request.form.get('company_bank_account')
        settings.company_sort_code = request.form.get('company_sort_code')
        settings.company_iban = request.form.get('company_iban')
        settings.company_swift = request.form.get('company_swift')
        settings.invoice_notes = request.form.get('invoice_notes')

        # Entrance animation controls
        settings.entrance_enabled = request.form.get('entrance_enabled') == 'on'
        settings.entrance_title = request.form.get('entrance_title') or settings.site_title or 'Atelier Gourmand'
        settings.entrance_subtitle = request.form.get('entrance_subtitle')
        settings.entrance_description = request.form.get('entrance_description')
        settings.entrance_extra_text = request.form.get('entrance_extra_text')
        settings.entrance_duration_ms = int(request.form.get('entrance_duration_ms') or settings.entrance_duration_ms or 2000)
        settings.entrance_fade_ms = int(request.form.get('entrance_fade_ms') or settings.entrance_fade_ms or 800)
        
        db.session.commit()
        flash('Settings updated successfully', 'success')
        return redirect(url_for('admin_settings'))
    
    return render_template('admin/settings.html', settings=settings)

@app.route('/admin/orders')
@login_required
def admin_orders():
    """Admin orders list"""
    status = request.args.get('status')
    payment = request.args.get('payment')
    search = (request.args.get('search') or '').strip()
    sort = request.args.get('sort', 'desc')

    q = Order.query
    if status:
        q = q.filter(Order.status == status)
    if payment:
        q = q.filter(Order.payment_status == payment)
    if search:
        like = f"%{search}%"
        q = q.filter(
            db.or_(
                Order.order_number.ilike(like),
                Order.customer_name.ilike(like),
                Order.customer_email.ilike(like),
            )
        )

    if sort == 'asc':
        q = q.order_by(Order.created_at.asc())
    else:
        q = q.order_by(Order.created_at.desc())

    orders = q.all()
    return render_template('admin/orders.html', orders=orders, status_filter=status, payment_filter=payment, search=search, sort=sort)

@app.route('/admin/orders/<int:id>')
@login_required
def admin_order_detail(id):
    """Admin order detail"""
    order = Order.query.get_or_404(id)
    return render_template('admin/order_detail.html', order=order)


@app.route('/admin/orders/<int:id>/print')
@login_required
def admin_order_print(id):
    order = Order.query.get_or_404(id)
    settings = SiteSettings.query.first()
    currency_symbol = CURRENCY_SYMBOLS.get(order.currency or app.config['DEFAULT_CURRENCY'], '£')
    return render_template('admin/order_print.html', order=order, settings=settings, currency_symbol=currency_symbol)

@app.route('/admin/orders/<int:id>/status', methods=['POST'])
@login_required
def admin_update_order_status(id):
    """Update order status"""
    order = Order.query.get_or_404(id)
    order.status = request.form.get('status')
    order.payment_status = request.form.get('payment_status', order.payment_status)
    order.admin_notes = request.form.get('admin_notes')
    db.session.commit()
    flash('Order updated successfully!', 'success')
    return redirect(url_for('admin_order_detail', id=id))


@app.route('/admin/orders/<int:id>/cancel', methods=['POST'])
@login_required
def admin_cancel_order(id):
    order = Order.query.get_or_404(id)
    order.status = 'cancelled'
    if order.payment_status == 'paid':
        order.payment_status = 'refunded'
    db.session.commit()
    flash('Order cancelled.', 'success')
    return redirect(url_for('admin_order_detail', id=id))


@app.route('/admin/orders/<int:id>/delete', methods=['POST'])
@login_required
def admin_delete_order(id):
    order = Order.query.get_or_404(id)
    db.session.delete(order)
    db.session.commit()
    flash('Order deleted.', 'success')
    return redirect(url_for('admin_orders'))


@app.route('/admin/orders/<int:id>/invoice')
@login_required
def admin_order_invoice(id):
    order = Order.query.get_or_404(id)
    settings = SiteSettings.query.first()
    currency_symbol = CURRENCY_SYMBOLS.get(order.currency or app.config['DEFAULT_CURRENCY'], '£')
    invoice_number = order.order_number
    invoice_date = order.created_at.date()
    return render_invoice_template(order, settings, currency_symbol, invoice_number, invoice_date, for_email=False)


@app.route('/admin/orders/<int:id>/send-invoice', methods=['POST'])
@login_required
def admin_send_invoice(id):
    order = Order.query.get_or_404(id)
    try:
        html_body = build_invoice_html(order)
        body = f"Invoice {order.order_number} for your order is attached below."
        settings = SiteSettings.query.first()
        from_email = app.config.get('SMTP_FROM') or (settings.contact_email if settings else None)
        send_email(order.customer_email, f'Invoice {order.order_number}', body, from_email=from_email, html_body=html_body)
        flash('Invoice sent to customer.', 'success')
    except Exception as exc:
        flash(f'Unable to send invoice: {exc}', 'error')
    return redirect(url_for('admin_order_detail', id=id))

@app.route('/admin/products/<int:product_id>/variants', methods=['GET', 'POST'])
@login_required
def admin_product_variants(product_id):
    """Manage product variants"""
    product = Product.query.get_or_404(product_id)
    
    if request.method == 'POST':
        stock_raw = request.form.get('stock_quantity', '').strip()
        stock_value = int(stock_raw) if stock_raw != '' else None
        variant = ProductVariant(
            product_id=product_id,
            name=request.form['name'],
            price_modifier=float(request.form.get('price_modifier', 0)),
            stock_quantity=stock_value,
            sku=request.form.get('sku'),
            is_active=bool(request.form.get('is_active'))
        )
        db.session.add(variant)
        db.session.commit()
        flash('Variant added successfully!', 'success')
        return redirect(url_for('admin_product_variants', product_id=product_id))
    
    return render_template('admin/product_variants.html', product=product)

@app.route('/admin/variants/<int:id>/delete', methods=['POST'])
@login_required
def admin_delete_variant(id):
    """Delete product variant"""
    variant = ProductVariant.query.get_or_404(id)
    product_id = variant.product_id
    db.session.delete(variant)
    db.session.commit()
    flash('Variant deleted!', 'success')
    return redirect(url_for('admin_product_variants', product_id=product_id))

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Create default admin user if none exists
        if not User.query.filter_by(email=os.getenv('ADMIN_EMAIL', 'admin@ateliergourmandbyoc.co.uk')).first():
            admin = User(
                email=os.getenv('ADMIN_EMAIL', 'admin@ateliergourmandbyoc.co.uk'),
                password_hash=generate_password_hash(os.getenv('ADMIN_PASSWORD', 'admin123'))
            )
            db.session.add(admin)
            db.session.commit()
            print('Default admin user created')
        
        # Create default booking settings if none exist
        if not BookingSettings.query.first():
            settings = BookingSettings(
                max_bookings_per_slot=5,
                advance_booking_days=30,
                min_advance_hours=48,
                booking_enabled=True
            )
            db.session.add(settings)
            db.session.commit()
            print('Default booking settings created')
        
        # Create default time slots if none exist - 30min intervals over 24 hours
        if AvailableTimeSlot.query.count() == 0:
            # Generate all 48 slots (24 hours * 2 = 30min intervals)
            for hour in range(24):
                for minute in [0, 30]:
                    time_str = f"{hour:02d}:{minute:02d}"
                    order = hour * 2 + (1 if minute == 30 else 0)
                    # Default: activate slots between 08:00-20:00, deactivate others
                    is_active = (8 <= hour < 20)
                    slot = AvailableTimeSlot(time_slot=time_str, order=order, is_active=is_active)
                    db.session.add(slot)
            db.session.commit()
            print('Default time slots created (48 slots with 30min intervals)')
    
    app.run(debug=True, port=5000)
