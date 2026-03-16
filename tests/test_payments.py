import os
import shutil
import tempfile
import unittest
import uuid
from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


_TEMP_DIR = tempfile.mkdtemp(prefix='atelier-tests-')
_DB_PATH = os.path.join(_TEMP_DIR, 'test.db').replace('\\', '/')

os.environ['DATABASE_URL'] = f"sqlite:///{_DB_PATH}"
os.environ['SECRET_KEY'] = 'test-secret'
os.environ['PAYMENT_BASE_URL'] = 'http://localhost'
os.environ['STRIPE_PUBLIC_KEY'] = 'pk_test_123'
os.environ['STRIPE_SECRET_KEY'] = 'sk_test_123'
os.environ['STRIPE_WEBHOOK_SECRET'] = 'whsec_test'
os.environ['PAYPAL_CLIENT_ID'] = 'paypal-client'
os.environ['PAYPAL_CLIENT_SECRET'] = 'paypal-secret'
os.environ['PAYPAL_WEBHOOK_ID'] = 'paypal-webhook'
os.environ['RATELIMIT_STORAGE_URI'] = 'memory://'

import app as app_module
from models import AvailableTimeSlot, Cart, CartItem, Order, Product, SiteSettings, db


class PaymentFlowTests(unittest.TestCase):
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
            db.drop_all()
            db.engine.dispose()
        shutil.rmtree(_TEMP_DIR, ignore_errors=True)

    def setUp(self):
        self.app = app_module.app
        self.app.config.update(
            TESTING=True,
            WTF_CSRF_ENABLED=False,
            STRIPE_PUBLIC_KEY='pk_test_123',
            STRIPE_SECRET_KEY='sk_test_123',
            STRIPE_WEBHOOK_SECRET='whsec_test',
            PAYPAL_CLIENT_ID='paypal-client',
            PAYPAL_CLIENT_SECRET='paypal-secret',
            PAYPAL_WEBHOOK_ID='paypal-webhook',
            PAYMENT_BASE_URL='http://localhost',
            RATELIMIT_STORAGE_URI='memory://',
        )

        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.create_all()

            settings = SiteSettings(
                site_title='Test Atelier',
                stripe_public_key='pk_test_123',
                allow_test_checkout=False,
            )
            slot = AvailableTimeSlot(time_slot='10:00', is_active=True, order=1)
            product = Product(
                name='Test Cake',
                short_description='Test description',
                price=12.50,
                is_active=True,
                slug='test-cake',
            )
            db.session.add_all([settings, slot, product])
            db.session.flush()

            cart = Cart(session_id='test-cart')
            db.session.add(cart)
            db.session.flush()

            item = CartItem(
                cart_id=cart.id,
                product_id=product.id,
                quantity=2,
                price_at_add=product.price,
            )
            db.session.add(item)
            db.session.commit()

            self.cart_id = cart.id

        self.client = self.app.test_client()
        with self.client.session_transaction() as session:
            session['cart_id'] = self.cart_id

    def _checkout_form(self, payment_method):
        return {
            'name': 'Test Customer',
            'email': 'customer@example.com',
            'phone': '0123456789',
            'pickup_date': '2026-03-20',
            'pickup_time': '10:00',
            'payment_method': payment_method,
            'fulfillment_method': 'pickup',
        }

    def _create_order(self, payment_method, payment_intent_id=None):
        order_number = f"ORD-TEST-{uuid.uuid4().hex[:8].upper()}"
        with self.app.app_context():
            order = Order(
                order_number=order_number,
                customer_name='Test Customer',
                customer_email='customer@example.com',
                customer_phone='0123456789',
                pickup_date=date(2026, 3, 20),
                pickup_time='10:00',
                subtotal=25.00,
                tax=0.0,
                total=25.00,
                currency='GBP',
                fx_rate=1.0,
                payment_method=payment_method,
                payment_status='pending',
                status='pending',
                payment_intent_id=payment_intent_id,
            )
            db.session.add(order)
            db.session.commit()
        return order_number

    def test_stripe_checkout_redirects_to_checkout_session(self):
        session_obj = MagicMock()
        session_obj.url = 'https://checkout.stripe.test/session'
        session_obj.get.side_effect = lambda key, default=None: {
            'payment_intent': 'pi_test_123',
        }.get(key, default)

        with patch.object(app_module.stripe.checkout.Session, 'create', return_value=session_obj) as create_session:
            response = self.client.post('/checkout', data=self._checkout_form('stripe'), follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['Location'], 'https://checkout.stripe.test/session')
        self.assertIn('session_id={CHECKOUT_SESSION_ID}', create_session.call_args.kwargs['success_url'])
        self.assertIn('payment_intent_data', create_session.call_args.kwargs)

        with self.app.app_context():
            order = Order.query.one()
            self.assertEqual(order.payment_method, 'stripe')
            self.assertEqual(order.payment_intent_id, 'pi_test_123')

    def test_paypal_checkout_redirects_to_approval_url(self):
        fake_link = SimpleNamespace(rel='approve', href='https://paypal.test/approve')
        fake_result = SimpleNamespace(id='PAYPAL-ORDER-1', links=[fake_link])
        fake_client = MagicMock()
        fake_client.execute.return_value = SimpleNamespace(result=fake_result)

        with patch.object(app_module, 'get_paypal_client', return_value=fake_client):
            response = self.client.post('/checkout', data=self._checkout_form('paypal'), follow_redirects=False)

        self.assertEqual(response.status_code, 303)
        self.assertEqual(response.headers['Location'], 'https://paypal.test/approve')

        with self.app.app_context():
            order = Order.query.one()
            self.assertEqual(order.payment_method, 'paypal')
            self.assertEqual(order.payment_intent_id, 'PAYPAL-ORDER-1')

    def test_payment_success_confirms_stripe_order_from_session(self):
        order_number = self._create_order('stripe')

        session_obj = MagicMock()
        session_obj.get.side_effect = lambda key, default=None: {
            'payment_status': 'paid',
            'payment_intent': 'pi_success_123',
        }.get(key, default)

        with patch.object(app_module.stripe.checkout.Session, 'retrieve', return_value=session_obj):
            with patch.object(app_module, 'send_email') as send_email:
                response = self.client.get(
                    f'/payment/success?order_number={order_number}&session_id=cs_test_123',
                    follow_redirects=False,
                )

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers['Location'].endswith(f'/order/{order_number}'))
        send_email.assert_called_once()

        with self.app.app_context():
            order = Order.query.filter_by(order_number=order_number).first()
            self.assertEqual(order.payment_status, 'paid')
            self.assertEqual(order.status, 'confirmed')
            self.assertEqual(order.payment_intent_id, 'pi_success_123')

    def test_payment_success_captures_paypal_order(self):
        order_number = self._create_order('paypal', payment_intent_id='PAYPAL-ORDER-2')
        fake_result = SimpleNamespace(status='COMPLETED')
        fake_client = MagicMock()
        fake_client.execute.return_value = SimpleNamespace(result=fake_result)

        with patch.object(app_module, 'get_paypal_client', return_value=fake_client):
            with patch.object(app_module, 'send_email') as send_email:
                response = self.client.get(f'/payment/success?order_number={order_number}', follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.headers['Location'].endswith(f'/order/{order_number}'))
        send_email.assert_called_once()

        with self.app.app_context():
            order = Order.query.filter_by(order_number=order_number).first()
            self.assertEqual(order.payment_status, 'paid')
            self.assertEqual(order.status, 'confirmed')

    def test_stripe_webhook_marks_order_paid(self):
        order_number = self._create_order('stripe')
        event = {
            'type': 'checkout.session.completed',
            'data': {
                'object': {
                    'metadata': {'order_number': order_number},
                    'payment_intent': 'pi_webhook_123',
                }
            },
        }

        with patch.object(app_module.stripe.Webhook, 'construct_event', return_value=event):
            response = self.client.post(
                '/webhooks/stripe',
                data='{}',
                headers={'Stripe-Signature': 'sig_test'},
                follow_redirects=False,
            )

        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            order = Order.query.filter_by(order_number=order_number).first()
            self.assertEqual(order.payment_status, 'paid')
            self.assertEqual(order.status, 'confirmed')
            self.assertEqual(order.payment_intent_id, 'pi_webhook_123')

    def test_paypal_webhook_uses_related_order_id_for_capture_events(self):
        order_number = self._create_order('paypal', payment_intent_id='PAYPAL-ORDER-3')
        event = {
            'event_type': 'PAYMENT.CAPTURE.COMPLETED',
            'resource': {
                'id': 'CAPTURE-1',
                'supplementary_data': {
                    'related_ids': {
                        'order_id': 'PAYPAL-ORDER-3',
                    }
                },
            },
        }

        with patch.object(app_module, 'verify_paypal_webhook', return_value=True):
            response = self.client.post('/webhooks/paypal', json=event, follow_redirects=False)

        self.assertEqual(response.status_code, 200)

        with self.app.app_context():
            order = Order.query.filter_by(order_number=order_number).first()
            self.assertEqual(order.payment_status, 'paid')
            self.assertEqual(order.status, 'confirmed')


if __name__ == '__main__':
    unittest.main()
