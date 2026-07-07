import os

file_path = r"c:\Users\kahyu\Desktop\Code_FYP\cloud\dashboard\backend\app\routers\iam.py"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

target = """    else:
        if not admin_in.user:
        staff = Staff("""

replacement = """    else:
        if not admin_in.user:
            raise HTTPException(status_code=400, detail="User registration data is required for a new user")
        if db.query(User).filter_by(username=admin_in.user.username).first():
            raise HTTPException(status_code=400, detail="Username already taken")
            
        email = generate_unique_email(db, admin_in.user.given_name, admin_in.user.family_name)
        user = User(
            given_name=admin_in.user.given_name,
            family_name=admin_in.user.family_name,
            email=email,
            username=admin_in.user.username,
            is_active=admin_in.user.is_active
        )
        admin_role = db.query(Role).filter_by(role_name="ADMIN").first()
        if admin_role:
            user.roles.append(admin_role)
        db.add(user)
        db.flush()

    # 3. Find or auto-create Staff profile (the trigger)
    staff = db.query(Staff).filter_by(user_id=user.user_id).first()
    if not staff:
        dept = get_or_create_department(db, admin_in.department or "DEP-IT")
        staff = Staff("""

if target in content:
    content = content.replace(target, replacement)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(content)
    print("SUCCESS: iam.py has been fixed!")
else:
    print("ERROR: Target sequence not found in iam.py!")
