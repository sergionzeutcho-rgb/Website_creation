"""
Generate slugs for existing products
"""
import re
from app import app, db
from models import Product

def slugify(text):
    """Convert text to URL-friendly slug"""
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[-\s]+', '-', text)
    return text.strip('-')

with app.app_context():
    products = Product.query.all()
    
    for product in products:
        if not product.slug:
            base_slug = slugify(product.name)
            slug = base_slug
            counter = 1
            
            # Ensure uniqueness
            while Product.query.filter_by(slug=slug).first() is not None:
                slug = f"{base_slug}-{counter}"
                counter += 1
            
            product.slug = slug
            print(f"Generated slug for '{product.name}': {slug}")
    
    db.session.commit()
    print(f"\nSuccessfully generated slugs for {len(products)} products!")
