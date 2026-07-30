import os
import sys

# Add parent directory to sys.path so we can import app layers dynamically
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import mysql.connector
from sqlalchemy import text

from app.core.config import settings
from app.core.database import Base, engine, SessionLocal
from app.models.models import Role, User, Admin, Building, Floorplan, Node, Edge, Department, Faculty, Programme, Staff, UserRole
from app.core.security import get_password_hash, validate_strong_password

def create_database():
    print(f"Connecting to MySQL server at {settings.DB_HOST}:{settings.DB_PORT}...")
    try:
        # Establish raw gateway link to check schema state before engine binding
        conn = mysql.connector.connect(
            host=settings.DB_HOST,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            port=settings.DB_PORT
        )
        cursor = conn.cursor()
        cursor.execute(f"CREATE DATABASE IF NOT EXISTS {settings.DB_NAME}")
        print(f"Database '{settings.DB_NAME}' verified/created successfully.")
        cursor.close()
        conn.close()
    except Exception as e:
        print(f"Error checking/creating database: {e}")
        print("Proceeding with default SQLAlchemy relational initialization...")

def seed_data():
    db = SessionLocal()
    try:
        db.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
        # =========================================================================
        # STAGE 1: SEED SECURITY ROLES (Foundational Reference Tier)
        # =========================================================================
        roles_data = [
            {"role_name": "ADMIN", "description": "System administrators with backend dashboard access control permissions"},
            {"role_name": "STAFF", "description": "Administrative, technical, security, and facility operational personnel"},
            {"role_name": "LECTURER", "description": "Academic faculty responsible for conducting courses and managing timetables"},
            {"role_name": "STUDENT", "description": "University Student"},
            {"role_name": "VISITOR", "description": "Guest/Visitor"}
        ]
        
        roles_map = {}
        for r in roles_data:
            role = db.query(Role).filter_by(role_name=r["role_name"]).first()
            if not role:
                role = Role(role_name=r["role_name"], description=r["description"])
                db.add(role)
                db.flush() # Forces ID generation within current block
                print(f"Seeded role: {r['role_name']}")
            roles_map[r["role_name"]] = role
            
        db.commit()
        
        # =========================================================================
        # STAGE 2: SEED PHYSICAL SPATIAL MANAGEMENT GRAPH (Nodes & Structural Dependencies)
        # =========================================================================
        building = db.query(Building).filter_by(building_name="FCI Building").first()
        if not building:
            building = Building(building_name="FCI Building")
            db.add(building)
            db.flush()
            
            floorplan = Floorplan(
                building_id=building.building_id, 
                floor_level=1, 
                image_path="floor1.png", 
                scale_ratio=1.0
            )
            db.add(floorplan)
            db.flush()
            
            # Seed structural nodes following spatial classification matrices
            # Locate your Node generation block and update the attributes:
            node1 = Node(
                floorplan_id=floorplan.floorplan_id, 
                coord_x=100.0, 
                coord_y=150.0, 
                room_label="Main Lobby", 
                is_accessible="ALLOW",  # Changed from True/1 to the correct ENUM string
                node_type="ENTRANCE"    # Changed from 'KIOSK' to a valid schema ENUM value
            )

            node2 = Node(
                floorplan_id=floorplan.floorplan_id, 
                coord_x=200.0, 
                coord_y=250.0, 
                room_label="Admin Office", 
                is_accessible="ALLOW", 
                node_type="OFFICE"      # Valid ENUM value
            )

            node3 = Node(
                floorplan_id=floorplan.floorplan_id, 
                coord_x=300.0, 
                coord_y=350.0, 
                room_label="Classroom 101", 
                is_accessible="ALLOW", 
                node_type="LECTURE_HALL" # Valid ENUM value
            )
            db.add_all([node1, node2, node3])
            db.flush()
            
            # Bind topological navigation pathway edge reference
            edge = Edge(
                source_node_id=node1.node_id, 
                destination_node_id=node2.node_id, 
                weight_distance=15.0, 
                is_accessible="ALLOW", 
                is_bidirectional=True
            )
            db.add(edge)
            print("Seeded physical references (Buildings, Floorplans, Nodes, Edges).")
            
        db.commit()
        
        # =========================================================================
        # STAGE 3: SEED SECURE IDENTITY ROOT (Dual-Table User -> Admin Extension Linkage)
        # =========================================================================
        # =========================================================================
        # STAGE 3: SEED RELATIONAL ORGANIZATIONAL DIRECTORY (Depts, Faculties, Programmes)
        # =========================================================================
        fac = db.query(Faculty).filter_by(faculty_id="FAC-FCI").first()
        if not fac:
            fac = Faculty(
                faculty_id="FAC-FCI",
                faculty_name="Faculty of Creative Information",
                dean_id="STF-00001"
            )
            db.add(fac)
            db.flush()
            
        dept = db.query(Department).filter_by(department_id="DEP-IT").first()
        if not dept:
            dept = Department(
                department_id="DEP-IT",
                department_name="Information Technology",
                manager_id="STF-00001"
            )
            db.add(dept)
            db.flush()
            
        prog = db.query(Programme).filter_by(programme_id="PRG-CS").first()
        if not prog:
            prog = Programme(
                programme_id="PRG-CS",
                programme_name="Computer Science",
                faculty_id="FAC-FCI",
                hop_id="STF-00001"
            )
            db.add(prog)
            db.flush()
            
        # =========================================================================
        # STAGE 4: SEED SECURE IDENTITY ROOT (User -> Staff -> Admin Linkage)
        # =========================================================================
        admin_role = roles_map["ADMIN"]
        existing_admin = db.query(User).filter_by(email="super.administrator@qiu.edu.my").first()
        
        if not existing_admin:
            password_plain = os.getenv("INITIAL_ADMIN_PASSWORD", "")
            try:
                password_plain = validate_strong_password(password_plain, name_parts=("super", "administrator", "qiu"))
            except ValueError as exc:
                raise RuntimeError("INITIAL_ADMIN_PASSWORD must be provided and meet the strong password policy") from exc
            password_hash = get_password_hash(password_plain)
            
            user = User(
                given_name="Super",
                family_name="Administrator",
                email="super.administrator@qiu.edu.my",
                is_active=True
            )
            db.add(user)
            db.flush()
            
            # Associate admin user with ADMIN role
            user.roles.append(admin_role)
            db.flush()
            
            office_node = db.query(Node).filter_by(room_label="Admin Office").first()
            office_id = office_node.node_id if office_node else None
            
            staff = Staff(
                staff_id="STF-00001",
                user_id=user.user_id,
                department_id="DEP-IT",
                position="System Administrator",
                office_node_id=office_id
            )
            db.add(staff)
            db.flush()
            
            admin = Admin(
                admin_id="ADM-00001",
                user_id=user.user_id,
                staff_id="STF-00001",
                admin_type="SUPER_ADMIN",
                password_hash=password_hash,
                must_change_password=True
            )
            db.add(admin)
            print("Seeded SUPER_ADMIN profile; require the provisioned password to be changed at first login.")
            
        db.commit()
        db.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
        print("Data seeding completed successfully!")
        
        try:
            import shutil
            from pathlib import Path
            from app.core.config import settings
            target_dir = settings.PRIVATE_STORAGE_ROOT / "floorplans"
            target_dir.mkdir(parents=True, exist_ok=True)
            source_dir = Path(__file__).resolve().parents[3] / "floorplan"
            if source_dir.exists():
                for img in source_dir.glob("*.jpeg"):
                    shutil.copy2(img, target_dir / img.name)
                print("Seeded floorplan images to private storage successfully.")
        except Exception as img_err:
            print(f"Note: Floorplan image copy skipped ({img_err})")
    except Exception as e:
        print(f"Error seeding relational database entries: {e}")
        db.rollback()
    finally:
        db.close()

def run_migrations():
    """
    Applies safe, idempotent schema migrations.
    Adds the `updated_at` column to the `users` table if it doesn't exist,
    then backfills existing rows from `enrolled_at`.
    """
    print("Running schema migrations...")
    try:
        with engine.connect() as conn:
            # Check if updated_at column already exists
            result = conn.execute(text(
                "SELECT COUNT(*) FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = DATABASE() "
                "AND TABLE_NAME = 'users' "
                "AND COLUMN_NAME = 'updated_at'"
            ))
            col_exists = result.scalar() > 0

            if not col_exists:
                print("Migration: Adding 'updated_at' column to 'users' table...")
                conn.execute(text(
                    "ALTER TABLE users "
                    "ADD COLUMN updated_at DATETIME NULL "
                    "AFTER enrolled_at"
                ))
                # Backfill existing rows so delta sync can still find them
                conn.execute(text(
                    "UPDATE users SET updated_at = enrolled_at WHERE updated_at IS NULL"
                ))
                conn.commit()
                print("Migration: 'updated_at' column added and backfilled successfully.")
            else:
                print("Migration: 'updated_at' column already exists, skipping.")
    except Exception as e:
        print(f"Migration error: {e}")


def main():
    create_database()
    run_migrations()

    print("Dropping existing tables to align database schema with models...")
    try:
        with engine.connect() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
            Base.metadata.drop_all(bind=conn)
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
            conn.commit()
        print("Existing tables dropped successfully.")
    except Exception as e:
        print(f"Note: Could not drop tables (this is normal on first run): {e}")

    print("Creating tables via SQLAlchemy mapping blueprints...")
    try:
        with engine.connect() as conn:
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 0;"))
            Base.metadata.create_all(bind=conn)
            conn.execute(text("SET FOREIGN_KEY_CHECKS = 1;"))
            conn.commit()
        print("Tables created successfully inside MySQL storage cluster.")
        seed_data()
    except Exception as e:
        print(f"Critical failure initializing physical transaction schema definitions: {e}")

if __name__ == "__main__":
    main()
