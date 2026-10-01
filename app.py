import os, sqlite3, secrets, json, csv, io
from decimal import Decimal, InvalidOperation
from collections import Counter
from zoneinfo import ZoneInfo
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash, send_from_directory, abort, jsonify, Response
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE = os.path.dirname(os.path.abspath(__file__))
CLOUD_MODE = os.environ.get('CLOUD_MODE') == '1'
DATA_DIR = os.environ.get('DATA_DIR', BASE)
if CLOUD_MODE and (not os.environ.get('DATA_DIR') or not os.path.isabs(DATA_DIR)):
    raise RuntimeError('Set DATA_DIR to an absolute persistent disk path in cloud settings.')
DB = os.path.join(DATA_DIR, 'clothing_orders.db')
UPLOAD = os.path.join(DATA_DIR, 'uploads')
ALLOWED = {'png','jpg','jpeg','webp','pdf'}

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY')
if CLOUD_MODE and (not app.secret_key or len(app.secret_key) < 32):
    raise RuntimeError('Set a random SECRET_KEY of at least 32 characters in cloud settings.')
if not app.secret_key:
    app.secret_key = 'local-development-only-change-this-secret-key'
app.config.update(SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax',
                  SESSION_COOKIE_SECURE=CLOUD_MODE)
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024


def conn():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c

def init_db():
    os.makedirs(DATA_DIR,exist_ok=True)
    os.makedirs(UPLOAD,exist_ok=True)
    c=conn()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS orders(
      id INTEGER PRIMARY KEY AUTOINCREMENT, order_no TEXT UNIQUE,
      customer_name TEXT NOT NULL, phone TEXT NOT NULL, area TEXT NOT NULL,
      product TEXT NOT NULL, size TEXT NOT NULL, quantity INTEGER NOT NULL,
      id_image TEXT NOT NULL, employee_id INTEGER NOT NULL,
      status TEXT NOT NULL DEFAULT 'New', created_at TEXT NOT NULL,
      deleted_at TEXT, gender TEXT NOT NULL DEFAULT '', comment TEXT NOT NULL DEFAULT '',
      FOREIGN KEY(employee_id) REFERENCES users(id));
    CREATE TABLE IF NOT EXISTS order_items(id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL,
      product TEXT NOT NULL, size TEXT NOT NULL, quantity INTEGER NOT NULL,
      FOREIGN KEY(order_id) REFERENCES orders(id));
    CREATE TABLE IF NOT EXISTS order_events(id INTEGER PRIMARY KEY, order_id INTEGER NOT NULL,
      actor_id INTEGER NOT NULL, action TEXT NOT NULL, occurred_at TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
      FOREIGN KEY(order_id) REFERENCES orders(id), FOREIGN KEY(actor_id) REFERENCES users(id));
    ''')
    if 'active' not in [r['name'] for r in c.execute('PRAGMA table_info(users)')]:
        c.execute('ALTER TABLE users ADD COLUMN active INTEGER NOT NULL DEFAULT 1')
    if 'deleted_at' not in [r['name'] for r in c.execute('PRAGMA table_info(orders)')]:
        c.execute('ALTER TABLE orders ADD COLUMN deleted_at TEXT')
    for column in ('gender','comment'):
        if column not in [r['name'] for r in c.execute('PRAGMA table_info(orders)')]:
            c.execute(f"ALTER TABLE orders ADD COLUMN {column} TEXT NOT NULL DEFAULT ''")
    if 'reason' not in [r['name'] for r in c.execute('PRAGMA table_info(order_events)')]:
        c.execute("ALTER TABLE order_events ADD COLUMN reason TEXT NOT NULL DEFAULT ''")
    # Existing orders keep their original item after upgrading.
    c.execute('''INSERT INTO order_items(order_id,product,size,quantity)
      SELECT o.id,o.product,o.size,o.quantity FROM orders o
      WHERE NOT EXISTS(SELECT 1 FROM order_items i WHERE i.order_id=o.id)''')
    c.executescript("""
    CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY, name TEXT NOT NULL, price_cents INTEGER NOT NULL DEFAULT 0, active INTEGER NOT NULL DEFAULT 1);
    CREATE TABLE IF NOT EXISTS variants(id INTEGER PRIMARY KEY, product_id INTEGER NOT NULL REFERENCES products(id), color TEXT NOT NULL, size TEXT NOT NULL, stock INTEGER NOT NULL CHECK(stock>=0), active INTEGER NOT NULL DEFAULT 1, UNIQUE(product_id,color,size));
    CREATE INDEX IF NOT EXISTS orders_report_date ON orders(created_at,status,employee_id);
    CREATE INDEX IF NOT EXISTS order_items_order ON order_items(order_id);
    """)
    for table, column, definition in [('orders','province',"TEXT NOT NULL DEFAULT ''"),('orders','stock_reserved','INTEGER NOT NULL DEFAULT 0'),('order_items','variant_id','INTEGER REFERENCES variants(id)'),('order_items','color',"TEXT NOT NULL DEFAULT ''"),('order_items','price_cents','INTEGER NOT NULL DEFAULT 0')]:
        if column not in [r['name'] for r in c.execute('PRAGMA table_info('+table+')')]:
            c.execute('ALTER TABLE '+table+' ADD COLUMN '+column+' '+definition)
    if not c.execute('SELECT 1 FROM users WHERE username=?',('admin',)).fetchone():
        initial_password=os.environ.get('INITIAL_ADMIN_PASSWORD') if CLOUD_MODE else 'Admin123!'
        if not initial_password or (CLOUD_MODE and len(initial_password)<12):
            c.close(); raise RuntimeError('Set INITIAL_ADMIN_PASSWORD (12+ characters) in cloud settings.')
        c.execute('INSERT INTO users(username,password,role) VALUES(?,?,?)',('admin',generate_password_hash(initial_password),'admin'))
    if not CLOUD_MODE and not c.execute('SELECT 1 FROM users WHERE username=?',('employee',)).fetchone():
        c.execute('INSERT INTO users(username,password,role) VALUES(?,?,?)',('employee',generate_password_hash('Employee123!'),'employee'))
    c.commit(); c.close()

def logged_in(f):
    @wraps(f)
    def w(*a,**k):
        if 'user_id' not in session: return redirect(url_for('login'))
        c=conn(); u=c.execute('SELECT role,active FROM users WHERE id=?',(session['user_id'],)).fetchone(); c.close()
        if not u or not u['active']:
            session.clear(); flash('Account disabled. Please contact the administrator.'); return redirect(url_for('login'))
        session['role']=u['role']
        return f(*a,**k)
    return w

def admin_only(f):
    @wraps(f)
    def w(*a,**k):
        if session.get('role')!='admin': abort(403)
        return f(*a,**k)
    return w

def allowed(name): return '.' in name and name.rsplit('.',1)[1].lower() in ALLOWED

def valid_document(f):
    header=f.stream.read(12)
    f.stream.seek(0)
    ext=f.filename.rsplit('.',1)[1].lower()
    return ((ext=='png' and header.startswith(b'\x89PNG\r\n\x1a\n')) or
            (ext in {'jpg','jpeg'} and header.startswith(b'\xff\xd8\xff')) or
            (ext=='webp' and header.startswith(b'RIFF') and header[8:12]==b'WEBP') or
            (ext=='pdf' and header.startswith(b'%PDF-')))

PROVINCES = ['Damascus','Rif Dimashq','Aleppo','Idlib','Hama','Tartus','Latakia','Homs','Daraa','Deir ez-Zor','Raqqa','Al-Hasakah','As-Suwayda','Quneitra']

def items_from_form(form):
    ids=form.getlist('variant_id[]'); quantities=form.getlist('quantity[]')
    if not ids or len(ids)!=len(quantities) or len(ids)>30: raise ValueError('Add between 1 and 30 items.')
    try:
        rows=[(int(v),int(q)) for v,q in zip(ids,quantities)]
    except (ValueError,TypeError): raise ValueError('Choose a product, color, size and quantity.')
    if any(q<1 or q>10000 for v,q in rows): raise ValueError('Quantity must be between 1 and 10000.')
    counts=Counter()
    for v,q in rows: counts[v]+=q
    return list(counts.items())

def stock_items(c, selections):
    result=[]
    for vid,qty in selections:
        v=c.execute('SELECT v.*,p.name,p.price_cents,p.active product_active FROM variants v JOIN products p ON p.id=v.product_id WHERE v.id=?',(vid,)).fetchone()
        if not v or not v['active'] or not v['product_active']: raise ValueError('An item is no longer available. Refresh and choose another product.')
        if c.execute('UPDATE variants SET stock=stock-? WHERE id=? AND stock>=?',(qty,vid,qty)).rowcount!=1:
            raise ValueError(v['name']+' / '+v['color']+' / '+v['size']+': insufficient stock or Out of stock.')
        result.append((v['name'],v['size'],qty,vid,v['color'],v['price_cents']))
    return result

def release_stock(c,oid):
    if c.execute('SELECT stock_reserved FROM orders WHERE id=?',(oid,)).fetchone()['stock_reserved']:
        for i in c.execute('SELECT variant_id,quantity FROM order_items WHERE order_id=?',(oid,)).fetchall():
            if i['variant_id']: c.execute('UPDATE variants SET stock=stock+? WHERE id=?',(i['quantity'],i['variant_id']))
        c.execute('UPDATE orders SET stock_reserved=0 WHERE id=?',(oid,))

def catalog(c):
    return [dict(r) for r in c.execute('SELECT v.*,p.name,p.price_cents FROM variants v JOIN products p ON p.id=v.product_id WHERE p.active=1 AND v.active=1 ORDER BY p.name,v.color,v.size')]

@app.context_processor
def inventory_context(): return {'provinces':PROVINCES}

@app.route('/inventory.json')
@logged_in
def inventory_json():
    c=conn(); rows=catalog(c); c.close()
    response=jsonify(rows); response.headers['Cache-Control']='no-store'; return response

def extra_fields(form):
    gender=form.get('gender','').strip(); comment=form.get('comment','').strip()
    if gender not in {'Man','Women'}: raise ValueError('Select a gender.')
    if len(comment)>1000: raise ValueError('Comment must be 1000 characters or fewer.')
    return gender,comment

def event(c,oid,action,reason=''):
    c.execute('INSERT INTO order_events(order_id,actor_id,action,occurred_at,reason) VALUES(?,?,?,?,?)',
              (oid,session['user_id'],action,datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),reason))

def csrf_token():
    if '_csrf' not in session: session['_csrf']=secrets.token_urlsafe(32)
    return session['_csrf']

app.jinja_env.globals['csrf_token']=csrf_token

@app.before_request
def check_csrf():
    if request.method == 'POST':
        if not session.get('_csrf') or not secrets.compare_digest(session.get('_csrf',''), request.form.get('_csrf','')):
            abort(400)

@app.route('/', methods=['GET','POST'])
def login():
    if request.method=='POST':
        c=conn(); u=c.execute('SELECT * FROM users WHERE username=?',(request.form['username'].strip(),)).fetchone(); c.close()
        if u and u['active'] and check_password_hash(u['password'], request.form['password']):
            session.clear(); session.update(user_id=u['id'], username=u['username'], role=u['role'])
            return redirect(url_for('dashboard' if u['role']=='admin' else 'new_order'))
        flash('Incorrect username or password.')
    return render_template('login.html')

@app.route('/logout')
def logout(): session.clear(); return redirect(url_for('login'))

def customer_fields(form):
    customer=form.get('customer_name','').strip(); phone=form.get('phone','').strip(); area=form.get('area','').strip(); province=form.get('province','')
    if not all((customer,phone,area)) or province not in PROVINCES: raise ValueError('Complete customer name, phone, province and detailed address.')
    if max(len(customer),len(phone),len(area))>1000: raise ValueError('Customer details are too long.')
    return customer,phone,area,province

@app.route('/new-order', methods=['GET','POST'])
@logged_in
def new_order():
    if request.method=='POST':
        filename=''; c=conn()
        try:
            selections=items_from_form(request.form); gender,comment=extra_fields(request.form)
            customer,phone,area,province=customer_fields(request.form)
            f=request.files.get('id_image')
            if f and f.filename:
                if not allowed(f.filename) or not valid_document(f): raise ValueError('ID document must be a valid JPG, PNG, WEBP, or PDF.')
                filename=secrets.token_hex(24)+'.'+f.filename.rsplit('.',1)[1].lower(); f.save(os.path.join(UPLOAD,filename))
            c.execute('BEGIN IMMEDIATE')
            items=stock_items(c,selections)
            oid=c.execute("""INSERT INTO orders(customer_name,phone,area,province,product,size,quantity,id_image,employee_id,status,created_at,gender,comment,stock_reserved)
                VALUES(?,?,?,?,?,?,?,?,?,'New',?,?,?,1)""",(customer,phone,area,province,*items[0][:3],filename,session['user_id'],datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),gender,comment)).lastrowid
            c.execute('UPDATE orders SET order_no=? WHERE id=?',(f'ORD-{oid:06d}',oid))
            c.executemany('INSERT INTO order_items(order_id,product,size,quantity,variant_id,color,price_cents) VALUES(?,?,?,?,?,?,?)',[(oid,*i) for i in items]); event(c,oid,'Submitted'); c.commit()
        except ValueError as exc:
            c.rollback()
            if filename: os.remove(os.path.join(UPLOAD,filename))
            flash(str(exc)); return redirect(url_for('new_order'))
        except Exception:
            c.rollback()
            if filename: os.remove(os.path.join(UPLOAD,filename))
            raise
        finally: c.close()
        return redirect(url_for('order_success',oid=oid))
    return render_template('order_form.html',o=None,items=[])

@app.route('/order/<int:oid>/success')
@logged_in
def order_success(oid):
    c=conn(); o=c.execute('''SELECT o.*,(SELECT action FROM order_events e WHERE e.order_id=o.id ORDER BY e.id DESC LIMIT 1) latest_action
      FROM orders o WHERE o.id=? AND o.employee_id=?''',(oid,session['user_id'])).fetchone()
    if not o: abort(404)
    items=c.execute('SELECT * FROM order_items WHERE order_id=? ORDER BY id',(oid,)).fetchall(); c.close()
    return render_template('order_success.html',o=o,items=items)

@app.route('/my-orders')
@logged_in
def my_orders():
    c=conn(); rows=c.execute('''SELECT o.*,(SELECT action FROM order_events e WHERE e.order_id=o.id ORDER BY e.id DESC LIMIT 1) latest_action
      FROM orders o WHERE o.employee_id=? AND o.deleted_at IS NULL ORDER BY o.id DESC''',(session['user_id'],)).fetchall(); c.close()
    return render_template('my_orders.html',orders=rows)

@app.route('/my-orders/<int:oid>/edit',methods=['GET','POST'])
@logged_in
def edit_my_order(oid):
    c=conn()
    if request.method=='POST': c.execute('BEGIN IMMEDIATE')
    o=c.execute('SELECT * FROM orders WHERE id=? AND employee_id=? AND deleted_at IS NULL',(oid,session['user_id'])).fetchone()
    if not o: c.close(); abort(404)
    if o['status']!='New': c.close(); flash('Only new orders can be edited.'); return redirect(url_for('my_orders'))
    if request.method=='POST':
        try:
            selections=items_from_form(request.form); gender,comment=extra_fields(request.form)
            customer,phone,area,province=customer_fields(request.form)
            release_stock(c,oid); items=stock_items(c,selections)
            c.execute('UPDATE orders SET customer_name=?,phone=?,area=?,province=?,product=?,size=?,quantity=?,gender=?,comment=?,stock_reserved=1 WHERE id=?',(customer,phone,area,province,*items[0][:3],gender,comment,oid))
            c.execute('DELETE FROM order_items WHERE order_id=?',(oid,))
            c.executemany('INSERT INTO order_items(order_id,product,size,quantity,variant_id,color,price_cents) VALUES(?,?,?,?,?,?,?)',[(oid,*i) for i in items]); event(c,oid,'Edited'); c.commit()
        except ValueError as exc:
            c.rollback(); flash(str(exc)); return redirect(url_for('edit_my_order',oid=oid))
        finally: c.close()
        flash('Order updated.'); return redirect(url_for('my_orders'))
    items=c.execute('SELECT * FROM order_items WHERE order_id=? ORDER BY id',(oid,)).fetchall(); c.close()
    return render_template('order_form.html',o=o,items=items)

@app.route('/my-orders/<int:oid>/cancel',methods=['POST'])
@logged_in
def cancel_my_order(oid):
    reason=request.form.get('reason','').strip()
    if not reason or len(reason)>500:
        flash('Please enter a cancellation reason (up to 500 characters).')
        return redirect(request.referrer if request.referrer and request.referrer.startswith(request.host_url) else url_for('my_orders'))
    c=conn()
    with c:
        c.execute('BEGIN IMMEDIATE')
        cur=c.execute("UPDATE orders SET status='Cancelled' WHERE id=? AND employee_id=? AND status='New' AND deleted_at IS NULL",(oid,session['user_id']))
        if not cur.rowcount: abort(404)
        release_stock(c,oid)
        event(c,oid,'Cancelled',reason)
    c.close(); flash('Order cancelled.'); return redirect(url_for('my_orders'))

@app.route('/dashboard')
@logged_in
@admin_only
def dashboard():
    q=request.args.get('q','').strip(); c=conn()
    sql='''SELECT o.*,u.username employee,
      (SELECT e.action FROM order_events e WHERE e.order_id=o.id ORDER BY e.id DESC LIMIT 1) latest_action,
      (SELECT e.occurred_at FROM order_events e WHERE e.order_id=o.id ORDER BY e.id DESC LIMIT 1) action_at,
      (SELECT e.reason FROM order_events e WHERE e.order_id=o.id ORDER BY e.id DESC LIMIT 1) action_reason,
      (SELECT actor.username FROM order_events e JOIN users actor ON actor.id=e.actor_id WHERE e.order_id=o.id ORDER BY e.id DESC LIMIT 1) action_by
      FROM orders o JOIN users u ON u.id=o.employee_id WHERE o.deleted_at IS NULL'''; params=[]
    if q:
        sql += ' AND (o.order_no LIKE ? OR o.customer_name LIKE ? OR o.phone LIKE ?)'; s=f'%{q}%'; params=[s,s,s]
    sql += ' ORDER BY o.id DESC'; rows=c.execute(sql,params).fetchall()
    stats={r['status']:r['n'] for r in c.execute('SELECT status,COUNT(*) n FROM orders WHERE deleted_at IS NULL GROUP BY status')}
    total=c.execute('SELECT COUNT(*) n FROM orders WHERE deleted_at IS NULL').fetchone()['n']; c.close()
    return render_template('dashboard.html',orders=rows,stats=stats,total=total,q=q)

@app.route('/trash')
@logged_in
@admin_only
def trash():
    q=request.args.get('q','').strip(); c=conn()
    sql='''SELECT o.*,u.username employee,
           (SELECT a.username FROM order_events e JOIN users a ON a.id=e.actor_id WHERE e.order_id=o.id AND e.action='Moved to Trash' ORDER BY e.id DESC LIMIT 1) deleted_by,
           (SELECT e.reason FROM order_events e WHERE e.order_id=o.id AND e.action='Moved to Trash' ORDER BY e.id DESC LIMIT 1) deleted_reason
           FROM orders o JOIN users u ON u.id=o.employee_id WHERE o.deleted_at IS NOT NULL'''; params=[]
    if q:
        sql += ' AND (o.order_no LIKE ? OR o.customer_name LIKE ? OR o.phone LIKE ?)'
        s=f'%{q}%'; params=[s,s,s]
    sql += ' ORDER BY o.deleted_at DESC, o.id DESC'
    rows=c.execute(sql,params).fetchall(); c.close()
    return render_template('trash.html',orders=rows,q=q)

@app.route('/order/<int:oid>/trash', methods=['POST'])
@logged_in
@admin_only
def move_to_trash(oid):
    reason=request.form.get('reason','').strip()
    if not reason or len(reason)>500:
        flash('Please enter a reason (up to 500 characters).'); return redirect(url_for('dashboard'))
    c=conn()
    with c:
        cur=c.execute('UPDATE orders SET deleted_at=? WHERE id=? AND deleted_at IS NULL',
                      (datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S'),oid))
        if cur.rowcount: event(c,oid,'Moved to Trash',reason)
    c.close()
    if not cur.rowcount: abort(404)
    flash('Order moved to Trash. You can restore it later.')
    return redirect(url_for('dashboard'))

@app.route('/order/<int:oid>/restore', methods=['POST'])
@logged_in
@admin_only
def restore_order(oid):
    c=conn()
    with c:
        cur=c.execute('UPDATE orders SET deleted_at=NULL WHERE id=? AND deleted_at IS NOT NULL',(oid,))
        if cur.rowcount: event(c,oid,'Restored')
    c.close()
    if not cur.rowcount: abort(404)
    flash('Order restored.')
    return redirect(url_for('trash'))

@app.route('/employees', methods=['GET','POST'])
@logged_in
@admin_only
def employees():
    c=conn()
    if request.method=='POST':
        username=request.form.get('username','').strip().lower()
        password=request.form.get('password','')
        if not (3 <= len(username) <= 40 and username.replace('_','').isalnum() and username.isascii()):
            flash('Username must be 3–40 English letters, digits, or underscores.')
        elif len(password) < 12:
            flash('Password must be at least 12 characters.')
        else:
            try:
                c.execute('INSERT INTO users(username,password,role,active) VALUES(?,?,?,1)',
                          (username,generate_password_hash(password),'employee'))
                c.commit(); flash('Employee account created.')
            except sqlite3.IntegrityError:
                flash('Username already in use.')
        c.close(); return redirect(url_for('employees'))
    users=c.execute("SELECT id,username,active FROM users WHERE role='employee' ORDER BY id").fetchall()
    c.close(); return render_template('employees.html',employees=users)

@app.route('/employees/<int:uid>/password', methods=['POST'])
@logged_in
@admin_only
def employee_password(uid):
    password=request.form.get('password','')
    if len(password)<12:
        flash('Password must be at least 12 characters.')
    else:
        c=conn(); cur=c.execute("UPDATE users SET password=? WHERE id=? AND role='employee'",
                                (generate_password_hash(password),uid))
        c.commit(); c.close()
        if not cur.rowcount: abort(404)
        flash('Employee password changed.')
    return redirect(url_for('employees'))

@app.route('/employees/<int:uid>/toggle', methods=['POST'])
@logged_in
@admin_only
def employee_toggle(uid):
    c=conn(); cur=c.execute("UPDATE users SET active=1-active WHERE id=? AND role='employee'",(uid,))
    c.commit(); c.close()
    if not cur.rowcount: abort(404)
    flash('Account status updated.')
    return redirect(url_for('employees'))

@app.route('/order/<int:oid>', methods=['GET','POST'])
@logged_in
@admin_only
def order_detail(oid):
    c=conn()
    if request.method=='POST':
        status=request.form['status']
        if status in {'New','Processing','Completed','Cancelled'}:
            try:
                c.execute('BEGIN IMMEDIATE')
                old=c.execute('SELECT * FROM orders WHERE id=? AND deleted_at IS NULL',(oid,)).fetchone()
                if not old: abort(404)
                if status=='Cancelled': release_stock(c,oid)
                elif old['status']=='Cancelled' and not old['stock_reserved']:
                    selections=[(i['variant_id'],i['quantity']) for i in c.execute('SELECT * FROM order_items WHERE order_id=?',(oid,)) if i['variant_id']]
                    stock_items(c,selections)
                    c.execute('UPDATE orders SET stock_reserved=1 WHERE id=?',(oid,))
                c.execute('UPDATE orders SET status=? WHERE id=?',(status,oid)); event(c,oid,f'Status changed to {status}'); c.commit(); flash('Order status updated.')
            except ValueError as exc: c.rollback(); flash(str(exc))
    row=c.execute('''SELECT o.*,u.username employee FROM orders o JOIN users u ON u.id=o.employee_id WHERE o.id=?''',(oid,)).fetchone()
    if not row: abort(404)
    items=c.execute('SELECT * FROM order_items WHERE order_id=? ORDER BY id',(oid,)).fetchall()
    history=c.execute('''SELECT e.action,e.reason,e.occurred_at,u.username actor FROM order_events e JOIN users u ON u.id=e.actor_id
      WHERE e.order_id=? ORDER BY e.id DESC''',(oid,)).fetchall(); c.close()
    return render_template('detail.html',o=row,items=items,history=history)

@app.route('/identity/<path:filename>')
@logged_in
@admin_only
def identity(filename): return send_from_directory(UPLOAD,filename,as_attachment=True)

@app.route('/products',methods=['GET','POST'])
@logged_in
@admin_only
def products_admin():
    c=conn()
    if request.method=='POST':
        try:
            name=request.form.get('name','').strip()
            price=Decimal(request.form.get('price',''))
            if not name or len(name)>120 or not price.is_finite() or price<0 or price>1000000000: raise ValueError('Enter a product name and valid price.')
            colors=request.form.getlist('color[]'); sizes=request.form.getlist('size[]'); stocks=request.form.getlist('stock[]')
            if not colors or not(len(colors)==len(sizes)==len(stocks)) or len(colors)>200: raise ValueError('Add 1–200 color / size rows.')
            variants=[]; seen=set()
            for color,size,stock in zip(colors,sizes,stocks):
                color=color.strip(); size=size.strip(); stock=int(stock)
                if not color or not size or max(len(color),len(size))>50 or not 0<=stock<=1000000 or (color.casefold(),size.casefold()) in seen: raise ValueError('Use unique color / size rows and non-negative quantities.')
                seen.add((color.casefold(),size.casefold())); variants.append((color,size,stock))
            c.execute('BEGIN IMMEDIATE')
            raw=request.form.get('product_id','')
            if raw:
                pid=int(raw)
                if not c.execute('SELECT 1 FROM products WHERE id=?',(pid,)).fetchone(): abort(404)
                c.execute('UPDATE products SET name=?,price_cents=?,active=1 WHERE id=?',(name,int(price*100),pid))
            else: pid=c.execute('INSERT INTO products(name,price_cents) VALUES(?,?)',(name,int(price*100))).lastrowid
            c.execute('UPDATE variants SET active=0 WHERE product_id=?',(pid,))
            for color,size,stock in variants:
                c.execute('INSERT INTO variants(product_id,color,size,stock) VALUES(?,?,?,?) ON CONFLICT(product_id,color,size) DO UPDATE SET stock=excluded.stock,active=1',(pid,color,size,stock))
            c.commit(); flash('Product saved. Available stock is updated for employees.')
        except (ValueError,InvalidOperation) as exc: c.rollback(); flash(str(exc))
        finally: c.close()
        return redirect(url_for('products_admin'))
    rows=c.execute('SELECT p.*,COALESCE(SUM(CASE WHEN v.active=1 THEN v.stock ELSE 0 END),0) total_stock FROM products p LEFT JOIN variants v ON v.product_id=p.id GROUP BY p.id ORDER BY p.id DESC').fetchall()
    edit=None; variants=[]
    if request.args.get('edit'):
        edit=c.execute('SELECT * FROM products WHERE id=?',(request.args['edit'],)).fetchone()
        if not edit: c.close(); abort(404)
        variants=c.execute('SELECT * FROM variants WHERE product_id=? AND active=1',(edit['id'],)).fetchall()
    c.close(); return render_template('products.html',products=rows,edit=edit,variants=variants)

@app.route('/products/<int:pid>/delete',methods=['POST'])
@logged_in
@admin_only
def delete_product(pid):
    c=conn(); c.execute('UPDATE products SET active=0 WHERE id=?',(pid,)); c.commit(); c.close()
    flash('Product removed from employee selection. Existing orders remain available.'); return redirect(url_for('products_admin'))

@app.route('/reports')
@logged_in
@admin_only
def reports():
    local=datetime.now(ZoneInfo('Asia/Damascus')).date(); period=request.args.get('period','daily')
    if period not in {'daily','weekly','monthly','custom'}: abort(400)
    try:
        anchor=datetime.strptime(request.args.get('date',local.isoformat()),'%Y-%m-%d').date()
        if period=='daily': first=last=anchor
        elif period=='weekly': first=anchor-timedelta(days=anchor.weekday()); last=first+timedelta(days=6)
        elif period=='monthly':
            first=anchor.replace(day=1); last=(first.replace(day=28)+timedelta(days=4)).replace(day=1)-timedelta(days=1)
        else:
            first=datetime.strptime(request.args.get('start',local.isoformat()),'%Y-%m-%d').date(); last=datetime.strptime(request.args.get('end',local.isoformat()),'%Y-%m-%d').date()
        if last<first: raise ValueError()
    except ValueError: flash('Enter a valid date range.'); return redirect(url_for('reports'))
    def utc(day): return datetime.combine(day,datetime.min.time(),ZoneInfo('Asia/Damascus')).astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
    where='o.created_at>=? AND o.created_at<? AND o.deleted_at IS NULL'; args=[utc(first),utc(last+timedelta(days=1))]
    status=request.args.get('status','Completed')
    if status not in {'Completed','New','Processing','Cancelled','all'}: abort(400)
    if status!='all': where+=' AND o.status=?'; args.append(status)
    employee=request.args.get('employee',''); province=request.args.get('province','')
    if employee: where+=' AND o.employee_id=?'; args.append(employee)
    if province: where+=' AND o.province=?'; args.append(province)
    c=conn()
    employees=c.execute("SELECT id,username FROM users WHERE role='employee'").fetchall()
    data=c.execute('SELECT o.id,o.order_no,o.created_at,o.status,o.province,u.username employee,i.product,i.color,i.size,i.quantity,i.price_cents FROM orders o JOIN users u ON u.id=o.employee_id JOIN order_items i ON i.order_id=o.id WHERE '+where+' ORDER BY o.id DESC',args).fetchall(); c.close()
    if request.args.get('export')=='csv':
        stream=io.StringIO(); writer=csv.writer(stream); writer.writerow(['Order','Created UTC','Status','Employee','Province','Product','Color','Size','Pieces','Unit price USD','Total USD'])
        def safe(x): return "'"+x if isinstance(x,str) and x.startswith(('=','+','-','@','\t','\r','\n')) else x
        for r in data: writer.writerow([safe(r['order_no']),r['created_at'],r['status'],safe(r['employee']),safe(r['province']),safe(r['product']),safe(r['color']),safe(r['size']),r['quantity'],f"{r['price_cents']/100:.2f}",f"{r['quantity']*r['price_cents']/100:.2f}"])
        return Response('\ufeff'+stream.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=clothing_report.csv'})
    groups={k:{} for k in ('employee','product','province')}
    for r in data:
        for key in groups:
            label=r[key] or 'Not recorded (older order)'
            g=groups[key].setdefault(label,{'orders':set(),'pieces':0,'cents':0}); g['orders'].add(r['id']); g['pieces']+=r['quantity']; g['cents']+=r['quantity']*r['price_cents']
    for key in groups: groups[key]=sorted(groups[key].items(),key=lambda pair:pair[1]['pieces'],reverse=True)
    return render_template('reports.html',data=data,groups=groups,total_orders=len({r['id'] for r in data}),pieces=sum(r['quantity'] for r in data),cents=sum(r['quantity']*r['price_cents'] for r in data),employees=employees,period=period,anchor=anchor,first=first,last=last,status=status,employee=employee,province=province)


init_db()

if __name__=='__main__':
    app.run(debug=not CLOUD_MODE)
