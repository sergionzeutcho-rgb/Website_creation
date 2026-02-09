"""
Database migration script to add new features:
- Delivery support
- Discount codes
- Multilingual support
"""

from app import app, db
from models import Order, SiteSettings, Discount, DeliveryZone

def migrate_database():
    with app.app_context():
        print("Starting database migration...")
        
        # Add new columns to existing tables
        try:
            # Check if columns exist before adding
            inspector = db.inspect(db.engine)
            
            # Order table migrations
            order_columns = [col['name'] for col in inspector.get_columns('order')]
            
            if 'fulfillment_method' not in order_columns:
                print("Adding fulfillment_method to Order...")
                db.session.execute(db.text("ALTER TABLE 'order' ADD COLUMN fulfillment_method VARCHAR(20) DEFAULT 'pickup'"))
            
            if 'delivery_address' not in order_columns:
                print("Adding delivery_address to Order...")
                db.session.execute(db.text("ALTER TABLE 'order' ADD COLUMN delivery_address TEXT"))
            
            if 'delivery_postcode' not in order_columns:
                print("Adding delivery_postcode to Order...")
                db.session.execute(db.text("ALTER TABLE 'order' ADD COLUMN delivery_postcode VARCHAR(20)"))
            
            if 'delivery_fee' not in order_columns:
                print("Adding delivery_fee to Order...")
                db.session.execute(db.text("ALTER TABLE 'order' ADD COLUMN delivery_fee FLOAT DEFAULT 0.0"))
            
            if 'discount_code' not in order_columns:
                print("Adding discount_code to Order...")
                db.session.execute(db.text("ALTER TABLE 'order' ADD COLUMN discount_code VARCHAR(50)"))
            
            if 'discount_amount' not in order_columns:
                print("Adding discount_amount to Order...")
                db.session.execute(db.text("ALTER TABLE 'order' ADD COLUMN discount_amount FLOAT DEFAULT 0.0"))
            
            # SiteSettings migrations
            settings_columns = [col['name'] for col in inspector.get_columns('site_settings')]
            
            if 'delivery_enabled' not in settings_columns:
                print("Adding delivery_enabled to SiteSettings...")
                db.session.execute(db.text("ALTER TABLE site_settings ADD COLUMN delivery_enabled BOOLEAN DEFAULT 0"))
            
            if 'default_delivery_fee' not in settings_columns:
                print("Adding default_delivery_fee to SiteSettings...")
                db.session.execute(db.text("ALTER TABLE site_settings ADD COLUMN default_delivery_fee FLOAT DEFAULT 5.0"))
            
            if 'free_delivery_threshold' not in settings_columns:
                print("Adding free_delivery_threshold to SiteSettings...")
                db.session.execute(db.text("ALTER TABLE site_settings ADD COLUMN free_delivery_threshold FLOAT DEFAULT 50.0"))
            
            if 'default_language' not in settings_columns:
                print("Adding default_language to SiteSettings...")
                db.session.execute(db.text("ALTER TABLE site_settings ADD COLUMN default_language VARCHAR(10) DEFAULT 'en'"))
            
            if 'enable_auto_translate' not in settings_columns:
                print("Adding enable_auto_translate to SiteSettings...")
                db.session.execute(db.text("ALTER TABLE site_settings ADD COLUMN enable_auto_translate BOOLEAN DEFAULT 1"))
            
            db.session.commit()
            print("Column migrations completed!")
            
            # Create new tables
            print("Creating new tables...")
            db.create_all()
            print("New tables created!")
            
            print("\n✅ Database migration completed successfully!")
            print("\nNew features added:")
            print("  - Delivery/Pickup support")
            print("  - Discount codes system")
            print("  - Delivery zones with custom pricing")
            print("  - Multilingual back-office support")
            
        except Exception as e:
            print(f"❌ Error during migration: {e}")
            db.session.rollback()
            raise

if __name__ == '__main__':
    migrate_database()
