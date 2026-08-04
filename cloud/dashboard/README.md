# Smart Campus Administrative Dashboard

This dashboard is a modular administrative system for the Smart Campus portal, featuring a **FastAPI** backend, **SQLAlchemy ORM** database mappings, and **React + Tailwind CSS** frontend clients. 

It manages physical clearance profiles, RAG knowledge indexing, hardware health monitoring, and class/appointment timetabling with robust double-booking validation checks.

---

## Folder Structure

```text
dashboard/
├── backend/
│   ├── app/
│   │   ├── core/
│   │   │   ├── config.py       # Configuration loader (.env parser)
│   │   │   ├── database.py     # SQLAlchemy DB connection engine & session
│   │   │   └── security.py     # Password hashing & JWT middleware checks
│   │   ├── models/
│   │   │   └── models.py       # SQLAlchemy ORM models for all 20+ tables
│   │   ├── schemas/
│   │   │   └── schemas.py      # Pydantic validation schemas
│   │   ├── routers/
│   │   │   ├── auth.py         # Login logs, secure token checks
│   │   │   ├── iam.py          # CRUD for student, lecturer, visitor profiles
│   │   │   ├── rag.py          # Document chunk management
│   │   │   ├── infrastructure.py # Device heartbeats, Node/Edge clearance settings
│   │   │   ├── academics.py    # Courses, enrollments, overlapping timetables
│   │   │   └── references.py   # Buildings, Floorplans, Nodes, Edges dropdown refs
│   │   ├── static/
│   │   │   └── index.html      # Single-Page CDN React App (Zero-Node setup preview)
│   │   ├── db_init.py          # DB schema migration & data seeding helper
│   │   └── main.py             # FastAPI entrypoint, middleware, static routers
│   └── requirements.txt        # Backend python dependencies
└── frontend/                   # Full modular React + Vite skeleton
    ├── package.json            # Node package configurations
    ├── vite.config.js          # Vite config with API proxy mappings
    ├── tailwind.config.js      # Tailwind theme adjustments
    ├── index.html              # HTML entrypoint
    └── src/
        ├── App.jsx             # Boilerplate App setup
        └── index.css           # Tailwind directives
```

---

## Requirements

1. **Python 3.10+**
2. **MySQL Database Server** (e.g., MySQL 8.0, 9.0+)
3. **Node.js & npm** *(Optional, only required if compiling or extending the `/frontend` Vite project)*

---

## Setup & Run Instructions

### 1. Database Initialization
Before running the server, verify your local MySQL server is active. On Windows, you can start the service by running this in an Administrator command prompt:
```powershell
Start-Service -Name MySQL97
```

### 2. Configure Environment Variables
A configuration `.env` file is generated at `dashboard/backend/.env`. Edit this file to match your local MySQL configuration:
```ini
DB_HOST=localhost
DB_PORT=3306
DB_USER=smart_campus_app
DB_PASSWORD=your_mysql_password
DB_NAME=biometric_rag_db
```

### 3. Install Python Dependencies
Run pip in your terminal (using your virtual environment) to install the backend requirements:
```bash
.venv\Scripts\pip install -r cloud/requirements.txt
```

### 4. Create Tables and Seed Default User
Run the initialization script to configure the database, run table structures, and seed the default roles, buildings, nodes, and a **SUPER_ADMIN** user:
```bash
.venv\Scripts\python.exe cloud/dashboard/backend/app/db_init.py
```

*Seeded credentials for test login:*
* **Username**: `admin`
* **Password**: the strong password provisioned during initialization; no default exists.

### 5. Launch the FastAPI Server
Start the Uvicorn local development server:
```bash
.venv\Scripts\python.exe -m uvicorn cloud.dashboard.backend.app.main:app --reload
```

`.\start_cloud.ps1` starts the separate RabbitMQ notification worker
automatically. Use `-SkipNotificationWorker` when the worker is managed
separately. The worker uses the durable `campus.notifications.queue` topology.

---

## Accessing the Frontends

### Option A: Out-Of-The-Box React SPA (Recommended)
You can access the fully interactive **React + Tailwind** administrative portal immediately by opening:
👉 **[http://127.0.0.1:8000/dashboard/](http://127.0.0.1:8000/dashboard/)**

This view runs entirely off the static FastAPI mount and does not require Node.js, compiling, or package managers.

The integrated Mapping & Notifications feature is available at
`/dashboard/mapping-notification`. It includes floorplan selection/upload, node
and edge editing, wall overlays, route preview, notification testing, and audit
refresh through relative `/api/mapping-notification` calls.

### Option B: Vite + React Development Skeleton
If you install Node.js/npm and wish to run the project in development mode:
1. Navigate to the frontend directory:
   ```bash
   cd dashboard/frontend
   ```
2. Install npm pack:
   ```bash
   npm install
   ```
3. Run the development server:
   ```bash
   npm run dev
   ```
4. Visit `http://localhost:5173/`. All API calls to `/api/*` will automatically be proxied to your running FastAPI backend at port 8000.

---

## Admin Tiers Reference

- `SUPER_ADMIN`: Full CRUD privileges across all tables (IAM, RAG, Infra, Academics).
- `SYSTEM_ADMIN`: Allowed to manage users, identity profiles, edge devices, and access clearing tables. Barred from accessing RAG knowledge bases.
- `CONTENT_ADMIN`: Confined strictly to RAG knowledge bases, document uploads, and chatbot query monitoring. Barred from access control and user directories.
