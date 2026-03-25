import os
import io
from datetime import datetime, timedelta
from decimal import Decimal
from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_login import LoginManager, UserMixin, login_required, current_user, login_user, logout_user
from flask_babel import Babel, _
from sqlalchemy import func
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.config['SECRET_KEY'] = 'kzl_boutique_secure_2026'
app.config['SQLALCHEMY_DATABASE_URI'] = 'mysql+pymysql://root:japu@localhost/pos_system'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

UPLOAD_FOLDER = 'static/uploads'
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

babel = Babel(app, locale_selector=lambda: session.get('lang', 'en'))

db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# ==========================================
# TIMEZONE HELPER (MYANMAR TIME: UTC +6:30)
# ==========================================
def get_mmt_time():
    return datetime.utcnow() + timedelta(hours=6, minutes=30)

# ==========================================
# DATABASE MODELS
# ==========================================

class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), default="KZL Clothing")
    address = db.Column(db.Text)
    phone = db.Column(db.String(50))
    logo_filename = db.Column(db.String(150))

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True)
    password_hash = db.Column(db.String(128))
    role = db.Column(db.String(20), default='cashier')

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


# ---> ဒီ Table အသစ်ကို အောက်မှာ ထပ်တိုးပါ <---
class SupplierPayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    supplier_id = db.Column(db.Integer, db.ForeignKey('supplier.id'), nullable=False)
    amount = db.Column(db.Numeric(10, 2), nullable=False)
    payment_method = db.Column(db.String(50)) # cash, kpay, wave
    reference_note = db.Column(db.String(150)) # e.g., "KBZ Pay Transfer"
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
    status = db.Column(db.String(20), default='Pending') # 'Pending', 'Received', 'Cancelled'
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
    
    items = db.relationship('SaleItem', backref='sale', lazy=True)
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
    
    top_items = db.session.query(
        SaleItem.product_name, 
        func.sum(SaleItem.quantity).label('total_sold')
    ).group_by(SaleItem.product_name).order_by(func.sum(SaleItem.quantity).desc()).limit(5).all()

    top_customers = db.session.query(
        Customer.name,
        func.sum(Sale.total_amount).label('total_spent')
    ).join(Sale).group_by(Customer.id).order_by(func.sum(Sale.total_amount).desc()).limit(5).all()

    top_suppliers = db.session.query(
        Supplier.name,
        func.sum(PurchaseOrder.total_amount).label('total_ordered')
    ).join(PurchaseOrder).group_by(Supplier.id).order_by(func.sum(PurchaseOrder.total_amount).desc()).limit(5).all()
    
    chart_data = []
    for i in range(6, -1, -1):
        day = (today - timedelta(days=i))
        val = db.session.query(func.sum(Sale.total_amount)).filter(func.date(Sale.timestamp) == day).scalar() or 0
        chart_data.append(float(val))

    return render_template('dashboard.html', 
                           total_sales=total_sales, 
                           total_stock=total_stock, 
                           active_credit=active_credit, 
                           supplier_debt=supplier_debt,
                           top_items=top_items,
                           top_customers=top_customers,
                           top_suppliers=top_suppliers,
                           chart_data=chart_data)



# ==========================================
# REPORTS ROUTE
# ==========================================
@app.route('/reports')
@login_required
def reports():
    today = get_mmt_time().date() 
    
    daily_rev = db.session.query(func.sum(Sale.total_amount)).filter(func.date(Sale.timestamp) == today).scalar() or 0
    cash_total = db.session.query(func.sum(Sale.amount_paid)).filter(func.date(Sale.timestamp) == today, Sale.payment_method == 'cash').scalar() or 0
    digital_total = db.session.query(func.sum(Sale.amount_paid)).filter(func.date(Sale.timestamp) == today, Sale.payment_method != 'cash').scalar() or 0
    credit_total = db.session.query(func.sum(Customer.balance)).filter(Customer.balance > 0).scalar() or 0
    
    total_revenue = db.session.query(func.sum(SaleItem.quantity * SaleItem.price)).scalar() or Decimal('0')
    total_cost = db.session.query(func.sum(SaleItem.quantity * SaleItem.purchase_cost)).scalar() or Decimal('0')
    net_profit = total_revenue - total_cost

    all_sales = Sale.query.order_by(Sale.timestamp.desc()).all()
    products = Product.query.all()
    stock_logs = StockLog.query.order_by(StockLog.timestamp.desc()).limit(200).all()
    customers = Customer.query.all() 
    suppliers = Supplier.query.all()
    
    chart_data = []
    for i in range(6, -1, -1):
        day = (today - timedelta(days=i))
        val = db.session.query(func.sum(Sale.total_amount)).filter(func.date(Sale.timestamp) == day).scalar() or 0
        chart_data.append(float(val))

    return render_template('reports.html', 
                           daily_rev=daily_rev, cash_total=cash_total, digital_total=digital_total, credit_total=credit_total,
                           all_sales=all_sales, products=products, stock_logs=stock_logs,
                           customers=customers, suppliers=suppliers,
                           total_revenue=total_revenue, total_cost=total_cost, net_profit=net_profit, chart_data=chart_data)


@app.route('/pos')
@login_required
def pos():
    customers = Customer.query.all()
    products = Product.query.filter(Product.stock > 0).all()
    recent_sales = Sale.query.order_by(Sale.timestamp.desc()).limit(15).all()
    
    last_sale_id = session.pop('last_sale_id', None)
    last_sale = Sale.query.get(last_sale_id) if last_sale_id else None
    
    return render_template('pos.html', customers=customers, products=products, last_sale=last_sale, recent_sales=recent_sales)

@app.route('/process_sale', methods=['POST'])
@login_required
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

    # ✅ BUG FIX: Prevent walk-in customers from adding overpayments to the Cash Drawer
    if not cust_id and amount_paid > total_amount:
        amount_paid = total_amount

    t_type = 'paid' if amount_paid >= total_amount else 'credit'

    editing_sale_id = session.pop('editing_sale_id', None)
    
    if editing_sale_id:
        sale = Sale.query.get(editing_sale_id)
        if sale:
            if sale.customer_id:
                old_cust = Customer.query.get(sale.customer_id)
                if old_cust:
                    old_cust.balance -= (sale.total_amount - sale.amount_paid)
            
            products = Product.query.all()
            for old_item in sale.items:
                matched = next((p for p in products if p.name in old_item.product_name), None)
                if matched:
                    matched.stock += old_item.quantity
            
            SaleItem.query.filter_by(sale_id=sale.id).delete()
            
            sale.total_amount = total_amount
            sale.amount_paid = amount_paid
            sale.transaction_type = t_type
            sale.payment_method = p_method
            sale.payment_info = p_info
            sale.customer_id = cust_id if cust_id else None
    else:
        sale = Sale(
            total_amount=total_amount, amount_paid=amount_paid, transaction_type=t_type,
            payment_method=p_method, payment_info=p_info, customer_id=cust_id if cust_id else None,
            timestamp=get_mmt_time()
        )
        db.session.add(sale)
        db.session.flush()

    for item_str in cart_data.split(','):
        if item_str:
            p_id, qty = item_str.split(':')
            qty = int(qty)
            product = Product.query.get(int(p_id))
            
            if product:
                prod_desc = f"{product.name} ({product.size} - {product.color})" if product.color else f"{product.name} ({product.size})"
                sale_item = SaleItem(
                    sale_id=sale.id, product_name=prod_desc, quantity=qty,
                    price=product.selling_price, purchase_cost=product.purchase_price
                )
                db.session.add(sale_item)
                product.stock -= qty

    if cust_id:
        customer = Customer.query.get(cust_id)
        customer.balance += (total_amount - amount_paid)

    db.session.commit()
    session.pop('edit_cart', None)
    session.pop('edit_customer', None)
    session.pop('edit_paid', None)
    
    session['last_sale_id'] = sale.id
    flash(_('Transaction processed successfully!'), 'success')
    return redirect(url_for('pos'))

@app.route('/edit_sale/<int:sale_id>', methods=['POST'])
@login_required
def edit_sale(sale_id):
    if current_user.role != 'admin':
        return redirect(url_for('pos'))
    sale = Sale.query.get_or_404(sale_id)
    cart_data = {}
    products = Product.query.all()
    for item in sale.items:
        matched_product = next((p for p in products if p.name in item.product_name), None)
        if matched_product:
            cart_data[str(matched_product.id)] = {
                'name': matched_product.name, 'price': float(matched_product.selling_price), 'qty': item.quantity
            }
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
    flash(_('Edit cancelled. The original sale remains unchanged.'), 'warning')
    return redirect(url_for('pos'))

@app.route('/delete_sale/<int:sale_id>', methods=['POST'])
@login_required
def delete_sale(sale_id):
    if current_user.role != 'admin': return redirect(url_for('reports'))
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
    flash(_('Sale permanently voided and stock restored.'), 'warning')
    return redirect(request.referrer or url_for('reports'))

@app.route('/receipt/<int:sale_id>')
@login_required
def receipt(sale_id):
    sale = Sale.query.get_or_404(sale_id)
    return render_template('receipt.html', sale=sale)


# ==========================================
# PURCHASE ORDER (PO) ROUTES
# ==========================================

@app.route('/purchase_orders')
@login_required
def purchase_orders():
    pos = PurchaseOrder.query.order_by(PurchaseOrder.timestamp.desc()).all()
    suppliers = Supplier.query.all()
    products = Product.query.all()
    return render_template('purchase_orders.html', pos=pos, suppliers=suppliers, products=products)

@app.route('/po/create', methods=['POST'])
@login_required
def create_po():
    supplier_id = request.form.get('supplier_id')
    product_ids = request.form.getlist('product_id[]')
    quantities = request.form.getlist('quantity[]')
    costs = request.form.getlist('unit_cost[]')

    if not supplier_id or not product_ids:
        flash(_('Invalid Purchase Order data.'), 'danger')
        return redirect(url_for('purchase_orders'))

    po = PurchaseOrder(supplier_id=supplier_id, status='Pending', total_amount=0)
    db.session.add(po)
    db.session.flush() 

    total_amount = Decimal('0')

    for i in range(len(product_ids)):
        if product_ids[i] and int(quantities[i]) > 0:
            qty = int(quantities[i])
            cost = Decimal(costs[i])
            
            po_item = POItem(po_id=po.id, product_id=product_ids[i], quantity=qty, unit_cost=cost)
            db.session.add(po_item)
            total_amount += (cost * qty)

    po.total_amount = total_amount
    db.session.commit()
    flash(_('Purchase Order #{} created successfully.').format(po.id), 'success')
    return redirect(url_for('purchase_orders'))

@app.route('/po/receive/<int:po_id>', methods=['POST'])
@login_required
def receive_po(po_id):
    po = PurchaseOrder.query.get_or_404(po_id)
    
    if po.status == 'Pending':
        po.status = 'Received'
        po.supplier.balance += po.total_amount 
        
        for item in po.items:
            item.product.stock += item.quantity
            db.session.add(StockLog(
                product_id=item.product.id, 
                quantity=item.quantity, 
                action=f"Received via PO #{po.id}", 
                timestamp=get_mmt_time()
            ))
            
        db.session.commit()
        flash(_('Goods received! Inventory stock and supplier balances have been updated.'), 'success')
        
    return redirect(url_for('purchase_orders'))

@app.route('/po/cancel/<int:po_id>', methods=['POST'])
@login_required
def cancel_po(po_id):
    po = PurchaseOrder.query.get_or_404(po_id)
    if po.status == 'Pending':
        po.status = 'Cancelled'
        db.session.commit()
        flash(_('Purchase Order #{} cancelled.').format(po.id), 'warning')
    return redirect(url_for('purchase_orders'))

# ==========================================
# INVENTORY ROUTE
# ==========================================

@app.route('/inventory', methods=['GET', 'POST'])
@login_required
def inventory():
    if request.method == 'POST':
        action = request.form.get('action')
        
        # Extract supplier ID properly
        supplier_id = request.form.get('supplier_id')
        if supplier_id == "":
            supplier_id = None
        
        if action == 'add_product':
            name = request.form.get('name', '').strip()
            size = request.form.get('size', '').strip()
            color = request.form.get('color', '').strip()
            
            existing_product = Product.query.filter_by(name=name, size=size, color=color).first()
            
            if existing_product:
                flash(_(f'Error: "{name}" ({size}/{color}) already exists. Please edit the existing item or adjust its stock instead.'), 'danger')
            else:
                try:
                    purchase_price = Decimal(request.form.get('purchase_price', '0'))
                    selling_price = Decimal(request.form.get('selling_price', '0'))
                    stock_qty = int(request.form.get('stock', '0'))
                    
                    # ✅ BUG FIX: Save the supplier_id when creating a new product
                    p = Product(
                        name=name,
                        category=request.form.get('category'),
                        size=size,
                        color=color,
                        purchase_price=purchase_price,
                        selling_price=selling_price,
                        stock=stock_qty,
                        supplier_id=supplier_id
                    )
                    db.session.add(p)
                    db.session.flush()
                    
                    if stock_qty != 0:
                        db.session.add(StockLog(product_id=p.id, quantity=stock_qty, action="Initial Setup", timestamp=get_mmt_time()))
                        
                    flash(_('Product added successfully.'), 'success')
                except ValueError:
                    flash(_('Error: Invalid numbers entered for price or stock.'), 'danger')
                    
        elif action == 'edit_product':
            p = Product.query.get(request.form.get('product_id'))
            if p:
                try:
                    p.name = request.form.get('name', '').strip()
                    p.category = request.form.get('category', '').strip()
                    p.size = request.form.get('size', '').strip()
                    p.color = request.form.get('color', '').strip()
                    p.purchase_price = Decimal(request.form.get('purchase_price', '0'))
                    p.selling_price = Decimal(request.form.get('selling_price', '0'))
                    
                    # ✅ BUG FIX: Update the supplier_id when editing
                    p.supplier_id = supplier_id
                    
                    flash(_('Product updated successfully.'), 'success')
                except ValueError:
                    flash(_('Error: Invalid numbers entered for price.'), 'danger')

        elif action == 'delete_product':
            p = Product.query.get(request.form.get('product_id'))
            if p:
                StockLog.query.filter_by(product_id=p.id).delete() 
                db.session.delete(p)
                flash(_('Product permanently deleted.'), 'warning')
                
        elif action == 'adjust_stock':
            p = Product.query.get(request.form.get('product_id'))
            try:
                qty_change = int(request.form.get('qty_change', '0'))
                reason = request.form.get('reason', 'Manual Adjustment').strip()
                
                if p and qty_change != 0:
                    p.stock += qty_change
                    db.session.add(StockLog(product_id=p.id, quantity=qty_change, action=reason, timestamp=get_mmt_time()))
                    flash(_('Stock adjusted successfully.'), 'success')
            except ValueError:
                flash(_('Error: Please enter a valid whole number for stock adjustments.'), 'danger')
                
        db.session.commit()
        return redirect(url_for('inventory'))
        
    return render_template('inventory.html', 
                           products=Product.query.all(), 
                           suppliers=Supplier.query.all())

# ==========================================
# SUPPLIER MANAGEMENT ROUTES
# ==========================================

@app.route('/suppliers', methods=['GET', 'POST'])
@login_required
def suppliers():
    if request.method == 'POST':
        action = request.form.get('action', 'add')
        
        if action == 'add':
            s = Supplier(
                name=request.form.get('name'),
                contact_person=request.form.get('contact_person'),
                phone=request.form.get('phone'),
                address=request.form.get('address'),
                balance=Decimal(request.form.get('balance', '0'))
            )
            db.session.add(s)
            flash(_('Supplier registered successfully.'), 'success')
            
        elif action == 'edit':
            s = Supplier.query.get(request.form.get('supplier_id'))
            if s:
                s.name = request.form.get('name')
                s.contact_person = request.form.get('contact_person')
                s.phone = request.form.get('phone')
                s.address = request.form.get('address')
                flash(_('Supplier details updated.'), 'success')
                
        elif action == 'delete':
            s = Supplier.query.get(request.form.get('supplier_id'))
            if s:
                for p in s.products:
                    p.supplier_id = None
                db.session.delete(s)
                flash(_('Supplier removed from system.'), 'warning')
                
        db.session.commit()
        return redirect(url_for('suppliers'))

    return render_template('suppliers.html', suppliers=Supplier.query.all())

@app.route('/supplier/pay/<int:supplier_id>', methods=['POST'])
@login_required
def supplier_pay(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    
    try:
        amount = Decimal(request.form.get('amount', '0'))
    except:
        amount = Decimal('0')

    payment_method = request.form.get('payment_method', 'cash')
    reference_note = request.form.get('reference_note', '')

    if amount > 0:
        # ၁။ Supplier ရဲ့ Balance ထဲကနေ နှုတ်မည်
        supplier.balance -= amount
        
        # ၂။ Payment မှတ်တမ်းအသစ်ကို Voucher သဘောမျိုး သိမ်းမည်
        payment = SupplierPayment(
            supplier_id=supplier.id,
            amount=amount,
            payment_method=payment_method,
            reference_note=reference_note,
            timestamp=get_mmt_time()
        )
        db.session.add(payment)
        db.session.commit()
        flash(f'Payment of {amount:,.0f} MMK recorded for {supplier.name}.', 'success')
    else:
        flash('Invalid payment amount.', 'danger')

    return redirect(url_for('suppliers'))

@app.route('/supplier/<int:supplier_id>')
@login_required
def supplier_detail(supplier_id):
    supplier = Supplier.query.get_or_404(supplier_id)
    
    # ၁။ Supplier ဆီက မှာယူခဲ့သမျှ PO များ
    pos = PurchaseOrder.query.filter_by(supplier_id=supplier_id, status='Received').all()
    # ၂။ Supplier ကို ငွေပြန်ဆပ်ခဲ့သမျှ မှတ်တမ်းများ
    payments = SupplierPayment.query.filter_by(supplier_id=supplier_id).all()
    
    # ၃။ PO နှင့် Payment များကို တစ်ခုတည်းဖြစ်အောင် ပေါင်းပြီး ရက်စွဲအလိုက် စီမည်
    combined = []
    for po in pos:
        combined.append({
            'date': po.timestamp,
            'ref': f"PO#{po.id}",
            'desc': f"Stock In: {sum(i.quantity for i in po.items)} items",
            'debit': po.total_amount, # ဆိုင်က ပေးရန်တိုးလာခြင်း
            'credit': Decimal('0')
        })
        
    for p in payments:
        combined.append({
            'date': p.timestamp,
            'ref': f"PAY#{p.id}",
            'desc': f"Payment ({p.payment_method.upper()}) - {p.reference_note}",
            'debit': Decimal('0'),
            'credit': p.amount # ဆိုင်က ပြန်ဆပ်လိုက်ခြင်း
        })
        
    # ရက်စွဲအလိုက် အဟောင်းမှ အသစ်သို့ စီစဉ်မည်
    combined.sort(key=lambda x: x['date'])
    
    statement_data = []
    current_running_bal = Decimal('0')
    total_ordered = Decimal('0')
    
    for item in combined:
        current_running_bal += item['debit']
        current_running_bal -= item['credit']
        total_ordered += item['debit']
        
        statement_data.append({
            'date': item['date'],
            'ref': item['ref'],
            'desc': item['desc'],
            'debit': item['debit'],
            'credit': item['credit'],
            'running_bal': current_running_bal
        })
        
    statement_data.reverse() # အသစ်ဆုံးကို အပေါ်မှာပြရန်
    
    return render_template('supplier_detail.html', 
                           supplier=supplier, 
                           history=statement_data, 
                           total_ordered=total_ordered,
                           now=get_mmt_time())

# ==========================================
# MANAGEMENT ROUTES
# ==========================================

@app.route('/customers', methods=['GET', 'POST'])
@login_required
def customers():
    if request.method == 'POST':
        c = Customer(name=request.form.get('name'), phone=request.form.get('phone'))
        db.session.add(c)
        db.session.commit()
    return render_template('customers.html', customers=Customer.query.all())

@app.route('/customer/<int:customer_id>')
@login_required
def customer_detail(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    
    # Fetch history oldest to newest to calculate running balance correctly
    all_history = Sale.query.filter_by(customer_id=customer_id).order_by(Sale.timestamp.asc()).all()
    
    statement_data = []
    current_running_bal = Decimal('0')
    total_spent = Decimal('0')
    
    for sale in all_history:
        # Debt increases by (Total - Paid). 
        change = sale.total_amount - sale.amount_paid
        current_running_bal += change
        
        if sale.total_amount > 0:
            total_spent += sale.total_amount
            
        statement_data.append({
            'date': sale.timestamp,
            'ref': f"INV#{sale.id}" if sale.total_amount > 0 else "PAYMENT",
            'desc': ", ".join([i.product_name for i in sale.items]) if sale.items else (sale.payment_info or "Debt Repayment"),
            'debit': sale.total_amount,
            'credit': sale.amount_paid,
            'running_bal': current_running_bal
        })
    
    # Reverse so the newest transaction is at the top
    statement_data.reverse()
    
    return render_template('customer_detail.html', 
                           customer=customer, 
                           history=statement_data, 
                           total_spent=total_spent,
                           now=get_mmt_time()) # ✅ Added this line

@app.route('/customer/repay/<int:customer_id>', methods=['POST'])
@login_required
def customer_repay(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    action = request.form.get('action')
    amount = Decimal(request.form.get('amount', '0'))
    payment_method = request.form.get('payment_method', 'cash')
    payment_info = request.form.get('payment_info', '')

    if amount > 0:
        if action == 'pay_debt':
            customer.balance -= amount
        elif action == 'add_credit':
            customer.balance -= amount
        
        new_repayment = Sale(
            customer_id=customer.id,
            total_amount=0,
            amount_paid=amount,
            payment_method=payment_method,
            payment_info=f"Repayment/Credit: {payment_info}",
            timestamp=get_mmt_time()
        )
        
        db.session.add(new_repayment)
        db.session.commit()
        flash(f'Successfully processed {amount:,.0f} MMK for {customer.name}', 'success')
    else:
        flash('Invalid amount.', 'danger')

    return redirect(url_for('customers'))

@app.route('/company', methods=['GET', 'POST'])
@login_required
def company_profile():
    if current_user.role != 'admin': return redirect(url_for('dashboard'))
    
    profile = Company.query.first()
    
    if request.method == 'POST':
        if profile is None:
            profile = Company()
            db.session.add(profile)
            
        profile.name = request.form.get('name')
        profile.phone = request.form.get('phone')
        profile.address = request.form.get('address')
        
        logo_file = request.files.get('logo')
        if logo_file and logo_file.filename != '':
            filename = secure_filename(logo_file.filename)
            logo_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            profile.logo_filename = filename
            
        db.session.commit()
        flash(_('Store Configuration Updated'), 'success')
        return redirect(url_for('company_profile'))
        
    return render_template('profile.html', profile=profile)

@app.route('/users', methods=['GET', 'POST'])
@login_required
def manage_users():
    if current_user.role != 'admin': 
        return redirect(url_for('dashboard'))
        
    if request.method == 'POST':
        action = request.form.get('action', 'create')

        if action == 'create':
            hashed_pw = bcrypt.generate_password_hash(request.form.get('password')).decode('utf-8')
            u = User(username=request.form.get('username'), password_hash=hashed_pw, role=request.form.get('role'))
            db.session.add(u)
            flash(_('Staff account created.'), 'success')
            
        elif action == 'edit':
            user_id = request.form.get('user_id')
            u = User.query.get(user_id)
            if u and u.username != 'admin': 
                u.role = request.form.get('role')
                new_pw = request.form.get('password')
                if new_pw and new_pw.strip() != "": 
                    u.password_hash = bcrypt.generate_password_hash(new_pw).decode('utf-8')
                flash(_('User account updated successfully.'), 'success')
                
        elif action == 'delete':
            user_id = request.form.get('user_id')
            u = User.query.get(user_id)
            if u and u.username != 'admin':
                db.session.delete(u)
                flash(_('User account permanently deleted.'), 'warning')

        db.session.commit()
        return redirect(url_for('manage_users'))
        
    return render_template('users.html', users=User.query.all())

# ==========================================
# EXPORTS & AUTH
# ==========================================

@app.route('/export/excel')
@login_required
def export_excel():
    sales = Sale.query.order_by(Sale.timestamp.desc()).all()
    data = []
    
    for s in sales:
        items_list = ", ".join([f"{i.product_name} (x{i.quantity})" for i in s.items])
        cogs = sum(i.purchase_cost * i.quantity for i in s.items)
        profit = s.total_amount - cogs
        
        data.append({
            'Invoice Ref': f"#{s.id}",
            'Date & Time': s.timestamp.strftime('%Y-%m-%d %H:%M'),
            'Customer Name': s.customer.name if s.customer else 'Walk-in',
            'Customer Phone': s.customer.phone if s.customer else '',
            'Items Purchased': items_list,
            'Total Invoice Amount (MMK)': float(s.total_amount),
            'Amount Paid (MMK)': float(s.amount_paid),
            'Balance Due (MMK)': float(s.total_amount - s.amount_paid),
            'Payment Method': s.payment_method.upper(),
            'Status': 'Fully Paid' if s.amount_paid >= s.total_amount else 'Debt/Credit',
            'Cost of Goods (MMK)': float(cogs),
            'Net Profit (MMK)': float(profit)
        })
    
    df = pd.DataFrame(data)
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Master Sales Ledger')
    
    output.seek(0)
    return send_file(output, download_name=f"Standard_Sales_Report_{get_mmt_time().strftime('%Y-%m-%d')}.xlsx", as_attachment=True)


@app.route('/export/customers_excel')
@login_required
def export_customers_excel():
    customers = Customer.query.all()
    data = []
    
    for c in customers:
        if c.balance > 0:
            status = "Owes Store (Debt)"
        elif c.balance < 0:
            status = "Store Credit"
        else:
            status = "Settled"
            
        last_activity = "No History"
        if c.sales:
            last_sale = sorted(c.sales, key=lambda x: x.timestamp, reverse=True)[0]
            last_activity = last_sale.timestamp.strftime('%Y-%m-%d %H:%M:%S')

        data.append({
            'Client ID': f"#{c.id}",
            'Client Name': c.name,
            'Phone Number': c.phone,
            'Current Balance (MMK)': float(abs(c.balance)),
            'Financial Status': status,
            'Last Transaction / Settlement Date': last_activity
        })
    
    df = pd.DataFrame(data)
    output = io.BytesIO()
    
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Client_Ledger_Report')
        worksheet = writer.sheets['Client_Ledger_Report']
        
        for col in worksheet.columns:
            max_length = 0
            column = col[0].column_letter 
            for cell in col:
                try:
                    if len(str(cell.value)) > max_length:
                        max_length = len(str(cell.value))
                except:
                    pass
            adjusted_width = (max_length + 2)
            worksheet.column_dimensions[column].width = adjusted_width

    output.seek(0)
    filename = f"Client_Financial_Report_{get_mmt_time().strftime('%Y-%m-%d')}.xlsx"
    return send_file(output, download_name=filename, as_attachment=True)

@app.route('/export/pdf')
@login_required
def export_pdf():
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    p.drawString(100, 750, f"Official Sales Report - {get_mmt_time().strftime('%Y-%m-%d')}")
    y = 700
    p.drawString(100, y, "ID | Date | Total Due | Paid | Payment Method")
    y -= 20
    for sale in Sale.query.order_by(Sale.timestamp.desc()).limit(40).all():
        p.drawString(100, y, f"#{sale.id} | {sale.timestamp.strftime('%Y-%m-%d')} | {sale.total_amount} MMK | {sale.amount_paid} MMK | {sale.payment_method.upper()}")
        y -= 20
        if y < 50:
            p.showPage()
            y = 750
    p.save()
    buffer.seek(0)
    return send_file(buffer, download_name="Sales_Report.pdf", as_attachment=True)

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
def abs_filter(value):
    return abs(value)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        
        admin_user = User.query.filter_by(username='admin').first()
        if not admin_user:
            hashed_pw = bcrypt.generate_password_hash('admin123').decode('utf-8')
            new_admin = User(username='admin', password_hash=hashed_pw, role='admin')
            db.session.add(new_admin)
            print("=========================================")
            print("🚨 DEFAULT ADMIN CREATED 🚨")
            print("Username: admin")
            print("Password: admin123")
            print("Please login and change this immediately!")
            print("=========================================")
            
        company_profile = Company.query.first()
        if not company_profile:
            new_company = Company(name="My Boutique Setup", phone="Update in Settings", address="Update in Settings")
            db.session.add(new_company)
            print("Blank Company Profile created.")

        db.session.commit()
        
        app.run(host='0.0.0.0', port=5000,  debug=True)
