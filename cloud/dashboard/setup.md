# Smart Campus Administrative Dashboard Setup Guide

This guide details the step-by-step process of installing, configuring, and launching the database server, python backend environment, and dashboard from scratch.

---

## Step 1: Setting Up the MySQL Database Server

Since MySQL is not yet configured or running on your machine, you can choose **either** Option 1 (local installation) or Option 2 (using Docker):

### Option 1: Direct Local Installation (No Docker)
1. Go to the [MySQL Community Downloads page](https://dev.mysql.com/downloads/installer/).
2. Download the **MySQL Installer for Windows**.
3. Run the installer, select **Custom** or **Developer Default**, and check:
   - **MySQL Server** (version 8.0, 9.0+)
   - **MySQL Workbench** (Optional: GUI manager)
4. During configuration:
   - Keep default Port `3306`.
   - Set a password for the `root` account (remember this for your `.env` file).
   - Configure it as a Windows Service named `MySQL97` (or similar).
5. Finish installation.

### Option 2: Running via Docker (Requires Docker Desktop)
If you already have Docker installed and prefer not to install MySQL directly on your Windows system, you can boot a MySQL container in seconds:
1. Open PowerShell or Command Prompt.
2. Run the following command to download and spin up a MySQL container:
   ```bash
   docker-compose up -d
   docker run --name smart-campus-mysql -e MYSQL_ROOT_PASSWORD=3996 -p 3306:3306 -d mysql:9.0
   ```
3. Set `DB_PASSWORD=your_root_password_here` in your `.env` file. The FastAPI backend will connect to it exactly the same way.

---

### B. Verify / Start the Service
* **For Option 1 (Local Service)**:
  Press `Win + R`, type `services.msc`, and ensure the service named **MySQL97** is *Running*. You can start it via:
  ```powershell
  Start-Service -Name MySQL97
  ```
* **For Option 2 (Docker Container)**:
  Ensure Docker Desktop is open and run:
  ```bash
  docker start biometric-mysql
  ```
On Windows, check if the database is running:
1. Press `Win + R`, type `services.msc`, and press Enter.
2. Scroll down to find your MySQL service (e.g. **MySQL97** or **MySQL80**).
3. If the status is not *Running*, right-click it and select **Start**.
   - *(Alternative via Administrator PowerShell)*:
     ```powershell
     Start-Service -Name MySQL97
     ```

---

## Step 2: Preparing the Python Environment

Your project already has a `.venv` folder configured in the `Code_FYP` root directory. We will use this environment to install dependencies and avoid global library pollution.

### A. Open Terminal in Project Root
Open a Command Prompt or PowerShell in the root workspace directory:
`c:\Users\kahyu\OneDrive\Documents\Kah Yuen\Degree\FYP\Code_FYP`

### B. Activate Virtual Environment
Run the activation command depending on your terminal shell:
- **PowerShell**:
  ```powershell
  .venv\Scripts\Activate.ps1
  ```
- **Command Prompt (CMD)**:
  ```cmd
  .venv\Scripts\activate.bat
  ```
*(You will see `(.venv)` displayed at the start of your terminal line once activated).*

### C. Install Requirements
With the virtual environment activated, install all backend packages:
```bash
pip install -r cloud/requirements.txt
```
This will fetch and configure:
- `fastapi` & `uvicorn` (ASGI Web server stack)
- `sqlalchemy` (ORM database management)
- `mysql-connector-python` (MySQL connectivity driver)
- `bcrypt` & `pyjwt` (Security & token generation)
- `python-dotenv`, `passlib`, RAG, sync, and cloud facial-recognition dependencies

---

## Step 3: Configure Environment Variables

1. Go to `cloud/dashboard/backend/.env`.
2. Look for the database configuration parameters and input your MySQL configuration:
   ```ini
   DB_HOST=localhost
   DB_PORT=3306
   DB_USER=root
   DB_PASSWORD=your_root_password_here   <-- Insert the password you set during installation
   DB_NAME=biometric_rag_db
   ```
3. Save the file.

---

## Step 4: Schema Migration and Initial Data Seeding

We have created an automated script that automatically creates the database schema structures, primary tables, and pre-populates basic reference data.

Run this script from your terminal:
```bash
python dashboard/backend/app/db_init.py
```

### What this script does:
1. Connects to your MySQL server using credentials from your `.env`.
2. Creates the database `biometric_rag_db` if it doesn't already exist.
3. Automatically sets up all 24 database tables, relations, and index matrices.
4. Seeds default roles: `STUDENT`, `LECTURER`, `VISITOR`, `ADMIN`.
5. Seeds a default campus structure (e.g. `FCI Building`, Room nodes, and path edges).
6. Creates a default **SUPER_ADMIN** profile:
   - **Username**: `admin`
   - **Password**: `admin123`

---

## Step 5: Start the FastAPI Application

Now that the database is running and python packages are set up, run the server:

```bash
python -m uvicorn dashboard.backend.app.main:app --reload
```

You should see output similar to:
```text
INFO:     Started server process [12820]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
```

---

## Step 6: Log In and Test the Dashboard

1. Open your browser and navigate to:
   **[http://127.0.0.1:8000/dashboard/](http://127.0.0.1:8000/dashboard/)**
2. Use the seeded credentials to log in:
   - **Username**: `admin`
   - **Password**: `admin123`
3. Once logged in, you will access the admin overview console. You can:
   - Browse and CRUD user profiles (under *Identity Profiles*).
   - Track and add hardware items (under *Infrastructure*).
   - Modify timetables and class slots (under *Academics & Slots*).

---

## Troubleshooting Guide

### 1. `Error: Can't connect to MySQL server on 'localhost:3306' (10061)`
- **Cause**: The MySQL service is not running or is blocked.
- **Solution**: Open `services.msc`, locate your MySQL service, right-click, and select **Start**.

### 2. `Error: Access denied for user 'root'@'localhost'`
- **Cause**: The database password in your `dashboard/backend/.env` is incorrect.
- **Solution**: Open the `.env` file and verify that the `DB_PASSWORD` value matches the exact root password configured during the MySQL installation.

### 3. `ModuleNotFoundError: No module named 'fastapi'`
- **Cause**: You ran the server command outside of your python virtual environment.
- **Solution**: Make sure you activate the virtual environment (`.venv\Scripts\activate`) before running any python scripts or uvicorn commands.
