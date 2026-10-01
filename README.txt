CLOTHING ORDERS - Quick Start

1. Install Python 3.10 or newer.
2. Open Command Prompt/Terminal in this folder.
3. Run: pip install -r requirements.txt
4. Run: python app.py
5. Open: http://127.0.0.1:5000

Demo accounts:
Admin: admin / Admin123!
Employee: employee / Employee123!

IMPORTANT BEFORE REAL USE:
- Change the demo passwords and SECRET_KEY.
- Do not expose this development server directly to the Internet.
- Customer ID images are sensitive. For production use, use HTTPS, private encrypted storage, backups, access controls, and a suitable retention/deletion policy.

EMPLOYEE MANAGEMENT:
Sign in as Admin, click "Employees" in the top menu, enter a unique username and
password of at least 12 characters, and click "Create Account". Repeat for each
employee. On the same page you can change a password or disable/reactivate an
employee. Disabling keeps the employee's order history and blocks new requests.
Each employee signs in with their own username and password. You do not need to
edit code for each account. The original demo employee account can be disabled
here. Existing clothing_orders.db data is retained; the active column is added
automatically when app.py is launched.

If replacing an older project folder, stop the app, back up clothing_orders.db
and uploads/, then replace app.py, templates/, and static/ with this version.
Keep your existing clothing_orders.db and uploads/ so customer records remain.

TRASH / RECOVERY:
Admin can use "Move to Trash" on the Dashboard. Trashed orders disappear from
Dashboard counts and search, but remain in the database with their ID documents.
Open "Trash" to search, view, and restore them. No permanent deletion is
performed. Existing databases gain the deleted_at column automatically on start.
ID document upload is optional; orders without it show no document link.
