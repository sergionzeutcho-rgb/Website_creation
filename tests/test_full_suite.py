"""Tests for authentication, CSRF, file uploads, authorization, audit logging, and webhook idempotency."""
import io
import os
import shutil
import tempfile
import unittest
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Reuse the same temp DB approach as test_payments — env vars must be set before app import
_TEMP_DIR = tempfile.mkdtemp(prefix='atelier-tests-full-')
_DB_PATH = os.path.join(_TEMP_DIR, 'test_full.db').replace('\\', '/')

# Only set DATABASE_URL if app hasn't been imported yet
if 'DATABASE_URL' not in os.environ:
    os.environ['DATABASE_URL'] = f"sqlite:///{_DB_PATH}"
os.environ.setdefault('SECRET_KEY', 'test-secret')
os.environ.setdefault('PAYMENT_BASE_URL', 'http://localhost')
os.environ.setdefault('STRIPE_PUBLIC_KEY', 'pk_test_123')
os.environ.setdefault('STRIPE_SECRET_KEY', 'sk_test_123')
os.environ.setdefault('STRIPE_WEBHOOK_SECRET', 'whsec_test')
os.environ.setdefault('PAYPAL_CLIENT_ID', 'paypal-client')
os.environ.setdefault('PAYPAL_CLIENT_SECRET', 'paypal-secret')
os.environ.setdefault('PAYPAL_WEBHOOK_ID', 'paypal-webhook')
os.environ.setdefault('RATELIMIT_STORAGE_URI', 'memory://')

import app as app_module
from models import (
    AuditLog, AvailableTimeSlot, Cart, CartItem, Customer, Order,
    Product, SiteSettings, User, WebhookEvent, db,
)
from werkzeug.security import generate_password_hash


class BaseTestCase(unittest.TestCase):
    """Shared setup for all test classes."""

    @classmethod
    def setUpClass(cls):
        app_module.app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
        )

    @classmethod
    def tearDownClass(cls):
        with app_module.app.app_context():
            db.session.remove()

    def setUp(self):
        self.app = app_module.app
        self.client = self.app.test_client()
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.create_all()

    # ── helpers ─────────────────────────────────────────────
    def _create_admin(self, email='admin@test.com', password='adminpass123'):
        with self.app.app_context():
            user = User(email=email, password_hash=generate_password_hash(password))
            db.session.add(user)
            db.session.commit()
            return user.id

    def _login_admin(self, email='admin@test.com', password='adminpass123'):
        return self.client.post('/admin/login', data={
            'email': email, 'password': password,
        }, follow_redirects=True)

    def _create_customer(self, email='cust@test.com', password='custpass123', name='Test Customer'):
        with self.app.app_context():
            c = Customer(email=email, password_hash=generate_password_hash(password), name=name)
            db.session.add(c)
            db.session.commit()
            return c.id

    def _create_product(self, name='Cake', price=10.0, active=True):
        with self.app.app_context():
            p = Product(name=name, price=price, is_active=active, slug=name.lower().replace(' ', '-'))
            db.session.add(p)
            db.session.commit()
            return p.id

    def _create_order(self, payment_method='stripe', payment_intent_id=None):
        order_number = f"ORD-TEST-{uuid.uuid4().hex[:8].upper()}"
        with self.app.app_context():
            order = Order(
                order_number=order_number,
                customer_name='Test', customer_email='t@t.com',
                customer_phone='0', pickup_date=date(2026, 3, 20),
                pickup_time='10:00', subtotal=25.0, tax=0.0,
                total=25.0, currency='GBP', fx_rate=1.0,
                payment_method=payment_method, payment_status='pending',
                status='pending', payment_intent_id=payment_intent_id,
            )
            db.session.add(order)
            db.session.commit()
        return order_number


# ════════════════════════════════════════════════════════════════
# 1. AUTHENTICATION TESTS
# ════════════════════════════════════════════════════════════════
class AdminAuthTests(BaseTestCase):

    def test_admin_login_success(self):
        self._create_admin()
        resp = self._login_admin()
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b'Dashboard', resp.data)

    def test_admin_login_wrong_password(self):
        self._create_admin()
        resp = self.client.post('/admin/login', data={
            'email': 'admin@test.com', 'password': 'wrong',
        }, follow_redirects=True)
        self.assertIn(b'Invalid email or password', resp.data)

    def test_admin_login_nonexistent_user(self):
        resp = self.client.post('/admin/login', data={
            'email': 'nobody@test.com', 'password': 'pass',
        }, follow_redirects=True)
        self.assertIn(b'Invalid email or password', resp.data)

    def test_admin_logout(self):
        self._create_admin()
        self._login_admin()
        resp = self.client.post('/admin/logout', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)


class CustomerAuthTests(BaseTestCase):

    def test_customer_register_success(self):
        resp = self.client.post('/account/register', data={
            'name': 'New User', 'email': 'new@test.com',
            'password': 'password123', 'confirm_password': 'password123',
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        with self.app.app_context():
            self.assertIsNotNone(Customer.query.filter_by(email='new@test.com').first())

    def test_customer_register_password_mismatch(self):
        resp = self.client.post('/account/register', data={
            'name': 'X', 'email': 'x@test.com',
            'password': 'password123', 'confirm_password': 'different',
        }, follow_redirects=True)
        self.assertIn(b'Passwords do not match', resp.data)

    def test_customer_register_short_password(self):
        resp = self.client.post('/account/register', data={
            'name': 'X', 'email': 'x@test.com',
            'password': 'short', 'confirm_password': 'short',
        }, follow_redirects=True)
        self.assertIn(b'at least 8 characters', resp.data)

    def test_customer_register_invalid_email(self):
        resp = self.client.post('/account/register', data={
            'name': 'X', 'email': 'not-an-email',
            'password': 'password123', 'confirm_password': 'password123',
        }, follow_redirects=True)
        self.assertIn(b'valid email', resp.data)

    def test_customer_register_duplicate_email(self):
        self._create_customer(email='dup@test.com')
        resp = self.client.post('/account/register', data={
            'name': 'X', 'email': 'dup@test.com',
            'password': 'password123', 'confirm_password': 'password123',
        }, follow_redirects=True)
        self.assertIn(b'already exists', resp.data)

    def test_customer_login_success(self):
        self._create_customer()
        resp = self.client.post('/account/login', data={
            'email': 'cust@test.com', 'password': 'custpass123',
        }, follow_redirects=False)
        # Successful login redirects (302)
        self.assertEqual(resp.status_code, 302)
        # Verify session has customer_id
        with self.client.session_transaction() as sess:
            self.assertIn('customer_id', sess)

    def test_customer_login_wrong_password(self):
        self._create_customer()
        resp = self.client.post('/account/login', data={
            'email': 'cust@test.com', 'password': 'wrong',
        }, follow_redirects=True)
        self.assertIn(b'Invalid email or password', resp.data)

    def test_customer_logout(self):
        self._create_customer()
        self.client.post('/account/login', data={
            'email': 'cust@test.com', 'password': 'custpass123',
        })
        resp = self.client.post('/account/logout', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)
        # Verify session no longer has customer_id
        with self.client.session_transaction() as sess:
            self.assertNotIn('customer_id', sess)


# ════════════════════════════════════════════════════════════════
# 2. CSRF TESTS
# ════════════════════════════════════════════════════════════════
class CSRFTests(BaseTestCase):

    def test_csrf_required_on_admin_login_when_enabled(self):
        """With CSRF enabled, missing token returns a redirect (CSRF error handler)."""
        self.app.config['WTF_CSRF_ENABLED'] = True
        try:
            self._create_admin()
            resp = self.client.post('/admin/login', data={
                'email': 'admin@test.com', 'password': 'adminpass123',
            })
            # CSRF handler redirects or returns 400
            self.assertIn(resp.status_code, (302, 400))
        finally:
            self.app.config['WTF_CSRF_ENABLED'] = False

    def test_csrf_exempt_on_stripe_webhook(self):
        """Stripe webhook should work without CSRF token even when CSRF is on."""
        self.app.config['WTF_CSRF_ENABLED'] = True
        try:
            with patch.object(app_module.stripe.Webhook, 'construct_event', return_value={
                'id': 'evt_ignored', 'type': 'unknown', 'data': {'object': {}},
            }):
                resp = self.client.post('/webhooks/stripe', data='{}',
                                        headers={'Stripe-Signature': 'sig'})
            self.assertEqual(resp.status_code, 200)
        finally:
            self.app.config['WTF_CSRF_ENABLED'] = False

    def test_csrf_exempt_on_paypal_webhook(self):
        self.app.config['WTF_CSRF_ENABLED'] = True
        try:
            with patch.object(app_module, 'verify_paypal_webhook', return_value=True):
                resp = self.client.post('/webhooks/paypal', json={
                    'event_type': 'UNKNOWN', 'resource': {},
                })
            self.assertEqual(resp.status_code, 200)
        finally:
            self.app.config['WTF_CSRF_ENABLED'] = False


# ════════════════════════════════════════════════════════════════
# 3. AUTHORIZATION TESTS
# ════════════════════════════════════════════════════════════════
class AuthorizationTests(BaseTestCase):

    def test_admin_dashboard_requires_login(self):
        resp = self.client.get('/admin', follow_redirects=False)
        self.assertIn(resp.status_code, (301, 302))

    def test_admin_products_requires_login(self):
        resp = self.client.get('/admin/products', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)

    def test_admin_orders_requires_login(self):
        resp = self.client.get('/admin/orders', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)

    def test_admin_settings_requires_login(self):
        resp = self.client.get('/admin/settings', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)

    def test_admin_product_new_requires_login(self):
        resp = self.client.post('/admin/products/new', data={'name': 'x', 'price': '5'},
                                follow_redirects=False)
        self.assertEqual(resp.status_code, 302)

    def test_admin_accessible_after_login(self):
        self._create_admin()
        self._login_admin()
        resp = self.client.get('/admin/products')
        self.assertEqual(resp.status_code, 200)

    def test_customer_cannot_access_admin(self):
        """A logged-in customer session should NOT grant access to admin routes."""
        self._create_customer()
        self.client.post('/account/login', data={
            'email': 'cust@test.com', 'password': 'custpass123',
        })
        resp = self.client.get('/admin/products', follow_redirects=False)
        self.assertEqual(resp.status_code, 302)


# ════════════════════════════════════════════════════════════════
# 4. FILE UPLOAD TESTS
# ════════════════════════════════════════════════════════════════
class FileUploadTests(BaseTestCase):

    def test_product_image_upload_allowed_extension(self):
        self._create_admin()
        self._login_admin()
        data = {
            'name': 'Upload Test',
            'price': '10',
            'image': (io.BytesIO(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100), 'test.png'),
        }
        resp = self.client.post('/admin/products/new', data=data,
                                content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        with self.app.app_context():
            product = Product.query.filter_by(name='Upload Test').first()
            self.assertIsNotNone(product)
            self.assertIn('.png', product.image_url or '')

    def test_product_image_upload_rejected_extension(self):
        self._create_admin()
        self._login_admin()
        data = {
            'name': 'Bad Upload',
            'price': '10',
            'image': (io.BytesIO(b'fake exe content'), 'malware.exe'),
        }
        resp = self.client.post('/admin/products/new', data=data,
                                content_type='multipart/form-data', follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        with self.app.app_context():
            product = Product.query.filter_by(name='Bad Upload').first()
            self.assertIsNotNone(product)
            # image_url should be None because .exe is not allowed
            self.assertIsNone(product.image_url)

    def test_product_creation_without_image(self):
        self._create_admin()
        self._login_admin()
        resp = self.client.post('/admin/products/new', data={
            'name': 'No Image', 'price': '5',
        }, follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        with self.app.app_context():
            self.assertIsNotNone(Product.query.filter_by(name='No Image').first())


# ════════════════════════════════════════════════════════════════
# 5. AUDIT LOGGING TESTS
# ════════════════════════════════════════════════════════════════
class AuditLogTests(BaseTestCase):

    def test_admin_login_creates_audit_entry(self):
        self._create_admin()
        self._login_admin()
        with self.app.app_context():
            entry = AuditLog.query.filter_by(action='admin.login').first()
            self.assertIsNotNone(entry)
            self.assertEqual(entry.user_email, 'admin@test.com')

    def test_product_create_audit_entry(self):
        self._create_admin()
        self._login_admin()
        self.client.post('/admin/products/new', data={
            'name': 'Audit Cake', 'price': '10',
        })
        with self.app.app_context():
            entry = AuditLog.query.filter_by(action='product.create').first()
            self.assertIsNotNone(entry)
            self.assertEqual(entry.target_type, 'Product')
            self.assertIn('Audit Cake', entry.details)

    def test_product_delete_audit_entry(self):
        self._create_admin()
        self._login_admin()
        pid = self._create_product(name='Delete Me')
        self.client.post(f'/admin/products/{pid}/delete')
        with self.app.app_context():
            entry = AuditLog.query.filter_by(action='product.delete').first()
            self.assertIsNotNone(entry)
            self.assertEqual(entry.target_id, pid)

    def test_order_cancel_audit_entry(self):
        self._create_admin()
        self._login_admin()
        order_number = self._create_order()
        with self.app.app_context():
            order = Order.query.filter_by(order_number=order_number).first()
            oid = order.id
        self.client.post(f'/admin/orders/{oid}/cancel')
        with self.app.app_context():
            entry = AuditLog.query.filter_by(action='order.cancel').first()
            self.assertIsNotNone(entry)


# ════════════════════════════════════════════════════════════════
# 6. WEBHOOK IDEMPOTENCY TESTS
# ════════════════════════════════════════════════════════════════
class WebhookIdempotencyTests(BaseTestCase):

    def test_stripe_duplicate_webhook_is_ignored(self):
        order_number = self._create_order('stripe')
        event = {
            'id': 'evt_test_dedup_001',
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'metadata': {'order_number': order_number},
                    'payment_intent': 'pi_dedup_123',
                }
            },
        }
        with patch.object(app_module.stripe.Webhook, 'construct_event', return_value=event):
            resp1 = self.client.post('/webhooks/stripe', data='{}',
                                     headers={'Stripe-Signature': 'sig'})
            self.assertEqual(resp1.status_code, 200)
            resp2 = self.client.post('/webhooks/stripe', data='{}',
                                     headers={'Stripe-Signature': 'sig'})
            self.assertEqual(resp2.status_code, 200)
            self.assertIn(b'already_processed', resp2.data)

        with self.app.app_context():
            events = WebhookEvent.query.filter_by(event_id='evt_test_dedup_001').all()
            self.assertEqual(len(events), 1)

    def test_paypal_duplicate_webhook_is_ignored(self):
        order_number = self._create_order('paypal', payment_intent_id='PP-ORDER-DEDUP')
        event = {
            'id': 'WH-TEST-DEDUP-001',
            'event_type': 'PAYMENT.CAPTURE.COMPLETED',
            'resource': {
                'id': 'CAPTURE-1',
                'supplementary_data': {
                    'related_ids': {'order_id': 'PP-ORDER-DEDUP'}
                },
            },
        }
        with patch.object(app_module, 'verify_paypal_webhook', return_value=True):
            resp1 = self.client.post('/webhooks/paypal', json=event)
            self.assertEqual(resp1.status_code, 200)
            resp2 = self.client.post('/webhooks/paypal', json=event)
            self.assertEqual(resp2.status_code, 200)
            self.assertIn(b'already_processed', resp2.data)

    def test_stripe_webhook_records_event(self):
        order_number = self._create_order('stripe')
        event = {
            'id': 'evt_test_record_001',
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'metadata': {'order_number': order_number},
                    'payment_intent': 'pi_rec_123',
                }
            },
        }
        with patch.object(app_module.stripe.Webhook, 'construct_event', return_value=event):
            self.client.post('/webhooks/stripe', data='{}',
                             headers={'Stripe-Signature': 'sig'})
        with self.app.app_context():
            we = WebhookEvent.query.filter_by(event_id='evt_test_record_001').first()
            self.assertIsNotNone(we)
            self.assertEqual(we.provider, 'stripe')
            self.assertEqual(we.event_type, 'checkout.session.completed')

    def test_already_paid_order_not_double_processed(self):
        """A webhook for an already-paid order should not re-trigger state change."""
        order_number = self._create_order('stripe')
        # Mark as already paid
        with self.app.app_context():
            order = Order.query.filter_by(order_number=order_number).first()
            order.payment_status = 'paid'
            order.status = 'confirmed'
            db.session.commit()

        event = {
            'id': 'evt_already_paid',
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'metadata': {'order_number': order_number},
                    'payment_intent': 'pi_should_not_overwrite',
                }
            },
        }
        with patch.object(app_module.stripe.Webhook, 'construct_event', return_value=event):
            self.client.post('/webhooks/stripe', data='{}',
                             headers={'Stripe-Signature': 'sig'})
        with self.app.app_context():
            order = Order.query.filter_by(order_number=order_number).first()
            # payment_intent_id should NOT have been overwritten since order was already confirmed
            self.assertNotEqual(order.payment_intent_id, 'pi_should_not_overwrite')


# ════════════════════════════════════════════════════════════════
# 7. ERROR HANDLER TESTS
# ════════════════════════════════════════════════════════════════
class ErrorHandlerTests(BaseTestCase):

    def test_404_page(self):
        resp = self.client.get('/nonexistent-page-xyz')
        self.assertEqual(resp.status_code, 404)
        self.assertIn(b'404', resp.data)

    def test_404_json(self):
        resp = self.client.get('/nonexistent-page-xyz',
                               headers={'Accept': 'application/json'})
        self.assertEqual(resp.status_code, 404)
        self.assertIn(b'Not found', resp.data)


# ════════════════════════════════════════════════════════════════
# 8. SECURITY HEADER TESTS
# ════════════════════════════════════════════════════════════════
class SecurityHeaderTests(BaseTestCase):

    def test_security_headers_present(self):
        resp = self.client.get('/')
        self.assertEqual(resp.headers.get('X-Content-Type-Options'), 'nosniff')
        self.assertEqual(resp.headers.get('X-Frame-Options'), 'DENY')
        self.assertIn('strict-origin', resp.headers.get('Referrer-Policy', ''))
        self.assertIn('default-src', resp.headers.get('Content-Security-Policy', ''))

    def test_permissions_policy_header(self):
        resp = self.client.get('/')
        self.assertIn('geolocation=()', resp.headers.get('Permissions-Policy', ''))


if __name__ == '__main__':
    unittest.main()
