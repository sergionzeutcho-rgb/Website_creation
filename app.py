import os
import uuid
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_from_directory, session
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_ckeditor import CKEditor
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
from datetime import datetime, date
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'dev-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL', 'sqlite:///atelier.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = os.getenv('UPLOAD_FOLDER', 'static/uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

# Allowed extensions for uploads
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'mp4', 'mov', 'avi'}

# Import db from models and initialize with app
from models import (db, User, Product, ProductVariant, ProductImage, HeroSection, MaisonSection, 
                    Booking, SiteSettings, AvailableTimeSlot, BlockedDate, BlockedTimeSlot, BookingSettings,
                    Cart, CartItem, Order, OrderItem, NavigationItem, Discount, DeliveryZone)

db.init_app(app)
ckeditor = CKEditor(app)

login_manager = LoginManager(app)
login_manager.login_view = 'admin_login'

# Ensure upload folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'products'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'hero'), exist_ok=True)
os.makedirs(os.path.join(app.config['UPLOAD_FOLDER'], 'maison'), exist_ok=True)

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

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

@app.context_processor
def inject_cart_count():
    """Make cart count available in all templates"""
    cart_count = 0
    if 'cart_id' in session:
        cart = Cart.query.get(session['cart_id'])
        if cart:
            cart_count = sum(item.quantity for item in cart.items)
    return {'cart_count': cart_count}

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Public routes
@app.route('/')
def index():
    hero = HeroSection.query.first()
    products = Product.query.filter_by(is_active=True).order_by(Product.order).all()
    maison = MaisonSection.query.first()
    settings = SiteSettings.query.first()
    nav_items = NavigationItem.query.filter_by(is_active=True).order_by(NavigationItem.order).all()
    return render_template('index.html', hero=hero, products=products, maison=maison, settings=settings, nav_items=nav_items)

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
    return jsonify({'message': 'Booking confirmed', 'id': booking.id}), 201

@app.route('/api/available-slots')
def api_available_slots():
    """Get available time slots sorted chronologically"""
    slots = AvailableTimeSlot.query.filter_by(is_active=True).order_by(AvailableTimeSlot.time_slot).all()
    return jsonify([{'time': slot.time_slot} for slot in slots])

# E-commerce routes
@app.route('/product/<slug>')
def product_detail(slug):
    """Product detail page"""
    # Try with slug first, fallback to ID for backwards compatibility
    product = Product.query.filter_by(is_active=True).filter(
        (Product.slug == slug) | (Product.id == slug)
    ).first_or_404()
    settings = SiteSettings.query.first()
    return render_template('product_detail.html', product=product, settings=settings)

@app.route('/cart')
def view_cart():
    """View shopping cart"""
    cart = get_or_create_cart()
    settings = SiteSettings.query.first()
    subtotal = sum(item.quantity * item.price_at_add for item in cart.items)
    return render_template('cart.html', cart=cart, subtotal=subtotal, settings=settings)

@app.route('/cart/add', methods=['POST'])
def add_to_cart():
    """Add product to cart"""
    try:
        product_id = request.form.get('product_id', type=int)
        variant_id = request.form.get('variant_id', type=int) if request.form.get('variant_id') else None
        quantity = request.form.get('quantity', 1, type=int)
        
        product = Product.query.get_or_404(product_id)
        variant = ProductVariant.query.get(variant_id) if variant_id else None
        
        price = product.price
        if variant and variant.price_modifier:
            price += variant.price_modifier
        
        cart = get_or_create_cart()
        
        existing_item = CartItem.query.filter_by(
            cart_id=cart.id,
            product_id=product_id,
            variant_id=variant_id
        ).first()
        
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
        return redirect(request.referrer or url_for('index'))
    except Exception as e:
        flash(f'Error adding to cart: {str(e)}', 'error')
        return redirect(request.referrer or url_for('index'))

@app.route('/cart/update/<int:item_id>', methods=['POST'])
def update_cart_item(item_id):
    """Update cart item quantity"""
    try:
        quantity = request.form.get('quantity', 1, type=int)
        cart_item = CartItem.query.get_or_404(item_id)
        
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
        cart_item = CartItem.query.get_or_404(item_id)
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
    
    if not cart.items:
        flash('Your cart is empty!', 'warning')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        try:
            customer_name = request.form.get('name')
            customer_email = request.form.get('email')
            customer_phone = request.form.get('phone')
            pickup_date = datetime.strptime(request.form.get('pickup_date'), '%Y-%m-%d').date()
            pickup_time = request.form.get('pickup_time')
            notes = request.form.get('notes')
            payment_method = request.form.get('payment_method', 'cash_on_pickup')
            
            subtotal = sum(item.quantity * item.price_at_add for item in cart.items)
            tax = 0
            total = subtotal + tax
            
            order_number = f"ORD-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
            
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
                payment_method=payment_method,
                payment_status='pending' if payment_method == 'cash_on_pickup' else 'pending',
                status='pending',
                notes=notes
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
            
            for item in cart.items:
                db.session.delete(item)
            
            db.session.commit()
            session.pop('cart_id', None)
            
            flash(f'Order {order_number} placed successfully!', 'success')
            return redirect(url_for('order_confirmation', order_number=order_number))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error processing order: {str(e)}', 'error')
            return redirect(url_for('checkout'))
    
    settings = SiteSettings.query.first()
    booking_settings = BookingSettings.query.first()
    time_slots = AvailableTimeSlot.query.filter_by(is_active=True).order_by(AvailableTimeSlot.time_slot).all()
    
    subtotal = sum(item.quantity * item.price_at_add for item in cart.items)
    tax = 0
    total = subtotal + tax
    
    return render_template('checkout.html', 
                         cart=cart, 
                         subtotal=subtotal, 
                         tax=tax, 
                         total=total,
                         settings=settings,
                         booking_settings=booking_settings,
                         time_slots=time_slots)

@app.route('/order/<order_number>')
def order_confirmation(order_number):
    """Order confirmation page"""
    order = Order.query.filter_by(order_number=order_number).first_or_404()
    settings = SiteSettings.query.first()
    return render_template('order_confirmation.html', order=order, settings=settings)

# Admin routes
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

@app.route('/admin/logout')
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
        
        # Basic settings
        settings.site_title = request.form['site_title']
        settings.contact_email = request.form['contact_email']
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
        
        # Chat integrations
        settings.whatsapp_number = request.form.get('whatsapp_number')
        settings.chatway_widget = request.form.get('chatway_widget')
        settings.custom_chat_widget = request.form.get('custom_chat_widget')
        
        db.session.commit()
        flash('Settings updated successfully', 'success')
        return redirect(url_for('admin_settings'))
    
    return render_template('admin/settings.html', settings=settings)

@app.route('/admin/orders')
@login_required
def admin_orders():
    """Admin orders list"""
    orders = Order.query.order_by(Order.created_at.desc()).all()
    return render_template('admin/orders.html', orders=orders)

@app.route('/admin/orders/<int:id>')
@login_required
def admin_order_detail(id):
    """Admin order detail"""
    order = Order.query.get_or_404(id)
    return render_template('admin/order_detail.html', order=order)

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

@app.route('/admin/products/<int:product_id>/variants', methods=['GET', 'POST'])
@login_required
def admin_product_variants(product_id):
    """Manage product variants"""
    product = Product.query.get_or_404(product_id)
    
    if request.method == 'POST':
        variant = ProductVariant(
            product_id=product_id,
            name=request.form['name'],
            price_modifier=float(request.form.get('price_modifier', 0)),
            stock_quantity=int(request.form.get('stock_quantity', 0)),
            sku=request.form.get('sku'),
            is_active=request.form.get('is_active') == 'on'
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
