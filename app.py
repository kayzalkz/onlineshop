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

class Product(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150))
    category = db.Column(db.String(50))
    size = db.Column(db.String(20))
    color = db.Column(db.String(50)) 
    purchase_price = db.Column(db.Numeric(10, 2))
    selling_price = db.Column(db.Numeric(10, 2))
    stock = db.Column(db.Integer, default=0)

class Sale(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    total_amount = db.Column(db.Numeric(10, 2))
    amount_paid = db.Column(db.Numeric(10, 2))
    timestamp = db.Column(db.DateTime, default=get_mmt_time) # MMT FIX
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
    timestamp = db.Column(db.DateTime, default=get_mmt_time) # MMT FIX
    product = db.relationship('Product', backref='stock_logs')

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.context_processor
def inject_company():
    return dict(company=Company.query.first())

# ==========================================
# DASHBOARD & POS ROUTES
# ==========================================

@app.route('/')
@login_required
def dashboard():
    today = get_mmt_time().date() # MMT FIX
    total_sales = db.session.query(func.sum(Sale.total_amount)).filter(func.date(Sale.timestamp) == today).scalar() or 0
    total_stock = db.session.query(func.sum(Product.stock)).scalar() or 0
    active_credit = db.session.query(func.sum(Customer.balance)).filter(Customer.balance > 0).scalar() or 0
    
    chart_data = []
    for i in range(6, -1, -1):
        day = (today - timedelta(days=i))
        val = db.session.query(func.sum(Sale.total_amount)).filter(func.date(Sale.timestamp) == day).scalar() or 0
        chart_data.append(float(val))

    return render_template('dashboard.html', total_sales=total_sales, total_stock=total_stock, active_credit=active_credit, chart_data=chart_data)

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
            timestamp=get_mmt_time() # MMT FIX
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
# INVENTORY ROUTE
# ==========================================

@app.route('/inventory', methods=['GET', 'POST'])
@login_required
def inventory():
    if request.method == 'POST':
        action = request.form.get('action')
        if action == 'add_product':
            stock_qty = int(request.form.get('stock', '0'))
            p = Product(
                name=request.form.get('name'),
                category=request.form.get('category'),
                size=request.form.get('size'),
                color=request.form.get('color'),
                purchase_price=Decimal(request.form.get('purchase_price', '0')),
                selling_price=Decimal(request.form.get('selling_price', '0')),
                stock=stock_qty
            )
            db.session.add(p)
            db.session.flush()
            if stock_qty != 0:
                db.session.add(StockLog(product_id=p.id, quantity=stock_qty, action="Initial Setup", timestamp=get_mmt_time()))
            flash(_('Product added.'), 'success')
        elif action == 'edit_product':
            p = Product.query.get(request.form.get('product_id'))
            if p:
                p.name = request.form.get('name')
                p.category = request.form.get('category')
                p.size = request.form.get('size')
                p.color = request.form.get('color')
                p.purchase_price = Decimal(request.form.get('purchase_price', '0'))
                p.selling_price = Decimal(request.form.get('selling_price', '0'))
                flash(_('Product updated.'), 'success')
        elif action == 'delete_product':
            p = Product.query.get(request.form.get('product_id'))
            if p:
                StockLog.query.filter_by(product_id=p.id).delete() 
                db.session.delete(p)
                flash(_('Product deleted.'), 'warning')
        elif action == 'adjust_stock':
            p = Product.query.get(request.form.get('product_id'))
            qty_change = int(request.form.get('qty_change', '0'))
            reason = request.form.get('reason', 'Manual Adjustment')
            if p and qty_change != 0:
                p.stock += qty_change
                db.session.add(StockLog(product_id=p.id, quantity=qty_change, action=reason, timestamp=get_mmt_time()))
                flash(_('Stock adjusted.'), 'success')
        db.session.commit()
        return redirect(url_for('inventory'))
    return render_template('inventory.html', products=Product.query.all())

# ==========================================
# REPORTS ROUTE
# ==========================================

@app.route('/reports')
@login_required
def reports():
    today = get_mmt_time().date() # MMT FIX
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
    
    chart_data = []
    for i in range(6, -1, -1):
        day = (today - timedelta(days=i))
        val = db.session.query(func.sum(Sale.total_amount)).filter(func.date(Sale.timestamp) == day).scalar() or 0
        chart_data.append(float(val))

    return render_template('reports.html', 
                           daily_rev=daily_rev, cash_total=cash_total, digital_total=digital_total, credit_total=credit_total,
                           all_sales=all_sales, products=products, stock_logs=stock_logs,
                           total_revenue=total_revenue, total_cost=total_cost, net_profit=net_profit, chart_data=chart_data)

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

@app.route('/customer/repay/<int:customer_id>', methods=['POST'])
@login_required
def customer_repay(customer_id):
    customer = Customer.query.get_or_404(customer_id)
    
    # Get values from the form
    action = request.form.get('action')
    # Convert float/string input to Decimal immediately
    amount = Decimal(request.form.get('amount', '0'))
    payment_method = request.form.get('payment_method', 'cash')
    payment_info = request.form.get('payment_info', '')

    if amount > 0:
        # Determine if we are reducing debt or adding prepaid credit
        if action == 'pay_debt':
            customer.balance -= amount
        elif action == 'add_credit':
            # Adding credit is mathematically the same as subtracting from a debt balance
            customer.balance -= amount
        
        # Record the transaction as a Sale with 0 total but a positive amount_paid
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
        
        # --- NEW LOGO UPLOAD LOGIC ---
        logo_file = request.files.get('logo')
        if logo_file and logo_file.filename != '':
            # Secure the filename to prevent malicious uploads
            filename = secure_filename(logo_file.filename)
            # Save it to the static/uploads folder
            logo_file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
            # Update the database
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
            # Protect the primary admin account from being accidentally downgraded
            if u and u.username != 'admin': 
                u.role = request.form.get('role')
                new_pw = request.form.get('password')
                # Only change the password if the admin typed a new one
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
        # 1. Build the empty tables
        db.create_all()
        
        # 2. Automatically create a default Admin user if none exists
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
            
        # 3. Automatically create a blank Company Profile if none exists
        company_profile = Company.query.first()
        if not company_profile:
            new_company = Company(name="My Boutique Setup", phone="Update in Settings", address="Update in Settings")
            db.session.add(new_company)
            print("Blank Company Profile created.")

        db.session.commit()
        
        app.run(host='0.0.0.0', port=5000,  debug=True)
