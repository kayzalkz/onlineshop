import mimetypes

# Force Python to recognize web files so Cloudflare 'nosniff' doesn't block them
mimetypes.add_type('text/css', '.css')
mimetypes.add_type('application/javascript', '.js')
mimetypes.add_type('image/png', '.png')
mimetypes.add_type('image/jpeg', '.jpg')
mimetypes.add_type('image/jpeg', '.jpeg')
mimetypes.add_type('image/svg+xml', '.svg')
mimetypes.add_type('font/woff', '.woff')
mimetypes.add_type('font/woff2', '.woff2')
import os
import io
from functools import wraps
from datetime import datetime, timedelta
from decimal import Decimal
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file, abort
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_required, current_user, login_user, logout_user
from flask_babel import Babel, _
from sqlalchemy import func
import pandas as pd
from werkzeug.utils import secure_filename
from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors

# NEW PRODUCTION IMPORTS
from dotenv import load_dotenv
from flask_wtf.csrf import CSRFProtect
from flask_migrate import Migrate

# Load the hidden .env file
load_dotenv()

app = Flask(__name__)

# Use environment variables for security
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fallback_key')
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Remove app.run(debug=True) from the bottom of your file later!

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

babel = Babel(app, locale_selector=lambda: session.get('lang', 'en'))

# Initialize Database & Security
db = SQLAlchemy(app)
migrate = Migrate(app, db) # Enables safe database upgrades
csrf = CSRFProtect(app)    # Blocks Cross-Site Request Forgery attacks
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

def get_mmt_time():
    return datetime.utcnow() + timedelta(hours=6, minutes=30)

# ==========================================
# CUSTOM SECURITY DECORATOR (RBAC)
# ==========================================
def permission_required(permission_name):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for('login'))
            if getattr(current_user.role_obj, permission_name) is not True:
                flash(_('Access Denied. You do not have permission to view this page.'), 'danger')
                return redirect(url_for('dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ==========================================
# DATABASE MODELS
# ==========================================
class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), default="KZL Clothing")
    address = db.Column(db.Text)
    phone = db.Column(db.String(50))
    logo_filename = db.Column(db.String(150))

class Role(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), unique=True, nullable=False)
    pos_access = db.Column(db.Boolean, default=False)
    inventory_access = db.Column(db.Boolean, default=False)
    supplier_access = db.Column(db.Boolean, default=False)
    report_access = db.Column(db.Boolean, default=False)
    manage_users_access = db.Column(db.Boolean, default=False) 
    users = db.relationship('User', backref='role_obj', lazy=True)

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password_hash = db.Column(db.String(128))
    role_id = db.Column(db.Integer, db.ForeignKey('role.id'), nullable=False)
    
    @property
    def is_admin(self):
        return self.role_obj and self.role_obj.manage_users_access

class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150))
    phone = db.Column(db.String(20))
    balance = db.Column(db.Numeric(10, 2), default=0.00)

class Supplier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    contact_person = db.Column(db.String(150))
    phone = db.Column(db.String(50))
    address = db.Column(db.Text)
    balance = db.Column(db.Numeric(10, 2), default=0.00) 
    products = db.relationship('Product', backref='supplier', lazy=True)

class SupplierPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_method = db.Column(db.String(50))
    reference_note = db.Column(db.String(150))
    timestamp = db.Column(db.DateTime, default=get_mmt_time)
    supplier = db.relationship('Supplier', backref='payments', lazy=True)

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150))
    category = db.Column(db.String(50))
    size = db.Column(db.String(20))
    color = db.Column(db.String(50)) 
    purchase_price = db.Column(db.Numeric(10, 2))
    selling_price = db.Column(db.Numeric(10, 2))
    stock = db.Column(db.Integer, default=0)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=True)

class PurchaseOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    status = db.Column(db.String(20), default='Pending') 
    total_amount = db.Column(db.Numeric(10, 2), default=0.00)
    timestamp = db.Column(db.DateTime, default=get_mmt_time)
    supplier = db.relationship('Supplier', backref='purchase_orders', lazy=True)
    items = db.relationship('POItem', backref='purchase_order', lazy=True, cascade="all, delete-orphan")

class POItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    po_id = db.Column(db.Integer, db.ForeignKey('purchase_order.id'), nullable=False)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    unit_cost = db.Column(db.Numeric(10, 2), nullable=False)
    product = db.relationship('Product', backref='po_items')

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    total_amount = db.Column(db.Numeric(10, 2))
    amount_paid = db.Column(db.Numeric(10, 2))
    timestamp = db.Column(db.DateTime, default=get_mmt_time)
    transaction_type = db.Column(db.String(20))
    payment_method = db.Column(db.String(50))
    payment_info = db.Column(db.String(100))
    customer_id = db.Column(db.Integer, db.ForeignKey('customer.id'), nullable=True)
    items = db.relationship('SaleItem', backref='sale', lazy=True, cascade="all, delete-orphan")
    customer = db.relationship('Customer', backref='sales', lazy=True) 

class SaleItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sale_id = db.Column(db.Integer, db.ForeignKey('sale.id'), nullable=False)
    product_name = db.Column(db.String(150))
    quantity = db.Column(db.Integer)
    price = db.Column(db.Numeric(10, 2))
    purchase_cost = db.Column(db.Numeric(10, 2))

class StockLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    product_id = db.Column(db.Integer, db.ForeignKey('product.id'), nullable=False)
    quantity = db.Column(db.Integer) 
    action = db.Column(db.String(100)) 
    timestamp = db.Column(db.DateTime, default=get_mmt_time)
    product = db.relationship('Product', backref='stock_logs')

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    category = db.Column(db.String(50), nullable=False) 
    description = db.Column(db.String(150))
    timestamp = db.Column(db.DateTime, default=get_mmt_time)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.context_processor
def inject_company():
    return dict(company=Company.query.first())

# ==========================================
# DASHBOARD ROUTE
# ==========================================
@app.route('/')
@login_required
def dashboard():
    today = get_mmt_time().date() 
    total_sales = db.session.query(func.sum(Sale.total_amount)).filter(func.date(Sale.timestamp) == today).scalar() or 0
    total_stock = db.session.query(func.sum(Product.stock)).scalar() or 0
    active_credit = db.session.query(func.sum(Customer.balance)).filter(Customer.balance > 0).scalar() or 0
    supplier_debt = db.session.query(func.sum(Supplier.balance)).filter(Supplier.balance > 0).scalar() or 0
    
    top_items = db.session.query(SaleItem.product_name, func.sum(SaleItem.quantity).label('total_sold')).group_by(SaleItem.product_name).order_by(func.sum(SaleItem.quantity).desc()).limit(5).all()
    top_customers = db.session.query(Customer.name, func.sum(Sale.total_amount).label('total_spent')).join(Sale).group_by(Customer.id).order_by(func.sum(Sale.total_amount).desc()).limit(5).all()
    top_suppliers = db.session.query(Supplier.name, func.sum(PurchaseOrder.total_amount).label('total_ordered')).join(PurchaseOrder).group_by(Supplier.id).order_by(func.sum(PurchaseOrder.total_amount).desc()).limit(5).all()
    
    chart_data = [float(db.session.query(func.sum(Sale.total_amount)).filter(func.date(Sale.timestamp) == (today - timedelta(days=i))).scalar() or 0) for i in range(6, -1, -1)]

    return render_template('dashboard.html', total_sales=total_sales, total_stock=total_stock, active_credit=active_credit, supplier_debt=supplier_debt,
                           top_items=top_items, top_customers=top_customers, top_suppliers=top_suppliers, chart_data=chart_data)

# ==========================================
# POS & CUSTOMERS
# ==========================================
@app.route('/pos')
@login_required
@permission_required('pos_access')
def pos():
    customers = Customer.query.all()
    products = Product.query.filter(Product.stock > 0).all()
    recent_sales = Sale.query.order_by(Sale.timestamp.desc()).limit(15).all()
    last_sale_id = session.pop('last_sale_id', None)
    last_sale = Sale.query.get(last_sale_id) if last_sale_id else None
    return render_template('pos.html', customers=customers, products=products, last_sale=last_sale, recent_sales=recent_sales)

@app.route('/process_sale', methods=['POST'])
@login_required
@permission_required('pos_access')
def process_sale():
    total_amount = Decimal(request.form.get('total_amount', '0'))
    amount_paid = Decimal(request.form.get('amount_paid', '0'))
    cust_id = request.form.get('customer_id')
    p_method = request.form.get('payment_method')
    p_info = request.form.get('payment_info', '')
    cart_data = request.form.get('cart_data', '')

    if not cart_data:
        flash(_('Cart is empty!'), 'danger')
        return redirect(url_for('pos'))

    if not cust_id and amount_paid > total_amount: amount_paid = total_amount
    t_type = 'paid' if amount_paid >= total_amount else 'credit'
    editing_sale_id = session.pop('editing_sale_id', None)
    
    if editing_sale_id:
        sale = Sale.query.get(editing_sale_id)
        if sale:
            if sale.customer_id:
                old_cust = Customer.query.get(sale.customer_id)
                if old_cust: old_cust.balance -= (sale.total_amount - sale.amount_paid)
            products = Product.query.all()
            for old_item in sale.items:
                matched = next((p for p in products if p.name in old_item.product_name), None)
                if matched: matched.stock += old_item.quantity
            SaleItem.query.filter_by(sale_id=sale.id).delete()
            sale.total_amount, sale.amount_paid, sale.transaction_type, sale.payment_method, sale.payment_info, sale.customer_id = total_amount, amount_paid, t_type, p_method, p_info, cust_id if cust_id else None
    else:
        sale = Sale(total_amount=total_amount, amount_paid=amount_paid, transaction_type=t_type, payment_method=p_method, payment_info=p_info, customer_id=cust_id if cust_id else None, timestamp=get_mmt_time())
        db.session.add(sale)
        db.session.flush()

    # ==========================================
    # ENTERPRISE FIX: SECURE INVENTORY DEDUCTION
    # ==========================================
    for item_str in cart_data.split(','):
        if item_str:
            p_id, qty = item_str.split(':')
            qty = int(qty)
            
            # 1. LOCK THE DATABASE ROW for this specific product
            product = Product.query.with_for_update().get(int(p_id))
            
            if product:
                # 2. SAFETY CHECK: Ensure we actually have the stock (skip this check if we are just editing an old sale)
                if product.stock < qty and not editing_sale_id:
                    db.session.rollback() # Cancel the whole receipt
                    flash(_(f'Checkout Failed! Another cashier just bought the last {product.name}.'), 'danger')
                    return redirect(url_for('pos'))

                # Proceed with the sale normally
                prod_desc = f"{product.name} ({product.size} - {product.color})" if product.color else f"{product.name} ({product.size})"
                db.session.add(SaleItem(sale_id=sale.id, product_name=prod_desc, quantity=qty, price=product.selling_price, purchase_cost=product.purchase_price))
                product.stock -= qty
    # ==========================================

    if cust_id:
        customer = Customer.query.get(cust_id)
        customer.balance += (total_amount - amount_paid)

    # Wrap the commit in a try/except block just in case the database is completely locked up
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        flash(_('Database busy. Please try processing the sale again.'), 'danger')
        return redirect(url_for('pos'))

    session.pop('edit_cart', None)
    session.pop('edit_customer', None)
    session.pop('edit_paid', None)
    session['last_sale_id'] = sale.id
    flash(_('Transaction processed successfully!'), 'success')
    return redirect(url_for('pos'))

@app.route('/edit_sale/<int:sale_id>', methods=['POST'])
@login_required
def edit_sale(sale_id):
    if not current_user.is_admin: return redirect(url_for('pos'))
    sale = Sale.query.get_or_404(sale_id)
    cart_data = {}
    products = Product.query.all()
    for item in sale.items:
        matched_product = next((p for p in products if p.name in item.product_name), None)
        if matched_product: cart_data[str(matched_product.id)] = {'name': matched_product.name, 'price': float(matched_product.selling_price), 'qty': item.quantity}
    session['edit_cart'] = cart_data
    session['edit_customer'] = sale.customer_id if sale.customer_id else ""
    session['edit_paid'] = float(sale.amount_paid)
    session['editing_sale_id'] = sale.id 
    flash(_('Editing Sale #{}. Original record is safe until you click Complete.').format(sale.id), 'info')
    return redirect(url_for('pos'))

@app.route('/cancel_edit')
@login_required
def cancel_edit():
    session.pop('editing_sale_id', None)
    session.pop('edit_cart', None)
    session.pop('edit_customer', None)
    session.pop('edit_paid', None)
    flash(_('Edit cancelled.'), 'warning')
    return redirect(url_for('pos'))

@app.route('/delete_sale/<int:sale_id>', methods=['POST'])
@login_required
def delete_sale(sale_id):
    if not current_user.is_admin: return redirect(url_for('reports'))
    sale = Sale.query.get_or_404(sale_id)
    if sale.customer_id:
        customer = Customer.query.get(sale.customer_id)
        if customer: customer.balance -= (sale.total_amount - sale.amount_paid)
    products = Product.query.all()
    for item in sale.items:
        matched = next((p for p in products if p.name in item.product_name), None)
        if matched: matched.stock += item.quantity
    SaleItem.query.filter_by(sale_id=sale.id).delete()
    db.session.delete(sale)
    db.session.commit()
    flash(_('Sale voided and stock restored.'), 'warning')
    return redirect(request.referrer or url_for('reports'))

@app.route('/receipt/<int:sale_id>')
@login_required
def receipt(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    return render_template('receipt.html', sale=sale)

@app.route('/customers', methods=['GET', 'POST'])
@login_required
@permission_required('pos_access')
def customers():
    if request.method == 'POST':
        db.session.add(Customer(name=request.form.get('name'), phone=request.form.get('phone')))
        db.session.commit()
        flash('Customer added.', 'success')
    return render_template('customers.html', customers=Customer.query.all())

@app.route('/customer/<int:customer_id>')
@login_required
@permission_required('pos_access')
def customer_detail(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    all_history = Sale.query.filter_by(customer_id=customer_id).order_by(Sale.timestamp.asc()).all()
    statement_data, current_running_bal, total_spent = [], Decimal('0'), Decimal('0')
    
    for sale in all_history:
        current_running_bal += (sale.total_amount - sale.amount_paid)
        if sale.total_amount > 0: total_spent += sale.total_amount
        statement_data.append({'date': sale.timestamp, 'ref': f"INV#{sale.id}" if sale.total_amount > 0 else "PAYMENT", 'desc': ", ".join([i.product_name for i in sale.items]) if sale.items else (sale.payment_info or "Debt Repayment"), 'debit': sale.total_amount, 'credit': sale.amount_paid, 'running_bal': current_running_bal})
    statement_data.reverse()
    return render_template('customer_detail.html', customer=customer, history=statement_data, total_spent=total_spent, now=get_mmt_time())

@app.route('/customer/repay/<int:customer_id>', methods=['POST'])
@login_required
@permission_required('pos_access')
def customer_repay(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    amount = Decimal(request.form.get('amount', '0'))
    if amount > 0:
        if request.form.get('action') in ['pay_debt', 'add_credit']: customer.balance -= amount
        db.session.add(Sale(customer_id=customer.id, total_amount=0, amount_paid=amount, payment_method=request.form.get('payment_method', 'cash'), payment_info=f"Repayment/Credit: {request.form.get('payment_info', '')}", timestamp=get_mmt_time()))
        db.session.commit()
        flash(f'Processed {amount:,.0f} MMK for {customer.name}', 'success')
    return redirect(url_for('customers'))

# ==========================================
# INVENTORY & PURCHASING
# ==========================================
@app.route('/inventory', methods=['GET', 'POST'])
@login_required
@permission_required('inventory_access')
def inventory():
    if request.method == 'POST':
        action = request.form.get('action')
        supplier_id = request.form.get('supplier_id') if request.form.get('supplier_id') != "" else None
        
        if action == 'add_product':
            name, size, color = request.form.get('name', '').strip(), request.form.get('size', '').strip(), request.form.get('color', '').strip()
            if not Product.query.filter_by(name=name, size=size, color=color).first():
                try:
                    p = Product(name=name, category=request.form.get('category'), size=size, color=color, purchase_price=Decimal(request.form.get('purchase_price', '0')), selling_price=Decimal(request.form.get('selling_price', '0')), stock=int(request.form.get('stock', '0')), supplier_id=supplier_id)
                    db.session.add(p)
                    db.session.flush()
                    if p.stock != 0: db.session.add(StockLog(product_id=p.id, quantity=p.stock, action="Initial Setup", timestamp=get_mmt_time()))
                    flash(_('Product added successfully.'), 'success')
                except ValueError: flash(_('Invalid numbers.'), 'danger')
                    
        elif action == 'edit_product':
            p = Product.query.get(request.form.get('product_id'))
            if p:
                try:
                    p.name, p.category, p.size, p.color = request.form.get('name', '').strip(), request.form.get('category', '').strip(), request.form.get('size', '').strip(), request.form.get('color', '').strip()
                    p.purchase_price, p.selling_price, p.supplier_id = Decimal(request.form.get('purchase_price', '0')), Decimal(request.form.get('selling_price', '0')), supplier_id
                    flash(_('Product updated.'), 'success')
                except ValueError: flash(_('Invalid numbers.'), 'danger')

        elif action == 'delete_product':
            p = Product.query.get(request.form.get('product_id'))
            if p:
                StockLog.query.filter_by(product_id=p.id).delete() 
                db.session.delete(p)
                flash(_('Product deleted.'), 'warning')
                
        elif action == 'adjust_stock':
            p = Product.query.get(request.form.get('product_id'))
            try:
                qty_change = int(request.form.get('qty_change', '0'))
                if p and qty_change != 0:
                    p.stock += qty_change
                    db.session.add(StockLog(product_id=p.id, quantity=qty_change, action=request.form.get('reason', 'Manual Adjustment').strip(), timestamp=get_mmt_time()))
                    flash(_('Stock adjusted.'), 'success')
            except ValueError: flash(_('Invalid adjustment.'), 'danger')
                
        db.session.commit()
        return redirect(url_for('inventory'))
    return render_template('inventory.html', products=Product.query.all(), suppliers=Supplier.query.all())

@app.route('/purchase_orders')
@login_required
@permission_required('supplier_access')
def purchase_orders():
    return render_template('purchase_orders.html', pos=PurchaseOrder.query.order_by(PurchaseOrder.timestamp.desc()).all(), suppliers=Supplier.query.all(), products=Product.query.all())

@app.route('/po/create', methods=['POST'])
@login_required
@permission_required('supplier_access')
def create_po():
    supplier_id, product_ids, quantities, costs = request.form.get('supplier_id'), request.form.getlist('product_id[]'), request.form.getlist('quantity[]'), request.form.getlist('unit_cost[]')
    if not supplier_id or not product_ids: return redirect(url_for('purchase_orders'))
    po = PurchaseOrder(supplier_id=supplier_id, status='Pending', total_amount=0)
    db.session.add(po)
    db.session.flush() 
    total_amount = Decimal('0')
    for i in range(len(product_ids)):
        if product_ids[i] and int(quantities[i]) > 0:
            qty, cost = int(quantities[i]), Decimal(costs[i])
            db.session.add(POItem(po_id=po.id, product_id=product_ids[i], quantity=qty, unit_cost=cost))
            total_amount += (cost * qty)
    po.total_amount = total_amount
    db.session.commit()
    flash(_('Purchase Order created.'), 'success')
    return redirect(url_for('purchase_orders'))

@app.route('/po/receive/<int:po_id>', methods=['POST'])
@login_required
@permission_required('supplier_access')
def receive_po(po_id):
    po = PurchaseOrder.query.get_or_404(po_id)
    if po.status == 'Pending':
        po.status = 'Received'
        po.supplier.balance += po.total_amount 
        for item in po.items:
            item.product.stock += item.quantity
            db.session.add(StockLog(product_id=item.product.id, quantity=item.quantity, action=f"Received via PO #{po.id}", timestamp=get_mmt_time()))
        db.session.commit()
        flash(_('Goods received!'), 'success')
    return redirect(url_for('purchase_orders'))

@app.route('/po/cancel/<int:po_id>', methods=['POST'])
@login_required
@permission_required('supplier_access')
def cancel_po(po_id):
    po = PurchaseOrder.query.get_or_404(po_id)
    if po.status == 'Pending':
        po.status = 'Cancelled'
        db.session.commit()
        flash(_('Purchase Order cancelled.'), 'warning')
    return redirect(url_for('purchase_orders'))

@app.route('/suppliers', methods=['GET', 'POST'])
@login_required
@permission_required('supplier_access')
def suppliers():
    if request.method == 'POST':
        action = request.form.get('action', 'add')
        if action == 'add':
            db.session.add(Supplier(name=request.form.get('name'), contact_person=request.form.get('contact_person'), phone=request.form.get('phone'), address=request.form.get('address'), balance=Decimal(request.form.get('balance', '0'))))
            flash(_('Supplier registered.'), 'success')
        elif action == 'edit':
            s = Supplier.query.get(request.form.get('supplier_id'))
            if s:
                s.name, s.contact_person, s.phone, s.balance = request.form.get('name'), request.form.get('contact_person'), request.form.get('phone'), request.form.get('balance', s.balance)
                flash(_('Supplier updated.'), 'success')
        elif action == 'delete':
            s = Supplier.query.get(request.form.get('supplier_id'))
            if s:
                if PurchaseOrder.query.filter_by(supplier_id=s.id).first() or SupplierPayment.query.filter_by(supplier_id=s.id).first():
                    flash(_('Error: Cannot delete this supplier. Has existing records.'), 'danger')
                else:
                    for p in s.products: p.supplier_id = None
                    db.session.delete(s)
                    flash(_('Supplier removed.'), 'warning')
        db.session.commit()
        return redirect(url_for('suppliers'))
    return render_template('suppliers.html', suppliers=Supplier.query.all())

@app.route('/supplier/pay/<int:supplier_id>', methods=['POST'])
@login_required
@permission_required('supplier_access')
def supplier_pay(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    try: amount = Decimal(request.form.get('amount', '0'))
    except: amount = Decimal('0')
    if amount > 0:
        supplier.balance -= amount
        db.session.add(SupplierPayment(supplier_id=supplier.id, amount=amount, payment_method=request.form.get('payment_method', 'cash'), reference_note=request.form.get('reference_note', ''), timestamp=get_mmt_time()))
        db.session.commit()
        flash(f'Payment recorded.', 'success')
    return redirect(url_for('suppliers'))

@app.route('/supplier/<int:supplier_id>')
@login_required
@permission_required('supplier_access')
def supplier_detail(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    combined = []
    for po in PurchaseOrder.query.filter_by(supplier_id=supplier_id, status='Received').all():
        combined.append({'date': po.timestamp, 'ref': f"PO#{po.id}", 'desc': f"Stock In: {sum(i.quantity for i in po.items)} items", 'debit': po.total_amount, 'credit': Decimal('0')})
    for p in SupplierPayment.query.filter_by(supplier_id=supplier_id).all():
        combined.append({'date': p.timestamp, 'ref': f"PAY#{p.id}", 'desc': f"Payment ({p.payment_method.upper()}) - {p.reference_note}", 'debit': Decimal('0'), 'credit': p.amount})
        
    combined.sort(key=lambda x: x['date'])
    statement_data, current_running_bal, total_ordered = [], Decimal('0'), Decimal('0')
    
    for item in combined:
        current_running_bal += item['debit'] - item['credit']
        total_ordered += item['debit']
        statement_data.append({'date': item['date'], 'ref': item['ref'], 'desc': item['desc'], 'debit': item['debit'], 'credit': item['credit'], 'running_bal': current_running_bal})
        
    statement_data.reverse()
    return render_template('supplier_detail.html', supplier=supplier, history=statement_data, total_ordered=total_ordered, now=get_mmt_time())

# ==========================================
# REPORTS & EXPORTS
# ==========================================
@app.route('/reports')
@login_required
@permission_required('report_access')
def reports():
    today = get_mmt_time().date() 
    daily_rev = db.session.query(func.sum(Sale.total_amount)).filter(func.date(Sale.timestamp) == today).scalar() or 0
    cash_total = db.session.query(func.sum(Sale.amount_paid)).filter(func.date(Sale.timestamp) == today, Sale.payment_method == 'cash').scalar() or 0
    digital_total = db.session.query(func.sum(Sale.amount_paid)).filter(func.date(Sale.timestamp) == today, Sale.payment_method != 'cash').scalar() or 0
    credit_total = db.session.query(func.sum(Customer.balance)).filter(Customer.balance > 0).scalar() or 0
    
    total_revenue = db.session.query(func.sum(SaleItem.quantity * SaleItem.price)).scalar() or Decimal('0')
    total_cost = db.session.query(func.sum(SaleItem.quantity * SaleItem.purchase_cost)).scalar() or Decimal('0')
    gross_profit = total_revenue - total_cost
    total_expenses = db.session.query(func.sum(Expense.amount)).scalar() or Decimal('0')
    net_profit = gross_profit - total_expenses 

    all_sales = Sale.query.order_by(Sale.timestamp.desc()).all()
    products = Product.query.all()
    customers = Customer.query.all() 
    suppliers = Supplier.query.all()
    expenses_list = Expense.query.order_by(Expense.timestamp.desc()).limit(50).all() 

    return render_template('reports.html', daily_rev=daily_rev, cash_total=cash_total, digital_total=digital_total, credit_total=credit_total,
                           all_sales=all_sales, products=products, customers=customers, suppliers=suppliers,
                           total_revenue=total_revenue, total_cost=total_cost, gross_profit=gross_profit, total_expenses=total_expenses, net_profit=net_profit, 
                           expenses_list=expenses_list)

@app.route('/add_expense', methods=['POST'])
@login_required
@permission_required('report_access')
def add_expense():
    if not current_user.is_admin: return redirect(url_for('reports'))
    try:
        amount = Decimal(request.form.get('amount', '0'))
        if amount > 0:
            db.session.add(Expense(amount=amount, category=request.form.get('category', 'Other'), description=request.form.get('description', '')))
            db.session.commit()
            flash(f'Expense recorded.', 'success')
    except Exception as e: flash('Error saving expense.', 'danger')
    return redirect(url_for('reports'))

def get_filtered_sales(request_args):
    """Helper function to filter sales based on selected date range"""
    time_frame = request_args.get('time_frame', 'all')
    start_date_str = request_args.get('start_date')
    end_date_str = request_args.get('end_date')
    
    query = Sale.query
    today = get_mmt_time()

    if time_frame == 'today':
        query = query.filter(func.date(Sale.timestamp) == today.date())
    elif time_frame == 'week':
        query = query.filter(Sale.timestamp >= (today - timedelta(days=7)).date())
    elif time_frame == 'month':
        query = query.filter(Sale.timestamp >= today.replace(day=1).date())
    elif time_frame == 'custom' and start_date_str and end_date_str:
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d') + timedelta(days=1)
        query = query.filter(Sale.timestamp >= start_date, Sale.timestamp < end_date)
        
    return query.order_by(Sale.timestamp.desc()).all(), time_frame

@app.route('/export/excel')
@login_required
@permission_required('report_access')
def export_excel():
    sales, time_frame = get_filtered_sales(request.args)
    data = []
    for s in sales:
        items_str = ", ".join([f"{i.product_name} (x{i.quantity})" for i in s.items])
        net_profit = float(s.total_amount - sum((i.purchase_cost or 0) * i.quantity for i in s.items))
        data.append({
            'Invoice Ref': f"#{s.id}", 
            'Date & Time': s.timestamp.strftime('%Y-%m-%d %H:%M'), 
            'Customer Name': s.customer.name if s.customer else 'Walk-in', 
            'Items Purchased': items_str, 
            'Total Invoice (MMK)': float(s.total_amount), 
            'Amount Paid (MMK)': float(s.amount_paid), 
            'Balance Due (MMK)': float(s.total_amount - s.amount_paid), 
            'Payment Method': s.payment_method.upper(), 
            'Net Profit (MMK)': net_profit
        })
        
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer: 
        df.to_excel(writer, index=False, sheet_name='Sales Ledger')
    output.seek(0)
    filename = f"{get_mmt_time().strftime('%d-%m-%Y')}-{time_frame.capitalize()}-Master-Ledger.xlsx"
    return send_file(output, download_name=filename, as_attachment=True)

@app.route('/export/pdf')
@login_required
@permission_required('report_access')
def export_pdf():
    sales, time_frame = get_filtered_sales(request.args)
    company = Company.query.first()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=landscape(letter), rightMargin=30, leftMargin=30, topMargin=30, bottomMargin=30)
    elements = []
    styles = getSampleStyleSheet()
    
    elements.append(Paragraph(f"<b>{company.name if company else 'Store'} - Official Sales Ledger</b>", styles['Heading1']))
    elements.append(Paragraph(f"Report Period: <b>{time_frame.upper()}</b> | Generated on: {get_mmt_time().strftime('%d %b, %Y %H:%M')}", styles['Normal']))
    elements.append(Spacer(1, 15))

    table_data = [["Inv #", "Date", "Customer", "Items Purchased", "Total (MMK)", "Paid (MMK)", "Type"]]
    for s in sales:
        items_str = ", ".join([f"{i.product_name}(x{i.quantity})" for i in s.items])
        cust_name = s.customer.name if s.customer else "Walk-in"
        table_data.append([
            f"#{s.id}", s.timestamp.strftime('%Y-%m-%d'), Paragraph(cust_name, styles['Normal']), 
            Paragraph(items_str, styles['Normal']), f"{s.total_amount:,.0f}", f"{s.amount_paid:,.0f}", s.payment_method.upper()
        ])

    t = Table(table_data, colWidths=[45, 75, 100, 250, 80, 80, 60], repeatRows=1) 
    t.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.HexColor("#1e293b")), 
        ('TEXTCOLOR', (0,0), (-1,0), colors.whitesmoke),
        ('ALIGN', (0,0), (-1,-1), 'LEFT'),
        ('ALIGN', (4,0), (5,-1), 'RIGHT'), 
        ('FONTNAME', (0,0), (-1,0), 'Helvetica-Bold'),
        ('FONTSIZE', (0,0), (-1,-1), 9),
        ('BOTTOMPADDING', (0,0), (-1,0), 10),
        ('TOPPADDING', (0,0), (-1,0), 10),
        ('BACKGROUND', (0,1), (-1,-1), colors.HexColor("#f8fafc")), 
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")), 
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
    ]))
    
    elements.append(t)
    doc.build(elements)
    buffer.seek(0)
    filename = f"{get_mmt_time().strftime('%d-%m-%Y')}-{time_frame.capitalize()}-Master-Ledger.pdf"
    return send_file(buffer, download_name=filename, as_attachment=True)

@app.route('/export/customers_excel')
@login_required
@permission_required('report_access')
def export_customers_excel():
    data = []
    for c in Customer.query.all():
        data.append({'Client ID': f"#{c.id}", 'Client Name': c.name, 'Phone Number': c.phone, 'Current Balance (MMK)': float(abs(c.balance)), 'Financial Status': "Owes Store" if c.balance > 0 else ("Store Credit" if c.balance < 0 else "Settled")})
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer: df.to_excel(writer, index=False, sheet_name='Client_Ledger_Report')
    output.seek(0)
    return send_file(output, download_name=f"Client_Financial_Report_{get_mmt_time().strftime('%Y-%m-%d')}.xlsx", as_attachment=True)

# ==========================================
# ADMIN & SYSTEM ROUTES
# ==========================================
@app.route('/roles', methods=['GET', 'POST'])
@login_required
@permission_required('manage_users_access')
def manage_roles():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'create':
            db.session.add(Role(name=request.form.get('name'), pos_access='pos_access' in request.form, inventory_access='inventory_access' in request.form, supplier_access='supplier_access' in request.form, report_access='report_access' in request.form, manage_users_access='manage_users_access' in request.form))
            flash(_('Role created.'), 'success')
        elif action == 'edit':
            role = Role.query.get(request.form.get('role_id'))
            if role and role.name != 'System Admin':
                role.name, role.pos_access, role.inventory_access, role.supplier_access, role.report_access, role.manage_users_access = request.form.get('name'), 'pos_access' in request.form, 'inventory_access' in request.form, 'supplier_access' in request.form, 'report_access' in request.form, 'manage_users_access' in request.form
                flash(_('Role updated.'), 'success')
        elif action == 'delete':
            role = Role.query.get(request.form.get('role_id'))
            if role and role.name != 'System Admin':
                if len(role.users) > 0: flash(_('Cannot delete role. Users are assigned.'), 'danger')
                else:
                    db.session.delete(role)
                    flash(_('Role deleted.'), 'warning')
        db.session.commit()
        return redirect(url_for('manage_roles'))
    return render_template('roles.html', roles=Role.query.all())

@app.route('/users', methods=['GET', 'POST'])
@login_required
@permission_required('manage_users_access')
def manage_users():
    if request.method == 'POST':
        action = request.form.get('action', 'create')
        if action == 'create':
            db.session.add(User(username=request.form.get('username'), password_hash=bcrypt.generate_password_hash(request.form.get('password')).decode('utf-8'), role_id=request.form.get('role_id')))
            flash(_('Staff account created.'), 'success')
        elif action == 'edit':
            u = User.query.get(request.form.get('user_id'))
            if u:
                if u.username != 'admin': u.role_id = request.form.get('role_id')
                if request.form.get('password', '').strip(): u.password_hash = bcrypt.generate_password_hash(request.form.get('password')).decode('utf-8')
                flash(_('User updated.'), 'success')
        elif action == 'delete':
            u = User.query.get(request.form.get('user_id'))
            if u and u.username != 'admin':
                db.session.delete(u)
                flash(_('User deleted.'), 'warning')
        db.session.commit()
        return redirect(url_for('manage_users'))
    return render_template('users.html', users=User.query.all(), roles=Role.query.all())

@app.route('/company', methods=['GET', 'POST'])
@login_required
@permission_required('manage_users_access')
def company_profile():
    profile = Company.query.first() or Company()
    if request.method == 'POST':
        if not profile.id: db.session.add(profile)
        profile.name, profile.phone, profile.address = request.form.get('name'), request.form.get('phone'), request.form.get('address')
        if request.files.get('logo') and request.files.get('logo').filename != '':
            filename = secure_filename(request.files.get('logo').filename)
            request.files.get('logo').save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            profile.logo_filename = filename
        db.session.commit()
        flash(_('Store Configuration Updated'), 'success')
        return redirect(url_for('company_profile'))
    return render_template('profile.html', profile=profile)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and bcrypt.check_password_hash(user.password_hash, request.form.get('password')):
            login_user(user)
            return redirect(url_for('dashboard'))
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/set_language/<language>')
def set_language(language):
    session['lang'] = language
    return redirect(request.referrer or url_for('dashboard'))

@app.template_filter('abs')
def abs_filter(value): return abs(value)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        # Ensure Admin Setup exists
        admin_role = Role.query.filter_by(name='System Admin').first()
        if not admin_role:
            admin_role = Role(name='System Admin', pos_access=True, inventory_access=True, supplier_access=True, report_access=True, manage_users_access=True)
            db.session.add(admin_role)
            db.session.commit()
            
        if not User.query.filter_by(username='admin').first():
            hashed_pw = bcrypt.generate_password_hash('admin123').decode('utf-8')
            db.session.add(User(username='admin', password_hash=hashed_pw, role_id=admin_role.id))
            
        if not Company.query.first():
            db.session.add(Company(name="My Boutique Setup", phone="Update in Settings", address="Update in Settings"))

        db.session.commit()
        app.run(host='0.0.0.0', port=5000, debug=True)
