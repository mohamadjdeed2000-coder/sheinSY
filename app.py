from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash, Response
import sqlite3, os, uuid, math, mimetypes
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app=Flask(__name__); app.secret_key=os.environ.get('SECRET_KEY','change-this-secret')
BASE=os.path.dirname(os.path.abspath(__file__)); DB=os.path.join(BASE,'sheinsy.db'); UP=os.path.join(BASE,'static','uploads')
os.makedirs(UP,exist_ok=True)
WHATSAPP=os.environ.get('WHATSAPP_NUMBER','971500000000'); ADMIN_PASSWORD=os.environ.get('ADMIN_PASSWORD','Admin@12345')
AED_RATE=3.6725
CATEGORIES=['Makeup','Skin Care','Bags']; STATUSES=['New','Confirmed','Preparing','Shipped','Delivered','Cancelled']
ALLOWED_IMAGES={'png','jpg','jpeg','webp','gif'}; ALLOWED_VIDEOS={'mp4','webm','mov','m4v'}

def db():
    c=sqlite3.connect(DB); c.row_factory=sqlite3.Row; return c

def ensure_column(c, table, col, definition):
    cols=[r['name'] for r in c.execute(f'PRAGMA table_info({table})').fetchall()]
    if col not in cols: c.execute(f'ALTER TABLE {table} ADD COLUMN {col} {definition}')

def init_db():
    c=db(); c.executescript('''
    CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,brand TEXT,price REAL NOT NULL,description TEXT,image TEXT,sizes TEXT,colors TEXT,stock INTEGER DEFAULT 0,delivery_days INTEGER DEFAULT 3,active INTEGER DEFAULT 1,created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT,order_no TEXT UNIQUE,name TEXT,phone TEXT,city TEXT,address TEXT,notes TEXT,product_id INTEGER,product_name TEXT,size TEXT,color TEXT,qty INTEGER DEFAULT 1,unit_price REAL,total REAL,status TEXT DEFAULT 'New',created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS admins(id INTEGER PRIMARY KEY AUTOINCREMENT,username TEXT UNIQUE,password_hash TEXT);
    CREATE TABLE IF NOT EXISTS product_media(id INTEGER PRIMARY KEY AUTOINCREMENT,product_id INTEGER NOT NULL,filename TEXT NOT NULL,media_type TEXT NOT NULL,sort_order INTEGER DEFAULT 0,created_at DATETIME DEFAULT CURRENT_TIMESTAMP);
    ''')
    ensure_column(c,'products','category',"TEXT DEFAULT 'Makeup'"); ensure_column(c,'products','deleted','INTEGER DEFAULT 0')
    ensure_column(c,'orders','deleted','INTEGER DEFAULT 0'); ensure_column(c,'orders','customer_action',"TEXT DEFAULT ''")
    if not c.execute('SELECT 1 FROM admins WHERE username=?',('admin',)).fetchone(): c.execute('INSERT INTO admins(username,password_hash) VALUES(?,?)',('admin',generate_password_hash(ADMIN_PASSWORD)))
    if not c.execute('SELECT 1 FROM products').fetchone():
        c.execute('INSERT INTO products(name,brand,price,description,sizes,colors,stock,delivery_days,category) VALUES(?,?,?,?,?,?,?,?,?)',('Classic Makeup Set','sheinSY',129,'A stylish sheinSY starter product.','','Pink,Beige',20,3,'Makeup'))
    c.commit(); c.close()
init_db()

def save_product_media(files, product_id, c):
    saved=[]
    start=c.execute('SELECT COALESCE(MAX(sort_order),-1)+1 n FROM product_media WHERE product_id=?',(product_id,)).fetchone()['n']
    for idx,f in enumerate(files):
        if not f or not f.filename: continue
        ext=f.filename.rsplit('.',1)[-1].lower() if '.' in f.filename else ''
        if ext not in ALLOWED_IMAGES|ALLOWED_VIDEOS: continue
        media_type='image' if ext in ALLOWED_IMAGES else 'video'
        fn=uuid.uuid4().hex[:10]+'_'+secure_filename(f.filename)
        f.save(os.path.join(UP,fn))
        c.execute('INSERT INTO product_media(product_id,filename,media_type,sort_order) VALUES(?,?,?,?)',(product_id,fn,media_type,start+idx))
        saved.append((fn,media_type))
    return saved

def get_product_media(c, product_id, legacy_image=''):
    rows=[dict(r) for r in c.execute('SELECT * FROM product_media WHERE product_id=? ORDER BY sort_order,id',(product_id,)).fetchall()]
    if legacy_image and not any(r['filename']==legacy_image for r in rows):
        rows.insert(0,{'id':0,'product_id':product_id,'filename':legacy_image,'media_type':'image','sort_order':-1})
    return rows

def lang(): return session.get('lang','en')

def visitor_country():
    # In production (Render/Cloudflare/etc.), proxy headers normally contain the public client IP.
    # We use a lightweight public-IP country lookup only once, then remember the result in session.
    if session.get('country_code'): return session['country_code']
    ip=(request.headers.get('CF-Connecting-IP') or request.headers.get('X-Forwarded-For','').split(',')[0].strip() or request.remote_addr or '')
    country=''
    if ip and ip not in ('127.0.0.1','::1'):
        try:
            import urllib.request, json
            with urllib.request.urlopen(f'https://ipapi.co/{ip}/country/', timeout=1.5) as r:
                country=r.read().decode().strip().upper()
        except Exception:
            country=''
    session['country_code']=country
    return country

def current_currency():
    manual=session.get('currency')
    if manual in ('USD','AED'): return manual
    return 'AED' if visitor_country()=='AE' else 'USD'

def money(value):
    value=float(value or 0)
    if current_currency()=='AED': return f'AED {value*AED_RATE:,.2f}'
    return f'$ {value:,.2f}'

@app.context_processor
def ctx(): return dict(lang=lang(), whatsapp=WHATSAPP, categories=CATEGORIES, statuses=STATUSES, currency=current_currency(), money=money, aed_rate=AED_RATE)

@app.route('/currency/<code>')
def set_currency(code):
    code=code.upper()
    if code in ('USD','AED'): session['currency']=code
    return redirect(request.referrer or url_for('home'))
@app.route('/language/<code>')
def language(code):
    if code in ('en','ar'): session['lang']=code
    return redirect(request.referrer or url_for('home'))

@app.route('/')
def home():
    q=request.args.get('q','').strip(); category=request.args.get('category','').strip(); c=db()
    sql='SELECT * FROM products WHERE active=1 AND deleted=0'; args=[]
    if category in CATEGORIES: sql+=' AND category=?'; args.append(category)
    if q: sql+=' AND (name LIKE ? OR brand LIKE ? OR description LIKE ?)'; args += [f'%{q}%']*3
    sql+=' ORDER BY id DESC'; products=c.execute(sql,args).fetchall(); c.close()
    return render_template('index.html',products=products,q=q,selected_category=category)
@app.route('/product/<int:pid>')
def product(pid):
    c=db(); p=c.execute('SELECT * FROM products WHERE id=? AND active=1 AND deleted=0',(pid,)).fetchone()
    if not p: c.close(); return 'Product not found',404
    media=get_product_media(c,pid,p['image']); c.close()
    return render_template('product.html',p=p,media=media)
@app.route('/favorites')
def favorites():
    ids=session.get('favorites',[]); c=db(); ps=[]
    if ids: ps=c.execute('SELECT * FROM products WHERE deleted=0 AND active=1 AND id IN (%s)'%','.join('?'*len(ids)),ids).fetchall()
    c.close(); return render_template('favorites.html',products=ps)
@app.post('/favorite/<int:pid>')
def favorite(pid):
    ids=session.get('favorites',[])
    if pid in ids: ids.remove(pid)
    else: ids.append(pid)
    session['favorites']=ids; return jsonify(ok=True,favorite=pid in ids,count=len(ids))
@app.route('/checkout/<int:pid>',methods=['GET','POST'])
def checkout(pid):
    c=db(); p=c.execute('SELECT * FROM products WHERE id=? AND active=1 AND deleted=0',(pid,)).fetchone()
    if not p: c.close(); return 'Product not found',404
    size=request.values.get('size',''); color=request.values.get('color',''); qty=max(1,int(request.values.get('qty',1) or 1))
    if request.method=='POST':
        no='SY'+uuid.uuid4().hex[:8].upper(); total=float(p['price'])*qty; phone=request.form['phone'].strip()
        c.execute('INSERT INTO orders(order_no,name,phone,city,address,notes,product_id,product_name,size,color,qty,unit_price,total) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)',(no,request.form['name'],phone,request.form['city'],request.form['address'],request.form.get('notes',''),pid,p['name'],size,color,qty,p['price'],total)); c.commit(); c.close(); session['my_orders_phone']=phone
        return redirect(url_for('confirmation',order_no=no))
    c.close(); return render_template('checkout.html',p=p,size=size,color=color,qty=qty)
@app.route('/confirmation/<order_no>')
def confirmation(order_no):
    c=db(); o=c.execute('SELECT * FROM orders WHERE order_no=? AND deleted=0',(order_no,)).fetchone(); p=c.execute('SELECT delivery_days FROM products WHERE id=?',(o['product_id'],)).fetchone() if o else None; c.close()
    if not o:return 'Order not found',404
    return render_template('confirmation.html',o=o,days=(p['delivery_days'] if p else 3))
@app.route('/my-orders',methods=['GET','POST'])
def my_orders():
    phone=(request.form.get('phone') if request.method=='POST' else request.args.get('phone')) or session.get('my_orders_phone','')
    phone=phone.strip(); orders=[]
    if phone:
        session['my_orders_phone']=phone; c=db(); orders=c.execute('SELECT * FROM orders WHERE phone=? AND deleted=0 ORDER BY id DESC',(phone,)).fetchall(); c.close()
    return render_template('my_orders.html',orders=orders,phone=phone)
@app.route('/order/<order_no>/edit',methods=['GET','POST'])
def customer_edit_order(order_no):
    phone=session.get('my_orders_phone',''); c=db(); o=c.execute('SELECT * FROM orders WHERE order_no=? AND phone=? AND deleted=0',(order_no,phone)).fetchone()
    if not o: c.close(); return 'Order not found',404
    if o['status'] not in ('New','Confirmed'): c.close(); flash('This order can no longer be edited.'); return redirect(url_for('my_orders'))
    if request.method=='POST':
        c.execute("UPDATE orders SET name=?,city=?,address=?,notes=?,size=?,color=?,qty=?,total=unit_price*?,customer_action='Edit requested' WHERE id=?",(request.form['name'],request.form['city'],request.form['address'],request.form.get('notes',''),request.form.get('size',''),request.form.get('color',''),max(1,int(request.form.get('qty',1))),max(1,int(request.form.get('qty',1))),o['id'])); c.commit(); c.close(); flash('Your changes were saved and the admin was notified.'); return redirect(url_for('my_orders'))
    p=c.execute('SELECT * FROM products WHERE id=?',(o['product_id'],)).fetchone(); c.close(); return render_template('edit_order.html',o=o,p=p)
@app.post('/order/<order_no>/cancel')
def customer_cancel_order(order_no):
    phone=session.get('my_orders_phone',''); c=db(); o=c.execute('SELECT * FROM orders WHERE order_no=? AND phone=? AND deleted=0',(order_no,phone)).fetchone()
    if o and o['status'] not in ('Shipped','Delivered','Cancelled'): c.execute("UPDATE orders SET status='Cancelled',customer_action='Cancel requested' WHERE id=?",(o['id'],)); c.commit()
    c.close(); return redirect(url_for('my_orders'))

def admin_required(): return session.get('admin')
@app.route('/admin/login',methods=['GET','POST'])
def admin_login():
    if request.method=='POST':
        username=request.form.get('username','').strip()
        password=request.form.get('password','')
        # Admin credentials are controlled by Render's ADMIN_PASSWORD environment variable.
        # This avoids stale passwords stored in a temporary SQLite database.
        if username == 'admin' and password == ADMIN_PASSWORD:
            session['admin']=True
            return redirect(url_for('admin_dashboard'))
        flash('Invalid username or password')
    return render_template('admin_login.html')
@app.route('/admin/logout')
def admin_logout(): session.pop('admin',None); return redirect(url_for('admin_login'))

def order_filter_sql():
    q=request.args.get('q','').strip(); status=request.args.get('status','').strip(); sql=' WHERE deleted=0'; args=[]
    if status in STATUSES: sql+=' AND status=?'; args.append(status)
    if q: sql+=' AND (order_no LIKE ? OR name LIKE ? OR phone LIKE ? OR product_name LIKE ?)'; args += [f'%{q}%']*4
    return sql,args,q,status
@app.route('/admin')
def admin_dashboard():
    if not admin_required(): return redirect(url_for('admin_login'))
    c=db(); where,args,q,status=order_filter_sql(); orders=c.execute('SELECT * FROM orders'+where+' ORDER BY id DESC LIMIT 20',args).fetchall(); counts={'orders':c.execute('SELECT COUNT(*) n FROM orders WHERE deleted=0').fetchone()['n'],'new':c.execute("SELECT COUNT(*) n FROM orders WHERE deleted=0 AND status='New'").fetchone()['n'],'products':c.execute('SELECT COUNT(*) n FROM products WHERE active=1 AND deleted=0').fetchone()['n'],'cancelled':c.execute("SELECT COUNT(*) n FROM orders WHERE deleted=0 AND status='Cancelled'").fetchone()['n']}; c.close(); return render_template('admin_dashboard.html',orders=orders,counts=counts,q=q,status=status)
@app.route('/admin/orders')
def admin_orders():
    if not admin_required(): return redirect(url_for('admin_login'))
    page=max(1,int(request.args.get('page',1))); per=20; where,args,q,status=order_filter_sql(); c=db(); total=c.execute('SELECT COUNT(*) n FROM orders'+where,args).fetchone()['n']; orders=c.execute('SELECT * FROM orders'+where+' ORDER BY id DESC LIMIT ? OFFSET ?',args+[per,(page-1)*per]).fetchall(); c.close(); return render_template('admin_orders.html',orders=orders,page=page,pages=max(1,math.ceil(total/per)),q=q,status=status,total=total)
@app.route('/admin/order/<int:oid>')
def admin_order_details(oid):
    if not admin_required(): return redirect(url_for('admin_login'))
    c=db(); o=c.execute('SELECT * FROM orders WHERE id=? AND deleted=0',(oid,)).fetchone(); c.close()
    if not o: return 'Order not found',404
    return render_template('admin_order_details.html',o=o)

@app.route('/admin/order/<int:oid>/download')
def download_order_details(oid):
    if not admin_required(): return redirect(url_for('admin_login'))
    c=db(); o=c.execute('SELECT * FROM orders WHERE id=?',(oid,)).fetchone(); c.close()
    if not o: return 'Order not found',404
    lines=[
        'sheinSY - Order Details',
        '======================',
        f"Order Number: {o['order_no']}", f"Date: {o['created_at']}", f"Status: {o['status']}",
        '', 'BUYER INFORMATION', '-----------------',
        f"Name: {o['name']}", f"Phone: {o['phone']}", f"City / Area: {o['city']}", f"Address: {o['address']}", f"Notes: {o['notes'] or '-'}",
        '', 'ORDER INFORMATION', '-----------------',
        f"Product: {o['product_name']}", f"Size: {o['size'] or '-'}", f"Color: {o['color'] or '-'}", f"Quantity: {o['qty']}",
        f"Unit Price: USD $ {o['unit_price']:.2f}", f"Total: USD $ {o['total']:.2f}", f"Customer Request: {o['customer_action'] or '-'}"
    ]
    content='\n'.join(lines)
    filename=f"sheinSY_order_{o['order_no']}.txt"
    return Response(content, mimetype='text/plain; charset=utf-8', headers={'Content-Disposition':f'attachment; filename="{filename}"'})

@app.post('/admin/order/<int:oid>/status')
def order_status(oid):
    if not admin_required(): return redirect(url_for('admin_login'))
    status=request.form['status']
    if status in STATUSES:
        c=db(); c.execute("UPDATE orders SET status=?, customer_action=CASE WHEN ? IN ('Confirmed','Preparing','Shipped','Delivered') THEN '' ELSE customer_action END WHERE id=?",(status,status,oid)); c.commit(); c.close()
    return redirect(request.referrer or url_for('admin_orders'))
@app.post('/admin/order/<int:oid>/delete')
def delete_order(oid):
    if not admin_required(): return redirect(url_for('admin_login'))
    c=db(); c.execute('UPDATE orders SET deleted=1 WHERE id=?',(oid,)); c.commit(); c.close(); return redirect(request.referrer or url_for('admin_orders'))
@app.route('/admin/products')
def admin_products():
    if not admin_required(): return redirect(url_for('admin_login'))
    q=request.args.get('q','').strip(); c=db(); sql='SELECT * FROM products WHERE deleted=0'; args=[]
    if q: sql+=' AND (name LIKE ? OR brand LIKE ? OR category LIKE ?)'; args=[f'%{q}%']*3
    products=c.execute(sql+' ORDER BY id DESC',args).fetchall(); c.close(); return render_template('admin_products.html',products=products,q=q)
@app.route('/admin/product/add',methods=['GET','POST'])
def add_product():
    if not admin_required(): return redirect(url_for('admin_login'))
    if request.method=='POST':
        colors=request.form.get('colors','').strip(); delivery_days=request.form.get('delivery_days','').strip()
        if not colors or not delivery_days or int(delivery_days) < 1: return 'Colors and delivery days are required.', 400
        cat=request.form.get('category','Makeup'); cat=cat if cat in CATEGORIES else 'Makeup'; c=db()
        cur=c.execute('INSERT INTO products(name,brand,price,description,image,sizes,colors,stock,delivery_days,category) VALUES(?,?,?,?,?,?,?,?,?,?)',(request.form['name'],request.form.get('brand','sheinSY'),float(request.form['price']),request.form.get('description',''),'',request.form.get('sizes',''),colors,int(request.form.get('stock',0)),int(delivery_days),cat))
        pid=cur.lastrowid; saved=save_product_media(request.files.getlist('media'),pid,c)
        cover=next((fn for fn,t in saved if t=='image'),'')
        c.execute('UPDATE products SET image=? WHERE id=?',(cover,pid)); c.commit(); c.close(); return redirect(url_for('admin_products'))
    return render_template('admin_product_form.html',p=None,media=[])
@app.route('/admin/product/<int:pid>/edit',methods=['GET','POST'])
def edit_product(pid):
    if not admin_required(): return redirect(url_for('admin_login'))
    c=db(); p=c.execute('SELECT * FROM products WHERE id=?',(pid,)).fetchone()
    if not p: c.close(); return 'Product not found',404
    if request.method=='POST':
        colors=request.form.get('colors','').strip(); delivery_days=request.form.get('delivery_days','').strip()
        if not colors or not delivery_days or int(delivery_days) < 1: c.close(); return 'Colors and delivery days are required.', 400
        cat=request.form.get('category','Makeup'); cat=cat if cat in CATEGORIES else 'Makeup'
        c.execute('UPDATE products SET name=?,brand=?,price=?,description=?,sizes=?,colors=?,stock=?,delivery_days=?,category=? WHERE id=?',(request.form['name'],request.form.get('brand',''),float(request.form['price']),request.form.get('description',''),request.form.get('sizes',''),colors,int(request.form.get('stock',0)),int(delivery_days),cat,pid))
        saved=save_product_media(request.files.getlist('media'),pid,c)
        if (not p['image'] or not str(p['image']).strip()) and saved:
            cover=next((fn for fn,t in saved if t=='image'),''); c.execute('UPDATE products SET image=? WHERE id=?',(cover,pid))
        c.commit(); c.close(); return redirect(url_for('edit_product',pid=pid))
    media=get_product_media(c,pid,p['image']); c.close(); return render_template('admin_product_form.html',p=p,media=media)

@app.post('/admin/product/<int:pid>/media/<int:mid>/delete')
def delete_product_media(pid,mid):
    if not admin_required(): return redirect(url_for('admin_login'))
    c=db(); m=c.execute('SELECT * FROM product_media WHERE id=? AND product_id=?',(mid,pid)).fetchone()
    if m:
        try: os.remove(os.path.join(UP,m['filename']))
        except OSError: pass
        c.execute('DELETE FROM product_media WHERE id=?',(mid,)); c.commit()
    c.close(); return redirect(url_for('edit_product',pid=pid))

@app.route('/admin/store-preview')
def admin_store_preview():
    if not admin_required(): return redirect(url_for('admin_login'))
    c=db(); products=c.execute('SELECT * FROM products WHERE active=1 AND deleted=0 ORDER BY id DESC').fetchall(); c.close()
    return render_template('admin_store_preview.html',products=products,selected_category='',q='',preview_mode=True)
@app.post('/admin/product/<int:pid>/delete')
def delete_product(pid):
    if not admin_required(): return redirect(url_for('admin_login'))
    c=db(); c.execute('UPDATE products SET deleted=1 WHERE id=?',(pid,)); c.commit(); c.close(); return redirect(url_for('admin_products'))
@app.route('/admin/trash')
def admin_trash():
    if not admin_required(): return redirect(url_for('admin_login'))
    c=db(); orders=c.execute('SELECT * FROM orders WHERE deleted=1 ORDER BY id DESC').fetchall(); products=c.execute('SELECT * FROM products WHERE deleted=1 ORDER BY id DESC').fetchall(); c.close(); return render_template('admin_trash.html',orders=orders,products=products)
@app.post('/admin/trash/<kind>/<int:item_id>/restore')
def restore_item(kind,item_id):
    if not admin_required(): return redirect(url_for('admin_login'))
    c=db()
    if kind=='order': c.execute('UPDATE orders SET deleted=0 WHERE id=?',(item_id,))
    elif kind=='product': c.execute('UPDATE products SET deleted=0,active=1 WHERE id=?',(item_id,))
    c.commit(); c.close(); return redirect(url_for('admin_trash'))
@app.get('/admin/api/new-orders')
def new_orders_api():
    if not admin_required(): return jsonify(count=0),401
    c=db(); n=c.execute("SELECT COUNT(*) n FROM orders WHERE deleted=0 AND status='New'").fetchone()['n']; c.close(); return jsonify(count=n)
if __name__=='__main__': app.run(debug=True)
