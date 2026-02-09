"""
E-commerce routes to add to app.py
This includes:
- Product detail pages
- Shopping cart (add, update, remove)
- Checkout
- Order management
"""

# Add these imports to the top of app.py:
# from flask import session
# from flask_ckeditor import CKEditor
# from models import ProductVariant, ProductImage, Cart, CartItem, Order, OrderItem
# import uuid
# from datetime import date

# Initialize CKEditor (add after db.init_app(app)):
# ckeditor = CKEditor(app)

# Helper function to get or create cart
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

# Add context processor for cart count (add after login_manager setup):
@app.context_processor
def inject_cart_count():
    """Make cart count available in all templates"""
    cart_count = 0
    if 'cart_id' in session:
        cart = Cart.query.get(session['cart_id'])
        if cart:
            cart_count = sum(item.quantity for item in cart.items)
    return {'cart_count': cart_count}

# === PUBLIC ROUTES ===

@app.route('/product/<slug>')
def product_detail(slug):
    """Product detail page"""
    product = Product.query.filter_by(slug=slug, is_active=True).first_or_404()
    settings = SiteSettings.query.first()
    return render_template('product_detail.html', product=product, settings=settings)

@app.route('/cart')
def view_cart():
    """View shopping cart"""
    cart = get_or_create_cart()
    settings = SiteSettings.query.first()
    
    # Calculate totals
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
        
        # Calculate price
        price = product.price
        if variant and variant.price_modifier:
            price += variant.price_modifier
        
        # Get or create cart
        cart = get_or_create_cart()
        
        # Check if item already in cart
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
            # Get form data
            customer_name = request.form.get('name')
            customer_email = request.form.get('email')
            customer_phone = request.form.get('phone')
            pickup_date = datetime.strptime(request.form.get('pickup_date'), '%Y-%m-%d').date()
            pickup_time = request.form.get('pickup_time')
            notes = request.form.get('notes')
            payment_method = request.form.get('payment_method', 'cash_on_pickup')
            
            # Calculate totals
            subtotal = sum(item.quantity * item.price_at_add for item in cart.items)
            tax = 0  # Can add tax calculation here
            total = subtotal + tax
            
            # Generate order number
            order_number = f"ORD-{datetime.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:8].upper()}"
            
            # Create order
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
                payment_status='pending',
                status='pending',
                notes=notes
            )
            db.session.add(order)
            db.session.flush()  # Get order ID
            
            # Create order items from cart
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
            
            # Clear cart
            for item in cart.items:
                db.session.delete(item)
            
            db.session.commit()
            
            # Clear session cart
            session.pop('cart_id', None)
            
            flash(f'Order {order_number} placed successfully!', 'success')
            return redirect(url_for('order_confirmation', order_number=order_number))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error processing order: {str(e)}', 'error')
            return redirect(url_for('checkout'))
    
    # GET request - show checkout form
    settings = SiteSettings.query.first()
    booking_settings = BookingSettings.query.first()
    time_slots = AvailableTimeSlot.query.filter_by(is_active=True).order_by(AvailableTimeSlot.order).all()
    
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

# === ADMIN ROUTES FOR ORDERS ===

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
    order.admin_notes = request.form.get('admin_notes')
    db.session.commit()
    flash('Order updated successfully!', 'success')
    return redirect(url_for('admin_order_detail', id=id))

# === ADMIN ROUTES FOR PRODUCT VARIANTS ===

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
