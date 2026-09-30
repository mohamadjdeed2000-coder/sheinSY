# sheinSY

Bilingual Flask storefront and admin dashboard.

## Run locally
1. Install Python 3.11+
2. Open a terminal in this folder
3. `pip install -r requirements.txt`
4. `python app.py`
5. Open `http://127.0.0.1:5000`

Admin: `http://127.0.0.1:5000/admin/login`
Default username: `admin`
Default password: `Admin@12345`

## Configuration
Set environment variables before production deployment:
- `ADMIN_PASSWORD` — initial admin password on a fresh database
- `SECRET_KEY` — secure random Flask session key
- `WHATSAPP_NUMBER` — international number without +, e.g. 9715XXXXXXXX

For Render: Build command `pip install -r requirements.txt`; Start command `gunicorn app:app`.
Note: SQLite and uploaded images need persistent storage in production.
