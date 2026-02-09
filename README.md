# Atelier Gourmand by OC - Website

A luxurious, minimalist website for a London-based patisserie with a complete back-office management system.

## Features

### Public Website
- **Luxurious Design**: Elegant, minimalist aesthetic inspired by premium patisseries
- **Hero Section**: Customizable hero with images and location details
- **Product Showcase**: Display seasonal creations with images and pricing
- **Booking System**: Customers can book pickup slots directly
- **Responsive**: Works beautifully on all devices

### Back-Office Admin Panel
- **Product Management**: Add, edit, delete products with images and pricing
- **Content Management**: Edit hero section, maison section, and settings
- **Booking Management**: View and manage customer bookings
- **Image Upload**: Upload product photos, hero images, and more
- **Settings**: Manage site title, contact info, and social media links

## Installation

1. **Install Python dependencies**:
```bash
.venv\Scripts\activate  # Activate your virtual environment
pip install -r requirements.txt
```

2. **Set up environment variables**:
The `.env` file is already created with default values. For production, update:
- `SECRET_KEY`: Change to a secure random key
- `ADMIN_EMAIL`: Your admin email
- `ADMIN_PASSWORD`: Choose a strong password

3. **Initialize the database**:
```bash
python app.py
```
This will:
- Create the database
- Create necessary tables
- Create a default admin user

## Usage

### Running the Development Server

```bash
python app.py
```

The site will be available at:
- **Public site**: http://localhost:5000
- **Admin panel**: http://localhost:5000/admin/login

### Default Admin Credentials
- Email: `admin@ateliergourmandbyoc.co.uk`
- Password: `AteLier2026!`

**⚠️ Change these immediately after first login!**

### Admin Panel Features

1. **Dashboard**: Overview of products, bookings, and recent activity
2. **Products**: 
   - Add new products with name, description, price, and images
   - Set display order
   - Toggle active/inactive status
3. **Hero Section**: Customize the main hero section with title, description, and image
4. **Maison Section**: Edit the "Our Maison" section
5. **Bookings**: View and manage all customer booking requests
6. **Settings**: Update site-wide settings like contact info and social links

## Deployment

### For Production Server

1. **Update environment variables** in `.env`:
   - Use a strong `SECRET_KEY`
   - Set production email/password
   - Consider using PostgreSQL instead of SQLite

2. **Use a production server**:
```bash
pip install gunicorn
gunicorn -w 4 -b 0.0.0.0:8000 app:app
```

3. **Set up reverse proxy** (nginx recommended)

4. **Enable HTTPS** with Let's Encrypt

## File Structure

```
website/
├── app.py                 # Main Flask application
├── models.py              # Database models
├── requirements.txt       # Python dependencies
├── .env                   # Environment variables
├── templates/
│   ├── index.html         # Public website
│   └── admin/             # Admin panel templates
├── static/
│   ├── styles.css         # Luxurious styling
│   ├── script.js          # Frontend interactions
│   └── uploads/           # Uploaded images
└── atelier.db            # SQLite database (created on first run)
```

## Customization

### Styling
Edit `static/styles.css` to customize:
- Colors (CSS variables in `:root`)
- Typography
- Spacing and layout
- Animations

### Content
Everything can be managed through the admin panel without touching code.

## Tech Stack

- **Backend**: Flask (Python)
- **Database**: SQLite (upgradeable to PostgreSQL)
- **Frontend**: HTML5, CSS3, Vanilla JavaScript
- **Admin**: Custom admin panel with Flask-Login
- **File Uploads**: Werkzeug secure filename handling

## Support

For issues or questions, edit the code or contact the development team.

---

**Atelier Gourmand by OC** - Quiet luxury, careful detail.
