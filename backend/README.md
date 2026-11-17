# SwiftWash Flask Backend

Flask + MongoDB REST API based on the SwiftWash OpenAPI 3.0.3 YAML.

## 1. Requirements
- Python 3.10+
- MongoDB Community Server running locally (or a MongoDB Atlas connection string)
- Postman for testing (optional)

## 2. Setup (Windows PowerShell)
```powershell
cd swiftwash_backend
py -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```
Edit `.env` and replace `JWT_SECRET_KEY` with a long random secret. Set `MONGO_URI` to your local MongoDB URI or Atlas URI.

## 3. Run
```powershell
python app.py
```
The API runs at `http://localhost:5000/api/v1`.
Health check: `GET http://localhost:5000/api/v1/health`.

## 4. First admin account
Public registration intentionally does not allow the `admin` role. Register a customer, partner, or rider normally. To create the first admin, open `mongosh` and run:
```javascript
use swiftwash
db.users.insertOne({
  role: "admin",
  name: "SwiftWash Administrator",
  email: "admin@swiftwash.local",
  passwordHash: "$2b$12$REPLACE_WITH_A_BCRYPT_HASH",
  isActive: true,
  createdAt: new Date().toISOString(),
  updatedAt: new Date().toISOString()
})
```
Generate a bcrypt hash locally:
```powershell
python -c "from flask_bcrypt import Bcrypt; from flask import Flask; a=Flask(__name__); b=Bcrypt(a); print(b.generate_password_hash('ChangeMe123!').decode())"
```
Use the printed hash in MongoDB, then log in with that email and password. Change the password immediately.

## 5. Authentication
Register/login returns `{ "token": "...", "user": {...} }`.
For protected endpoints, send:
```
Authorization: Bearer YOUR_JWT_TOKEN
Content-Type: application/json
```

## 6. Main endpoints
| Method | Endpoint | Purpose |
|---|---|---|
| POST | `/auth/register` | Register customer, partner, rider |
| POST | `/auth/login` | Login and receive JWT |
| GET | `/users/me` | Current user's profile |
| GET/PATCH/DELETE | `/users/{userId}` | User management |
| GET/POST | `/partners` | Browse/create partner profile |
| GET/PUT/DELETE | `/partners/{partnerId}` | Partner profile |
| PATCH | `/partners/{partnerId}/approval` | Admin approval |
| GET/POST | `/services` | Browse/create services |
| GET/PUT/DELETE | `/services/{serviceId}` | Service management |
| GET | `/partners/{partnerId}/services` | Partner services |
| GET | `/riders` | Find available riders |
| GET/POST | `/orders` | List/book orders |
| GET/PUT/DELETE | `/orders/{orderId}` | Order details |
| PATCH | `/orders/{orderId}/status` | Confirm/cancel |
| PATCH | `/orders/{orderId}/rider` | Assign/reassign rider |
| PATCH | `/orders/{orderId}/fulfillment` | Pickup/delivery stages |
| PATCH | `/orders/{orderId}/actual-quantities` | Record actual weight/count |
| GET/POST | `/reviews` | Browse/write reviews |
| GET/PATCH/DELETE | `/reviews/{reviewId}` | Review management |
| GET | `/partners/{partnerId}/reviews` | Partner reviews |

## 7. Example test sequence
1. Register a `partner` and log in.
2. `POST /partners` with `businessName`, `location.street`, and `location.city`.
3. Log in as admin and approve with `PATCH /partners/{partnerId}/approval` and `{ "isApproved": true }`.
4. As partner, create services using `POST /services`.
5. Register/login as `customer`, then book using `POST /orders`.
6. Partner confirms order with `PATCH /orders/{orderId}/status`.
7. Partner assigns an active rider with `PATCH /orders/{orderId}/rider`.
8. Rider progresses through `out_for_pickup` and `picked_up`.
9. Partner records all `actualQuantity` values, then marks `ready_for_delivery`.
10. Rider marks `out_for_delivery` then `delivered`. The overall order status becomes `completed`.

## Notes
- MongoDB ObjectIds are returned as 24-character strings in JSON.
- Passwords are stored as bcrypt hashes; hashes are never returned.
- Order items snapshot service name, type, unit, and price at booking time.
- Every operational update is appended to `statusHistory`.
- `deliveryAddress` defaults to `pickupAddress`.
- This is a student-project starter backend. Review and test all authorization and edge cases before deployment. Use HTTPS, a strong secret, production logging, and disable Flask debug mode before deployment.