from app import app, db, User, Company, Supplier, Product, Customer, Sale, SaleItem, PurchaseOrder, POItem, StockLog, bcrypt, get_mmt_time
from datetime import timedelta
from decimal import Decimal
import random

def run_seed():
    with app.app_context():
        print("Dropping all existing tables...")
        db.drop_all()
        
        print("Rebuilding tables...")
        db.create_all()

        # ==========================================
        # 1. ADMIN & COMPANY CONFIG
        # ==========================================
        print("Creating Admin & Company...")
        admin_pw = bcrypt.generate_password_hash('admin123').decode('utf-8')
        db.session.add(User(username='admin', password_hash=admin_pw, role='admin'))
        db.session.add(Company(name="KZL Premium Boutique", phone="09-123456789", address="Yangon, Myanmar"))
        
        # ==========================================
        # 2. SUPPLIERS
        # ==========================================
        print("Creating Suppliers...")
        suppliers = [
            Supplier(name="BKK Wholesale Hub", contact_person="Mr. Somchai", phone="+66 81 234 5678", balance=Decimal('0')),
            Supplier(name="Local Textile Mill", contact_person="U Aung", phone="09 876 543 210", balance=Decimal('150000')),
            Supplier(name="Seoul Fashion Imports", contact_person="Ms. Kim", phone="+82 10 1234 5678", balance=Decimal('0'))
        ]
        db.session.add_all(suppliers)
        db.session.flush() # Flush to get their IDs

        # ==========================================
        # 3. PRODUCTS (INVENTORY)
        # ==========================================
        print("Creating Products...")
        products = [
            Product(name="Premium Cotton T-Shirt", category="Tops", size="M", color="White", purchase_price=4000, selling_price=9000, stock=50, supplier_id=suppliers[0].id),
            Product(name="Premium Cotton T-Shirt", category="Tops", size="L", color="Black", purchase_price=4000, selling_price=9000, stock=30, supplier_id=suppliers[0].id),
            Product(name="Vintage Denim Jacket", category="Outerwear", size="Free Size", color="Blue", purchase_price=15000, selling_price=35000, stock=10, supplier_id=suppliers[1].id),
            Product(name="Summer Floral Dress", category="Dresses", size="S", color="Yellow", purchase_price=8000, selling_price=18500, stock=25, supplier_id=suppliers[2].id),
            Product(name="High-Waist Jeans", category="Bottoms", size="M", color="Dark Wash", purchase_price=12000, selling_price=25000, stock=5, supplier_id=suppliers[0].id),
        ]
        db.session.add_all(products)
        db.session.flush()

        # Add initial stock logs
        for p in products:
            db.session.add(StockLog(product_id=p.id, quantity=p.stock, action="Initial Setup", timestamp=get_mmt_time()))

        # ==========================================
        # 4. VIP CUSTOMERS
        # ==========================================
        print("Creating VIP Customers...")
        customers = [
            Customer(name="Daw Aye Aye", phone="09-222333444", balance=Decimal('45000')), # Owes money
            Customer(name="U Kyaw Kyaw", phone="09-555666777", balance=Decimal('-15000')), # Has store credit
            Customer(name="Ma Su Su", phone="09-888999000", balance=Decimal('0')) # Settled
        ]
        db.session.add_all(customers)
        db.session.flush()

        # ==========================================
        # 5. HISTORICAL SALES (For 7-Day Chart)
        # ==========================================
        print("Simulating past 7 days of sales...")
        today = get_mmt_time()
        
        for i in range(7):
            past_date = today - timedelta(days=6-i)
            # 1-3 random sales per day
            num_sales = random.randint(1, 3) 
            
            for _ in range(num_sales):
                selected_prod = random.choice(products)
                qty = random.randint(1, 3)
                total = selected_prod.selling_price * qty
                
                # Mostly paid, sometimes debt
                is_paid = random.choice([True, True, False])
                amount_paid = total if is_paid else (total - Decimal('5000'))
                
                sale = Sale(
                    total_amount=total,
                    amount_paid=amount_paid,
                    transaction_type='paid' if is_paid else 'credit',
                    payment_method=random.choice(['cash', 'kpay', 'wave']),
                    timestamp=past_date,
                    # Randomly assign a customer or leave as walk-in (None)
                    customer_id=random.choice([None, customers[0].id, customers[2].id])
                )
                db.session.add(sale)
                db.session.flush()

                sale_item = SaleItem(
                    sale_id=sale.id,
                    product_name=f"{selected_prod.name} ({selected_prod.size})",
                    quantity=qty,
                    price=selected_prod.selling_price,
                    purchase_cost=selected_prod.purchase_price
                )
                db.session.add(sale_item)

        # ==========================================
        # 6. PURCHASE ORDERS
        # ==========================================
        print("Creating Purchase Orders...")
        # 1 Pending PO
        po1 = PurchaseOrder(supplier_id=suppliers[0].id, status='Pending', total_amount=40000, timestamp=today - timedelta(days=1))
        db.session.add(po1)
        db.session.flush()
        db.session.add(POItem(po_id=po1.id, product_id=products[0].id, quantity=10, unit_cost=4000))

        # 1 Received PO
        po2 = PurchaseOrder(supplier_id=suppliers[1].id, status='Received', total_amount=150000, timestamp=today - timedelta(days=3))
        db.session.add(po2)
        db.session.flush()
        db.session.add(POItem(po_id=po2.id, product_id=products[2].id, quantity=10, unit_cost=15000))

        db.session.commit()
        print("\n✅ SEEDING COMPLETE! ✅")
        print("Database is populated with test data.")
        print("Login with: admin / admin123")

if __name__ == '__main__':
    run_seed()
