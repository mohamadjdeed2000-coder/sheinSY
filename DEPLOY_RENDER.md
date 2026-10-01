# Deploy Clothing Orders on Render

This is a paid deployment because a persistent disk is required. Do not put customer IDs or the SQLite database in GitHub.

1. Create a private GitHub repository. Upload the contents of this `clothing_orders` directory to the repository root (app.py, requirements.txt, templates/, static/, .gitignore). Never upload `clothing_orders.db`, `uploads/`, or a `.env` file.
2. In Render, choose New > Web Service and connect the private repository. Choose Python 3.
3. Build command: `pip install -r requirements.txt`
4. Start command: `gunicorn --workers 1 --threads 4 --bind 0.0.0.0:$PORT app:app`
5. Choose a paid web service. Attach a persistent disk mounted at `/var/data`, sized for the expected ID documents. Both the database and uploaded IDs will live there. Do not choose a free service for this design.
6. Set environment variables in the Render dashboard:
   - `CLOUD_MODE=1`
   - `DATA_DIR=/var/data`
   - `SECRET_KEY=` a random value of at least 32 characters; generate locally with `python -c "import secrets; print(secrets.token_urlsafe(48))"` and keep it private.
   - `INITIAL_ADMIN_PASSWORD=` your unique admin password of at least 12 characters, entered only in Render's Environment settings. It seeds a NEW database once. Do not put it in GitHub.
7. Deploy. Visit the HTTPS `onrender.com` URL and sign in as `admin` with the password set above. Use Employees to create separate accounts for staff. Do not share the admin account. Remove `INITIAL_ADMIN_PASSWORD` from Render's settings after confirming that the admin account exists; restarting won't reset an existing password.
8. Test with fictional customer details and no real identity document. Verify each staff account, admin-only ID access, Trash and Restore, and data persistence after redeploy.

If you already have orders on your computer, the cloud deployment starts with an empty database. Preserve the local `clothing_orders.db` and `uploads/` files, and arrange a separate secure transfer to `/var/data` before using existing records. Do not upload those files to GitHub. If a local database with demo accounts is transferred, change/disable every demo credential before granting employee access.

Back up the SQLite database with its backup API while the service is running, and back up the uploads folder separately. Disk snapshots are not a substitute for a tested backup and restore process. A paid persistent disk keeps files across deploys, but a disk failure, accidental removal, or deletion can still lose data.

The online version uses HTTPS via Render, secure session cookies, CSRF-protected forms, hashed passwords, private file paths, and one application instance. Set a policy for collecting, retaining, and deleting customer identity images. Before storing actual IDs, review whether your business truly needs them and have a security/privacy review of the deployment.

Update notes: This version adds multiple items per customer order and an order activity log.
Upload the changed app.py, templates/, and static/style.css to the same paths in your existing private GitHub repository. Render auto-deploys after commit if enabled.
Existing SQLite orders are migrated automatically at startup. Back up any persistent database before deploying to production. On Render Free, the database and uploads are temporary and can be lost on restart or redeploy.

Version 5: mobile order menus, optional order comment, Gender (Man/Women), product choices (Pajamas/Pants/Shoes), and colored submitted/edited/cancelled states. Cancellation and trash reasons appear in the order detail activity history rather than the dashboard list. Existing orders gain empty comment/gender fields at startup. Upload app.py, all changed templates, and static/style.css to the matching repository paths. Keep clothing_orders.db and uploads out of GitHub.
