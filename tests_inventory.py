import os,tempfile,sys,importlib.util,concurrent.futures
from werkzeug.datastructures import MultiDict
os.environ['DATA_DIR']=tempfile.mkdtemp()
spec=importlib.util.spec_from_file_location('store',str(__import__('pathlib').Path(__file__).with_name('app.py'))); m=importlib.util.module_from_spec(spec);sys.modules['store']=m;spec.loader.exec_module(m)
a=m.app;a.testing=True
admin=a.test_client();emp=a.test_client()
def identity(client,uid,role):
 with client.session_transaction() as s:s.update(user_id=uid,role=role,username=role,_csrf='test')
identity(admin,1,'admin');identity(emp,2,'employee')
def post(client,path,fields):
 return client.post(path,data=MultiDict([('_csrf','test')]+fields),follow_redirects=True)
r=post(admin,'/products',[('name','Pants'),('price','12.50'),('color[]','Black'),('size[]','S'),('stock[]','2'),('color[]','Black'),('size[]','M'),('stock[]','5')]);assert r.status_code==200
assert emp.get('/products').status_code==403
assert admin.get('/reports').status_code==200
base=[('customer_name','Customer'),('phone','0999999999'),('province','Damascus'),('area','Street 1'),('gender','Man'),('variant_id[]','1'),('quantity[]','2')]
r=post(emp,'/new-order',base);assert b'Order submitted successfully' in r.data,r.data
c=m.conn();assert c.execute('SELECT stock FROM variants WHERE id=1').fetchone()[0]==0;c.close()
r=post(emp,'/new-order',base);assert b'insufficient stock' in r.data
c=m.conn();assert c.execute('SELECT COUNT(*) FROM orders').fetchone()[0]==1;c.close()
r=post(emp,'/my-orders/1/edit',[(k,'2' if k=='variant_id[]' else '3' if k=='quantity[]' else v) for k,v in base]);assert r.status_code==200
c=m.conn();assert [r[0] for r in c.execute('SELECT stock FROM variants ORDER BY id')]==[2,2];c.close()
r=post(emp,'/my-orders/1/cancel',[('reason','Customer changed mind')]);assert r.status_code==200
c=m.conn();assert [r[0] for r in c.execute('SELECT stock FROM variants ORDER BY id')]==[2,5];c.close()
post(admin,'/order/1',[('status','Completed')]);r=admin.get('/reports');assert b'37.50' in r.data and b'1 orders' in r.data,r.data
assert admin.get('/reports?export=csv').status_code==200
assert b'Damascus' in admin.get('/order/1').data
post(admin,'/products/1/delete',[]);assert emp.get('/inventory.json').json==[]
# Re-enable and compete for last unit.
post(admin,'/products',[('product_id','1'),('name','Pants'),('price','12.50'),('color[]','Black'),('size[]','S'),('stock[]','1')])
def submit(_):
 client=a.test_client();identity(client,2,'employee');return post(client,'/new-order',[(k,'1' if k=='quantity[]' else v) for k,v in base]).data
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(submit,range(2)))
assert sum(b'Order submitted successfully' in r for r in results)==1
c=m.conn();assert c.execute('SELECT stock FROM variants WHERE id=1').fetchone()[0]==0;c.close()
m.init_db();m.init_db()
assert a.test_client().post('/products',data={}).status_code==400
print('PASS: admin products, role permissions, create/edit/cancel stock, reports/CSV, removal, concurrent last-unit orders, repeated migration')
