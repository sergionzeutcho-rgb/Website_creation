from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    short_description = db.Column(db.Text)  # Short description for cards
    full_description = db.Column(db.Text)  # Rich HTML content for product page
    price = db.Column(db.Float)
    image_url = db.Column(db.String(500))
    is_active = db.Column(db.Boolean, default=True)
    order = db.Column(db.Integer, default=0)
    
    # Inventory management
    track_inventory = db.Column(db.Boolean, default=False)
    stock_quantity = db.Column(db.Integer, default=0)
    allow_backorder = db.Column(db.Boolean, default=False)
    
    # SEO
    slug = db.Column(db.String(250), unique=True)  # URL-friendly name
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    variants = db.relationship('ProductVariant', backref='product', lazy=True, cascade='all, delete-orphan')
    images = db.relationship('ProductImage', backref='product', lazy=True, cascade='all, delete-orphan')

class ProductVariant(db.Model):
    """Product variants (e.g., sizes, flavors, etc.)"""
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)  # e.g., "Small", "Large", "Chocolate"
    price_modifier = db.Column(db.Float, default=0.0)  # Add/subtract from base price
    stock_quantity = db.Column(db.Integer, default=0)
    sku = db.Column(db.String(100))  # Stock Keeping Unit
    is_active = db.Column(db.Boolean, default=True)
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class ProductImage(db.Model):
    """Additional product images"""
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    image_url = db.Column(db.String(500), nullable=False)
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Cart(db.Model):
    """Shopping cart - can be session-based or user-based"""
    id = db.Column(db.Integer, primary_key=True)
    session_id = db.Column(db.String(100))  # For guest users
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)  # For logged-in users
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    items = db.relationship('CartItem', backref='cart', lazy=True, cascade='all, delete-orphan')

class CartItem(db.Model):
    """Items in shopping cart"""
    id = db.Column(db.Integer, primary_key=True)
    cart_id = db.Column(db.Integer, db.ForeignKey('cart.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variant.id'), nullable=True)
    quantity = db.Column(db.Integer, default=1)
    price_at_add = db.Column(db.Float, nullable=False)  # Store price when added to cart
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    product = db.relationship('Product', backref='cart_items')
    variant = db.relationship('ProductVariant', backref='cart_items')

class Order(db.Model):
    """Customer orders"""
    id = db.Column(db.Integer, primary_key=True)
    order_number = db.Column(db.String(50), unique=True, nullable=False)
    
    # Customer info
    customer_name = db.Column(db.String(200), nullable=False)
    customer_email = db.Column(db.String(120), nullable=False)
    customer_phone = db.Column(db.String(50))
    
    # Delivery/Pickup info
    fulfillment_method = db.Column(db.String(20), default='pickup')  # 'pickup' or 'delivery'
    pickup_date = db.Column(db.Date, nullable=False)
    pickup_time = db.Column(db.String(20), nullable=False)
    delivery_address = db.Column(db.Text)  # For delivery orders
    delivery_postcode = db.Column(db.String(20))  # For delivery zone pricing
    delivery_fee = db.Column(db.Float, default=0.0)
    
    # Order totals
    subtotal = db.Column(db.Float, nullable=False)
    discount_code = db.Column(db.String(50))  # Applied discount code
    discount_amount = db.Column(db.Float, default=0.0)  # Discount amount
    tax = db.Column(db.Float, default=0.0)
    total = db.Column(db.Float, nullable=False)
    
    # Payment
    payment_method = db.Column(db.String(50))  # stripe, paypal, cash_on_pickup
    payment_status = db.Column(db.String(50), default='pending')  # pending, paid, failed, refunded
    payment_intent_id = db.Column(db.String(200))  # Stripe payment intent ID
    
    # Order status
    status = db.Column(db.String(50), default='pending')  # pending, confirmed, preparing, ready, completed, cancelled
    notes = db.Column(db.Text)
    admin_notes = db.Column(db.Text)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    items = db.relationship('OrderItem', backref='order', lazy=True, cascade='all, delete-orphan')

class OrderItem(db.Model):
    """Items in an order"""
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey('order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    variant_id = db.Column(db.Integer, db.ForeignKey('product_variant.id'), nullable=True)
    
    product_name = db.Column(db.String(200), nullable=False)  # Store name at time of order
    variant_name = db.Column(db.String(100))
    quantity = db.Column(db.Integer, nullable=False)
    unit_price = db.Column(db.Float, nullable=False)
    total_price = db.Column(db.Float, nullable=False)
    
    product = db.relationship('Product', backref='order_items')
    variant = db.relationship('ProductVariant', backref='order_items')

class HeroSection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.Text)  # Rich HTML content
    subtitle = db.Column(db.Text)  # Rich HTML content
    description = db.Column(db.Text)  # Rich HTML content
    image_url = db.Column(db.String(500))
    video_url = db.Column(db.String(500))  # New: Support for video
    media_type = db.Column(db.String(20), default='image')  # 'image' or 'video'
    location = db.Column(db.String(200))
    hours = db.Column(db.String(200))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class MaisonSection(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.Text)  # Rich HTML content
    description = db.Column(db.Text)  # Rich HTML content
    image_url = db.Column(db.String(500))
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Booking(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    pickup_date = db.Column(db.Date, nullable=False)
    pickup_time = db.Column(db.String(20), nullable=False)
    email = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(50))
    notes = db.Column(db.Text)
    status = db.Column(db.String(20), default='pending')  # pending, confirmed, cancelled
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class AvailableTimeSlot(db.Model):
    """Define available time slots for bookings"""
    id = db.Column(db.Integer, primary_key=True)
    time_slot = db.Column(db.String(20), nullable=False, unique=True)  # e.g., "09:00", "10:30"
    is_active = db.Column(db.Boolean, default=True)
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class BlockedDate(db.Model):
    """Block entire days (holidays, vacations, etc.)"""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False, unique=True)
    reason = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class BlockedTimeSlot(db.Model):
    """Block specific time slots on specific dates"""
    id = db.Column(db.Integer, primary_key=True)
    date = db.Column(db.Date, nullable=False)
    time_slot = db.Column(db.String(20), nullable=False)
    reason = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    __table_args__ = (db.UniqueConstraint('date', 'time_slot', name='_date_time_uc'),)

class BookingSettings(db.Model):
    """Global booking settings"""
    id = db.Column(db.Integer, primary_key=True)
    max_bookings_per_slot = db.Column(db.Integer, default=5)
    advance_booking_days = db.Column(db.Integer, default=30)  # How many days in advance customers can book
    min_advance_hours = db.Column(db.Integer, default=48)  # Minimum hours before pickup
    booking_enabled = db.Column(db.Boolean, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class SiteSettings(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    site_title = db.Column(db.String(200))
    logo_url = db.Column(db.String(500))  # New: Custom logo
    contact_email = db.Column(db.String(120))
    phone = db.Column(db.String(50))
    address = db.Column(db.Text)
    # Social media links
    instagram = db.Column(db.String(200))
    tiktok = db.Column(db.String(200))  # New
    facebook = db.Column(db.String(200))  # New
    youtube = db.Column(db.String(200))  # New
    # API Integrations
    stripe_public_key = db.Column(db.String(200))  # New
    stripe_secret_key = db.Column(db.String(200))  # New
    paypal_client_id = db.Column(db.String(200))  # New
    whatsapp_number = db.Column(db.String(50))  # New
    chatway_widget = db.Column(db.Text)  # New: Widget embed code
    custom_chat_widget = db.Column(db.Text)  # New: Any custom chat widget
    # Delivery settings
    delivery_enabled = db.Column(db.Boolean, default=False)
    default_delivery_fee = db.Column(db.Float, default=5.0)
    free_delivery_threshold = db.Column(db.Float, default=50.0)  # Free delivery over this amount
    # Language settings
    default_language = db.Column(db.String(10), default='en')  # en, fr
    enable_auto_translate = db.Column(db.Boolean, default=True)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class NavigationItem(db.Model):
    """Navigation menu items"""
    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(100), nullable=False)  # e.g., "Click & Collect"
    url = db.Column(db.String(500), nullable=False)  # e.g., "#collect" or "/shop"
    is_cta = db.Column(db.Boolean, default=False)  # Call-to-action button style
    is_active = db.Column(db.Boolean, default=True)
    order = db.Column(db.Integer, default=0)
    target = db.Column(db.String(20), default='_self')  # _self or _blank
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Discount(db.Model):
    """Discount codes and promotions"""
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(50), unique=True, nullable=False)  # e.g., "WELCOME10"
    description = db.Column(db.String(200))
    
    # Discount type and value
    discount_type = db.Column(db.String(20), nullable=False)  # 'percentage' or 'fixed'
    discount_value = db.Column(db.Float, nullable=False)  # e.g., 10 for 10% or £10
    
    # Conditions
    min_order_amount = db.Column(db.Float, default=0.0)  # Minimum order to apply
    max_discount_amount = db.Column(db.Float)  # Max discount for percentage type
    applies_to = db.Column(db.String(20), default='order')  # 'order' or 'product'
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=True)  # For product-specific
    
    # Free delivery
    free_delivery = db.Column(db.Boolean, default=False)  # If true, delivery is free
    
    # Usage limits
    usage_limit = db.Column(db.Integer)  # Total uses allowed (null = unlimited)
    usage_count = db.Column(db.Integer, default=0)  # Current usage count
    per_customer_limit = db.Column(db.Integer, default=1)  # Uses per customer
    
    # Validity
    is_active = db.Column(db.Boolean, default=True)
    start_date = db.Column(db.DateTime)
    end_date = db.Column(db.DateTime)
    
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class DeliveryZone(db.Model):
    """Delivery zones with custom pricing"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)  # e.g., "Central London"
    postcodes = db.Column(db.Text)  # Comma-separated postcodes or prefixes (e.g., "SW1, SW2, W1")
    delivery_fee = db.Column(db.Float, nullable=False)
    min_order_amount = db.Column(db.Float, default=0.0)
    estimated_delivery_time = db.Column(db.String(50))  # e.g., "30-45 mins"
    is_active = db.Column(db.Boolean, default=True)
    order = db.Column(db.Integer, default=0)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

