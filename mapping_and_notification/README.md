# Campus Navigation System

A comprehensive, multi-floor, multi-building routing and navigation system with a React frontend, Node.js/Express backend, RabbitMQ-based notification engine, and Python FastAPI AI microservice for map processing.

## 🏗 System Architecture

The Campus Navigation System is composed of four major components working in tandem:

### 1. React Frontend (`/frontend`)
The administrative dashboard and primary user interface for managing campus maps.
* **Core Responsibilities**: 
  * Map upload and floorplan management.
  * Interactive Konva-based canvas for drawing nodes and edges.
  * Role-Based Access Control (RBAC) configuration for pathways.
  * Testing navigation flows and viewing pathing visualization.
* **Tech Stack**: React 19, Tailwind CSS, Konva (canvas rendering).

### 2. Node.js Backend (`/backend`)
The core API server, database interface, and navigation engine.
* **Core Responsibilities**: 
  * Authentication and role management.
  * Storing graphs (nodes, edges, floorplans, buildings) in MySQL.
  * Executing the multi-floor **A* Pathfinding Algorithm**.
  * Generating step-by-step natural language routing instructions.
  * Generating visual `.png` route previews.
  * Publishing notification events to RabbitMQ.
* **Tech Stack**: Node.js, Express, MySQL2, JSON Web Tokens.

### 3. RabbitMQ Notification System (`/backend/consumer.js`)
An asynchronous, decoupled messaging system for handling heavy external integrations.
* **Core Responsibilities**:
  * Offloading email/notification delivery from the main API thread.
  * Generating rich HTML emails containing navigation routes and images.
  * Ethereal integration for local development/testing of emails.
* **Tech Stack**: amqplib, nodemailer, RabbitMQ.

### 4. Python AI Services (`/ai-services`)
A computer vision microservice designed to process map imagery.
* **Core Responsibilities**:
  * Analyzing uploaded floorplans via OpenCV.
  * Detecting walls and obstacles to aid in automatic path generation.
* **Tech Stack**: Python, FastAPI, OpenCV, Pydantic.

---

## 🚀 Getting Started

### Prerequisites
* **Node.js** (v18+)
* **Python** (3.9+)
* **MySQL** Server
* **RabbitMQ** Server

### 1. Database Setup
1. Create a MySQL database named `campus_navigation`.
2. Import the schema (if applicable).
3. Ensure your MySQL server is running on the default port.

### 2. Environment Configuration
Copy `.env.example` to `.env` in the following locations and populate the values:
* `backend/.env`
* `ai-services/.env`

### 3. Installation
From the root directory, install all dependencies for the entire system:
```bash
npm run install:all
```

### 4. Running the Complete System
You can start the frontend, backend, RabbitMQ consumer, and AI service simultaneously using the root startup script:
```bash
npm start
```
This will launch:
* Backend API on `http://localhost:5000`
* AI Service on `http://localhost:8000`
* Frontend App on `http://localhost:3000`
* The RabbitMQ background consumer.

---

## 🛠 Important Commands
The root `package.json` provides scripts to manage individual services:
* `npm run start:backend` — Starts the Node.js API with Nodemon.
* `npm run start:consumer` — Starts the RabbitMQ email consumer worker.
* `npm run start:ai` — Starts the FastAPI server via Uvicorn.
* `npm run start:frontend` — Starts the React development server.

## 🔐 Role-Based Access Control (RBAC)
Paths and nodes can be restricted by roles (Admin, Staff, Student, Visitor). The navigation engine factors in the user's role dynamically during A* pathfinding, ensuring that users are only routed through corridors and elevators they are authorized to access.
