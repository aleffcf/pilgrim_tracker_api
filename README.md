# 🥾 Aparecida Pilgrim Tracking API

Backend REST API developed to support a **mobile pilgrim tracking application for journeys to Aparecida, Brazil**.

The system provides a secure and scalable foundation for registering pilgrims, organizing them into groups, authenticating users, sharing real-time location information, and managing group administrators.

> **Portfolio Project** — This repository demonstrates backend architecture, REST API development, authentication, database modeling, security practices, and asynchronous programming with Python.

---

## 📌 About the Project

Long-distance pilgrimages involve groups of people traveling together, often over several days and through areas where maintaining awareness of each participant's location can be difficult.

The goal of this project is to provide a backend capable of supporting a mobile application where:

* Pilgrims can join a specific group.
* Each pilgrim receives a unique access code.
* Users can authenticate securely.
* The mobile application can periodically send GPS coordinates.
* Pilgrims can see the latest known location of other members of their group.
* Group administrators can manage participants.
* Different groups remain isolated from one another.

The architecture was designed around a **multi-tenant model**, where each pilgrim belongs to a specific group (tenant).

---

# 🎯 Project Goals

The main technical goals of this project are:

* Build a clean REST API using FastAPI
* Implement asynchronous database operations
* Design a multi-tenant data model
* Provide secure authentication using JWT
* Protect access codes using bcrypt
* Implement role-based authorization for administrators
* Support GPS location updates
* Isolate location data between different groups
* Protect authentication endpoints against brute-force attempts
* Keep configuration and secrets outside the source code

---

# 🏗️ Architecture

The application follows a simple API-centric architecture:

```text
┌──────────────────────┐
│     Mobile App       │
│                      │
│  Pilgrim / Admin UI  │
└──────────┬───────────┘
           │
           │ HTTPS / REST
           ▼
┌──────────────────────────────┐
│          FastAPI             │
│                              │
│ ┌──────────┐ ┌────────────┐ │
│ │   Auth   │ │   Users    │ │
│ └──────────┘ └────────────┘ │
│                              │
│ ┌──────────┐ ┌────────────┐ │
│ │ Location │ │   Admin    │ │
│ └──────────┘ └────────────┘ │
└──────────────┬───────────────┘
               │
               │ SQLAlchemy Async
               ▼
┌──────────────────────────────┐
│         PostgreSQL           │
│                              │
│  tenants                     │
│  users                       │
└──────────────────────────────┘
```

The API uses SQLAlchemy's asynchronous engine and PostgreSQL through the `asyncpg` driver.

---

# 🧩 Core Concepts

## Multi-Tenant Groups

A **tenant** represents a pilgrim group.

Each tenant contains:

* Group information
* A unique join code
* An account limit
* Its associated pilgrims
* Administrators

```text
Tenant
│
├── Admin
│
├── Pilgrim
│   └── Last known location
│
├── Pilgrim
│   └── Last known location
│
└── Pilgrim
    └── Last known location
```

This structure allows the API to ensure that location data is only exposed to members of the same group.

---

# 🔐 Authentication

Authentication was designed around a simple flow suitable for a mobile application.

```text
QR / Join Code
      │
      ▼
┌───────────────┐
│ Register User │
└───────┬───────┘
        │
        ▼
  6-digit Access
       Code
        │
        ▼
┌───────────────┐
│     Login     │
└───────┬───────┘
        │
        ▼
    JWT Token
        │
        ▼
Authenticated API
      Requests
```

### Access Codes

Pilgrim accounts receive a randomly generated 6-digit access code.

The API never stores the code in plain text. It stores only a bcrypt hash and returns the plain-text code only when the account is created or its code is reset.

### JWT

Successful authentication generates a JWT containing the user and tenant identifiers.

```json
{
  "sub": "user_id",
  "tenant_id": 123,
  "exp": "expiration_timestamp"
}
```

The current implementation uses a long-lived token with a 365-day expiration period, designed to avoid repeatedly asking mobile users to authenticate.

---

# 🛡️ Security

Security was considered as part of the API design rather than as an afterthought.

### Passwordless-style access code

Instead of requiring traditional passwords, pilgrims use a generated access code that is stored using bcrypt hashing.

### JWT Authentication

Protected endpoints require:

```http
Authorization: Bearer <access_token>
```

### Tenant Isolation

Location queries are scoped to the authenticated user's tenant.

This prevents a user belonging to one group from retrieving the location of users belonging to another group.

### Login Rate Limiting

The login endpoint is limited to:

```text
5 requests / minute / IP
```

This reduces the risk of brute-force attacks against the 6-digit access code.

### Secure Admin Bootstrap

The first administrator is created using a server-side setup key.

The key is obtained from an environment variable and is never intended to be distributed to the mobile application.

---

# 🗄️ Data Model

The current database consists primarily of two entities.

## Tenant

```text
tenants
├── id
├── full_name
├── slug
├── join_code
├── max_accounts
├── created_at
└── updated_at
```

## User

```text
users
├── id
├── username
├── tenant_id
├── access_code_hash
├── is_admin
├── last_latitude
├── last_longitude
├── last_seen_at
├── created_at
└── updated_at
```

The user model stores the latest known location rather than an entire location history.

This keeps the initial implementation simple and efficient for the core use case.

---

# 📍 Location Tracking

The mobile application sends the user's current coordinates to:

```http
POST /location
```

Example:

```json
{
  "latitude": -22.8469,
  "longitude": -45.2297
}
```

The API updates:

* `last_latitude`
* `last_longitude`
* `last_seen_at`

Other members of the same group can then be retrieved through:

```http
GET /pessoas
```

Example response:

```json
[
  {
    "id": 15,
    "username": "john.doe",
    "latitude": -22.8469,
    "longitude": -45.2297,
    "last_seen_at": "2026-08-13T18:30:00Z"
  }
]
```

This endpoint provides the mobile application with the information required to display group members on a map.

---

# 📡 API Overview

| Method | Endpoint                     | Auth      | Description            |
| ------ | ---------------------------- | --------- | ---------------------- |
| `POST` | `/tenant`                    | —         | Create a pilgrim group |
| `GET`  | `/tenant/{join_code}/exists` | —         | Check group existence  |
| `POST` | `/user`                      | —         | Register a pilgrim     |
| `GET`  | `/users`                     | —         | List users             |
| `POST` | `/login`                     | —         | Authenticate           |
| `GET`  | `/me`                        | JWT       | Get current user       |
| `POST` | `/location`                  | JWT       | Update location        |
| `GET`  | `/pessoas`                   | JWT       | Get group locations    |
| `POST` | `/admin/bootstrap`           | Setup Key | Create first admin     |
| `POST` | `/user/{id}/promote`         | Admin     | Promote user           |
| `POST` | `/user/{id}/reset-code`      | Admin     | Reset access code      |

---

# 👤 Typical User Journey

```text
1. User opens the mobile application
              │
              ▼
2. Scans the group's QR Code
              │
              ▼
3. API validates the group
              │
              ▼
4. User creates their account
              │
              ▼
5. API generates a 6-digit access code
              │
              ▼
6. User logs in
              │
              ▼
7. API returns JWT
              │
              ▼
8. Mobile app stores the token securely
              │
              ▼
9. App periodically sends GPS coordinates
              │
              ▼
10. App retrieves other group members
              │
              ▼
11. Locations are displayed on the map
```

---

# 🛠️ Technology Stack

### Backend

**Python + FastAPI**

FastAPI provides the REST API layer, request validation, dependency injection, authentication integration, and automatic OpenAPI documentation.

### Database

**PostgreSQL**

Used as the primary relational database.

### ORM

**SQLAlchemy Async**

Database operations are implemented using asynchronous SQLAlchemy sessions.

### Authentication

**JWT + bcrypt**

JWT handles authenticated sessions while bcrypt protects user access codes.

### Rate Limiting

**SlowAPI**

Used to protect the login endpoint against excessive authentication attempts.

---

# 🚀 Getting Started

## Requirements

* Python 3.10+
* PostgreSQL
* pip
* Git

## Clone the repository

```bash
git clone <repository-url>
cd pilgrim_tracker_app
```

## Create a virtual environment

```bash
python -m venv .venv
```

### macOS / Linux

```bash
source .venv/bin/activate
```

### Windows

```powershell
.venv\Scripts\activate
```

## Install dependencies

```bash
pip install -r requirements.txt
```

## Configure environment variables

Create a `.env` file:

```env
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
DB_NAME=pilgrim_tracking

JWT_SECRET=your_secure_jwt_secret
ADMIN_SETUP_KEY=your_secure_admin_setup_key
```

Generate a secure JWT secret with:

```bash
openssl rand -hex 32
```

**Never commit `.env` to the repository.**

---

# ▶️ Running Locally

Start the development server:

```bash
uvicorn main:app --reload
```

The API will be available at:

```text
http://localhost:8000
```

Interactive API documentation:

```text
http://localhost:8000/docs
```

Alternative documentation:

```text
http://localhost:8000/redoc
```

---

# 🧪 API Documentation

FastAPI automatically generates interactive Swagger/OpenAPI documentation.

Once the API is running, open:

```text
/docs
```

This allows developers to:

* Explore endpoints
* Inspect request schemas
* Test authenticated endpoints
* Review response models
* Understand API contracts

---

# 🔄 Future Improvements

The current implementation focuses on the core functionality required by the mobile application.

Possible future improvements include:

### Location History

Currently only the latest location is stored.

A future version could introduce:

```text
location_history
├── id
├── user_id
├── latitude
├── longitude
└── recorded_at
```

This would enable:

* Route visualization
* Journey replay
* Distance calculations
* Historical analysis

### Real-Time Communication

The current implementation can use polling to retrieve updated locations.

A future version could introduce WebSockets for real-time location updates.

```text
Mobile App
    │
    │ WebSocket
    ▼
FastAPI
    │
    ▼
Connected Group Members
```

### Authentication Improvements

Potential improvements include:

* Refresh tokens
* Token revocation
* Device/session management
* More granular permissions

### Administrative Dashboard

A future web dashboard could provide:

* Participant management
* Live map
* Last-seen monitoring
* Group statistics
* User administration
* Route monitoring

---

# 📈 Production Considerations

Before deploying the API to production, the following areas should be reviewed:

* HTTPS/TLS
* Database migrations
* Database backups
* Production logging
* Monitoring
* Error tracking
* Restricted CORS configuration
* Strong secret management
* API authentication hardening
* Location privacy policies
* Input validation for geographic coordinates
* Secure mobile token storage
* Protection of administrative endpoints

The current CORS configuration allows all origins for development convenience and should be reviewed for production environments.

---

# 📁 Suggested Repository Structure

```text
aparecida-pilgrim-api/
│
├── app/
│   ├── main.py
│   ├── models/
│   ├── schemas/
│   ├── routes/
│   ├── services/
│   └── auth/
│
├── tests/
│
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
└── LICENSE
```

> The structure above represents a recommended evolution of the current implementation as the project grows.

---

# 💡 Technical Highlights

This project demonstrates practical backend engineering concepts including:

* REST API design
* Asynchronous Python
* FastAPI dependency injection
* PostgreSQL integration
* SQLAlchemy ORM
* Multi-tenant architecture
* JWT authentication
* Password/access-code hashing
* Role-based authorization
* Rate limiting
* Geographic data handling
* Environment-based configuration
* API validation with Pydantic
* Automatic OpenAPI documentation
* Database constraint handling

---

# 👨‍💻 Portfolio Context

This project was developed as a backend foundation for a mobile application focused on **pilgrim safety, group coordination, and location awareness during journeys to Aparecida**.

The implementation prioritizes a simple user experience while demonstrating backend concerns such as authentication, authorization, tenant isolation, database design, and secure handling of credentials.

The project is also structured to allow future expansion into real-time tracking, historical route visualization, administrative dashboards, and analytics.

---

# 📄 License

This project is **proprietary software**.

The source code is publicly available for portfolio and evaluation purposes.

Viewing the source code does not grant permission to copy, modify, distribute, sublicense, or use the software commercially without prior written permission from the copyright holder.

**All rights reserved.**

---

# 📬 Contact

For professional inquiries, collaboration, or access to additional project information, please contact the author through the contact information available on the GitHub profile.
