from app import app, db, User, Role, Company, bcrypt

def initialize_clean_database():
    with app.app_context():
        print("Dropping all existing tables to start fresh...")
        db.drop_all()
        
        print("Creating empty tables for the entire system...")
        db.create_all()

        # ==========================================
        # 1. CREATE MASTER ROLE
        # ==========================================
        print("Setting up System Admin Role...")
        admin_role = Role(
            name='System Admin',
            pos_access=True,
            inventory_access=True,
            supplier_access=True,
            report_access=True,
            manage_users_access=True
        )
        db.session.add(admin_role)
        db.session.flush() # Flush to get the ID for the user creation

        # ==========================================
        # 2. CREATE DEFAULT ADMIN ACCOUNT
        # ==========================================
        print("Creating default admin account...")
        admin_pw = bcrypt.generate_password_hash('admin123').decode('utf-8')
        default_admin = User(
            username='admin', 
            password_hash=admin_pw, 
            role_id=admin_role.id
        )
        db.session.add(default_admin)
        
        # ==========================================
        # 3. CREATE BLANK COMPANY PROFILE
        # ==========================================
        print("Creating basic store profile...")
        db.session.add(Company(name="KZL Boutique", phone="Update in Settings", address="Update in Settings"))
        
        # Save everything to the database
        db.session.commit()
        
        print("\n✅ CLEAN DATABASE INITIALIZATION COMPLETE! ✅")
        print("=========================================")
        print("Your system is completely empty and ready for real data.")
        print("Login to the system using:")
        print("Username: admin")
        print("Password: admin123")
        print("=========================================")

if __name__ == '__main__':
    initialize_clean_database()
