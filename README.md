# Aparecida Pilgrim Tracking API

Backend API for a mobile application designed to track pilgrims during the journey to **Aparecida, Brazil**.

The API provides multi-tenant group management, pilgrim registration and authentication, GPS location updates, real-time group member location retrieval, and administrator management.

Built with **FastAPI**, **PostgreSQL**, **SQLAlchemy Async**, **JWT**, and **bcrypt**.

---

## Features

* Multi-tenant architecture for pilgrim groups
* Group/tenant creation with unique join codes
* QR-code-friendly group joining
* Pilgrim registration using a group join code
* Automatic generation of a 6-digit pilgrim access code
* Secure access-code hashing with bcrypt
* JWT-based authentication
* Long-lived authentication tokens
* GPS location tracking
* Retrieval of the latest location of pilgrims within the same group
* Administrator accounts
* Admin bootstrap mechanism
* Admin promotion of existing users
* Access-code reset
* Login rate limiting
* PostgreSQL asynchronous database access
* CORS configuration
* Environment-based configuration

---

## Tech Stack

| Technology    | Purpose                         |
| ------------- | ------------------------------- |
| Python        | Backend language                |
| FastAPI       | REST API framework              |
| PostgreSQL    | Database                        |
| SQLAlchemy    | ORM and database access         |
| asyncpg       | Async PostgreSQL driver         |
| Pydantic      | Request/response validation     |
| PyJWT         | JWT authentication              |
| bcrypt        | Access-code hashing             |
| SlowAPI       | Rate limiting                   |
| python-dotenv | Environment variable management |

The application uses SQLAlchemy's asynchronous engine and session management to communicate with PostgreSQL.

---

# Architecture

The application uses a **multi-tenant model**.

A tenant represents a pilgrim group, organization, or journey.

```text
Tenant / Pilgrim Group
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

Each user belongs to exactly one tenant.

The database stores the user's tenant relationship together with their latest latitude, longitude, and timestamp.

This allows the application to restrict location visibility to members of the same pilgrim group.

---

# Requirements

Before running the API, make sure you have:

* Python 3.10+
* PostgreSQL
* `pip`
* A PostgreSQL database
* Environment variables configured

---

# Installation

Clone the repository:

```bash
git clone <your-repository-url>
cd <project-directory>
```

Create a virtual environment:

```bash
python -m venv .venv
```

Activate it on macOS/Linux:

```bash
source .venv/bin/activate
```

On Windows:

```powershell
.venv\Scripts\activate
```

Install dependencies:

```bash
pip install fastapi uvicorn sqlalchemy asyncpg pydantic pyjwt bcrypt python-dotenv slowapi
```

---

# Environment Variables

Create a `.env` file in the project root:

```env
DB_USER=postgres
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=5432
DB_NAME=pilgrim_tracking

JWT_SECRET=your_secure_jwt_secret
ADMIN_SETUP_KEY=your_secure_admin_setup_key
```

The API loads these variables using `python-dotenv`.

## Generating a JWT secret

Use a cryptographically secure random value.

For example:

```bash
openssl rand -hex 32
```

Never commit your `.env` file to source control.

Add it to `.gitignore`:

```gitignore
.env
.venv/
__pycache__/
```

---

# Running the API

Start the FastAPI application with Uvicorn:

```bash
uvicorn main:app --reload
```

For production:

```bash
uvicorn main:app --host 0.0.0.0 --port 8000
```

The API will be available at:

```text
http://localhost:8000
```

FastAPI automatically provides interactive API documentation at:

```text
http://localhost:8000/docs
```

and OpenAPI documentation at:

```text
http://localhost:8000/redoc
```

---

# Authentication

The API uses two authentication mechanisms during the account lifecycle:

1. **Group Join Code + Access Code**
2. **JWT Bearer Token**

## Access Code

When a pilgrim account is created, the API generates a random 6-digit access code.

The code is returned only in the account creation response and is stored in the database as a bcrypt hash.

Example:

```text
482731
```

The mobile application should securely store this code if the user needs it later.

---

## JWT

After a successful login, the API returns a JWT access token.

The token contains:

```json
{
  "sub": "user_id",
  "tenant_id": 123,
  "exp": "expiration_timestamp"
}
```

Tokens currently expire after **365 days**.

Authenticated requests must send:

```http
Authorization: Bearer <access_token>
```

---

# API Endpoints

## Tenant / Group

### Create a Tenant

```http
POST /tenant
```

Creates a new pilgrim group.

### Request

```json
{
  "full_name": "Caminhada para Aparecida 2026",
  "slug": "caminhada-aparecida-2026",
  "max_accounts": 50
}
```

### Response

```json
{
  "id": 1,
  "full_name": "Caminhada para Aparecida 2026",
  "slug": "caminhada-aparecida-2026",
  "join_code": "K7P4XZ",
  "max_accounts": 50
}
```

The API automatically generates a unique join code for the group. The code is designed to be suitable for QR-code usage and avoids visually ambiguous characters.

---

## Check Whether a Group Exists

```http
GET /tenant/{join_code}/exists
```

Example:

```http
GET /tenant/K7P4XZ/exists
```

Response:

```json
{
  "exists": true
}
```

This endpoint can be used by the mobile application before attempting to register a pilgrim.

---

# Users / Pilgrims

## Create a Pilgrim

```http
POST /user
```

Registers a new pilgrim in an existing group.

### Request

```json
{
  "username": "john.doe",
  "tenant_join_code": "K7P4XZ"
}
```

The API:

1. Validates the group join code.
2. Checks the group's account limit.
3. Generates a random 6-digit access code.
4. Hashes the access code with bcrypt.
5. Creates the user.
6. Returns the generated access code once.

### Response

```json
{
  "id": 15,
  "username": "john.doe",
  "tenant_id": 1,
  "access_code": "482731"
}
```

> **Important:** The access code is returned in plain text only during account creation or reset. The database stores only its hash.

---

## Get All Users

```http
GET /users
```

Returns the users currently stored in the database.

> This endpoint is currently not protected by authentication. For production, consider restricting it to administrators.

---

# Login

## Authenticate a Pilgrim

```http
POST /login
```

### Request

```json
{
  "tenant_join_code": "K7P4XZ",
  "access_code": "482731"
}
```

### Response

```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIs...",
  "token_type": "bearer"
}
```

The endpoint is protected by a rate limit of:

```text
5 requests per minute per IP address
```

This helps reduce brute-force attempts against the 6-digit access code.

---

# Current User

```http
GET /me
```

Requires authentication.

### Headers

```http
Authorization: Bearer <access_token>
```

### Response

```json
{
  "id": 15,
  "username": "john.doe",
  "tenant_id": 1
}
```

This endpoint can be used by the mobile app to verify the current authenticated user.

---

# Location Tracking

## Update Current Location

```http
POST /location
```

Requires authentication.

### Headers

```http
Authorization: Bearer <access_token>
```

### Request

```json
{
  "latitude": -22.8469,
  "longitude": -45.2297
}
```

The API stores:

* Latitude
* Longitude
* Last-seen timestamp

### Response

```json
{
  "ok": true
}
```

The mobile application can call this endpoint periodically while tracking is active.

---

## Get Pilgrims' Locations

```http
GET /pessoas
```

Requires authentication.

The API returns users belonging to the **same tenant/group** as the authenticated user and who have a known location.

### Response

```json
[
  {
    "id": 15,
    "username": "john.doe",
    "latitude": -22.8469,
    "longitude": -45.2297,
    "last_seen_at": "2026-08-13T18:30:00Z"
  },
  {
    "id": 16,
    "username": "mary.smith",
    "latitude": -22.8475,
    "longitude": -45.2281,
    "last_seen_at": "2026-08-13T18:29:32Z"
  }
]
```

This endpoint is intended to provide the mobile application with the information required to display other pilgrims on a map.

---

# Administration

## Admin Bootstrap

```http
POST /admin/bootstrap
```

Creates the first administrator for a tenant.

This endpoint requires the server-side setup key:

```http
X-Setup-Key: <ADMIN_SETUP_KEY>
```

### Request

```json
{
  "username": "admin",
  "tenant_join_code": "K7P4XZ"
}
```

### Response

```json
{
  "id": 1,
  "username": "admin",
  "tenant_id": 1,
  "access_code": "731942"
}
```

The setup key must never be embedded in or distributed with the mobile application. It is intended for infrastructure/admin use only.

---

## Promote User to Admin

```http
POST /user/{user_id}/promote
```

Requires an authenticated administrator.

Example:

```http
POST /user/15/promote
```

The target user must belong to the same tenant as the administrator.

---

## Reset User Access Code

```http
POST /user/{user_id}/reset-code
```

Requires an authenticated administrator.

Example:

```http
POST /user/15/reset-code
```

### Response

```json
{
  "id": 15,
  "username": "john.doe",
  "tenant_id": 1,
  "access_code": "928341"
}
```

The old access code becomes invalid and the new code is returned once.

---

# Mobile Application Flow

A typical pilgrim flow is:

```text
                    ┌─────────────────┐
                    │ Create / Select │
                    │     Group       │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   Scan QR Code  │
                    │  / Enter Code   │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ Register User   │
                    │   POST /user    │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │ Receive Access  │
                    │      Code       │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   POST /login   │
                    └────────┬────────┘
                             │
                             ▼
                    ┌─────────────────┐
                    │   Store JWT     │
                    │  Securely on    │
                    │      device     │
                    └────────┬────────┘
                             │
                  ┌──────────┴──────────┐
                  ▼                     ▼
          ┌───────────────┐     ┌────────────────┐
          │ POST /location│     │ GET /pessoas   │
          │ periodically  │     │ periodically   │
          └───────────────┘     └────────────────┘
```

---

# Recommended Tracking Strategy

The mobile application should avoid sending GPS updates continuously at maximum frequency.

A practical approach is to send location updates:

* At a fixed interval, such as every 15–60 seconds
* When the user has moved a meaningful distance
* When tracking starts
* When the application resumes tracking
* Optionally when significant location changes are detected

For example:

```text
Tracking started
      │
      ▼
Get GPS location
      │
      ▼
POST /location
      │
      ▼
Wait / detect movement
      │
      ▼
Get new GPS location
      │
      ▼
POST /location
      │
      └───────────────► repeat
```

The exact interval should be tuned based on battery consumption, GPS accuracy, network availability, and the desired tracking experience.

---

# Database Model

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

The tenant represents a pilgrim group.

The `join_code` is unique and is used by pilgrims to join the group. `max_accounts` controls the number of users allowed in the tenant.

---

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

The `tenant_id` establishes the relationship between a pilgrim and their group.

The API currently stores only the **latest known location**, rather than a historical location trail.

---

# Security

The API implements several security mechanisms.

### Password/access-code hashing

Access codes are never stored in plain text. They are hashed using bcrypt.

### JWT authentication

Protected endpoints require a valid Bearer token.

### Tenant isolation

Location queries are filtered using the authenticated user's tenant ID, preventing users from retrieving locations from other groups.

### Login rate limiting

Login attempts are limited to 5 requests per minute per IP address.

### Secure setup key

The admin bootstrap operation requires a server-side setup key and uses constant-time comparison.

### Environment variables

Secrets and database credentials are loaded from environment variables instead of being hard-coded.

---

# HTTP Status Codes

The API uses standard HTTP status codes.

| Status | Meaning                                            |
| ------ | -------------------------------------------------- |
| `200`  | Successful request                                 |
| `401`  | Authentication failed / invalid token              |
| `403`  | Authenticated but not authorized                   |
| `404`  | Resource not found                                 |
| `409`  | Resource conflict, such as duplicate username/slug |
| `422`  | Request validation error                           |
| `429`  | Rate limit exceeded                                |

Examples of conflicts include an already-used tenant slug or username.

---

# CORS

The current development configuration allows all origins:

```python
allow_origins=["*"]
```

This is convenient during development, but production deployments should restrict allowed origins when browser-based clients or dashboards are used.

Native mobile applications are generally not subject to browser CORS restrictions.

---

# Production Checklist

Before deploying the API to production, review the following:

* [ ] Use HTTPS
* [ ] Generate a strong `JWT_SECRET`
* [ ] Generate a strong `ADMIN_SETUP_KEY`
* [ ] Never expose `ADMIN_SETUP_KEY` to the mobile app
* [ ] Never commit `.env` to Git
* [ ] Restrict CORS if a web frontend is introduced
* [ ] Configure PostgreSQL with proper credentials
* [ ] Add database migrations
* [ ] Protect `/users` with authentication/authorization
* [ ] Add logging and monitoring
* [ ] Configure database backups
* [ ] Consider connection pool configuration
* [ ] Consider token revocation/refresh strategy
* [ ] Validate latitude and longitude ranges
* [ ] Consider privacy requirements for location data
* [ ] Consider historical location storage if route history is required
* [ ] Configure a production ASGI server/reverse proxy
* [ ] Add automated tests

---

# Future Improvements

Depending on the evolution of the mobile application, the following features may be useful:

## Location History

Currently, each user has only their latest known coordinates.

A separate table could store:

```text
location_history
├── id
├── user_id
├── latitude
├── longitude
└── recorded_at
```

This would allow the application to reconstruct a pilgrim's route.

## Real-Time Updates

The current architecture relies on HTTP polling.

For real-time map updates, WebSockets or Server-Sent Events could be introduced.

```text
Mobile App
    │
    │ WebSocket
    ▼
FastAPI
    │
    ▼
Connected Pilgrims
```

## Refresh Tokens

The current JWT is intentionally long-lived.

A refresh-token architecture could provide better control over sessions and token revocation.

## Better Admin Controls

Possible future administrative features include:

* Remove pilgrim from group
* Delete/deactivate user
* View group members
* View last-seen status
* Export participant data
* Monitor active pilgrims
* Manage group capacity

---

# API Design Summary

| Method | Endpoint                     | Authentication | Purpose                    |
| ------ | ---------------------------- | -------------- | -------------------------- |
| `POST` | `/tenant`                    | Public         | Create a group             |
| `GET`  | `/tenant/{join_code}/exists` | Public         | Check group existence      |
| `GET`  | `/users`                     | Public*        | List users                 |
| `POST` | `/user`                      | Public         | Register pilgrim           |
| `POST` | `/login`                     | Public         | Authenticate user          |
| `GET`  | `/me`                        | JWT            | Get current user           |
| `POST` | `/location`                  | JWT            | Update current location    |
| `GET`  | `/pessoas`                   | JWT            | Get group member locations |
| `POST` | `/admin/bootstrap`           | Setup key      | Create first admin         |
| `POST` | `/user/{user_id}/promote`    | Admin JWT      | Promote user               |
| `POST` | `/user/{user_id}/reset-code` | Admin JWT      | Reset access code          |

* The `/users` endpoint is currently public in the implementation and should likely be protected before production.

---

# License

Add the project's license here, for example:

```text
MIT License
```

if the project is intended to be distributed under the MIT license.

---

# Project Purpose

This API is designed to support a mobile pilgrim-tracking experience for journeys to **Aparecida**, providing a simple authentication model suitable for pilgrims while maintaining group-level isolation for location data.

The architecture intentionally keeps the client flow simple:

**Join Group → Register → Login → Track Location → View Group Members**
