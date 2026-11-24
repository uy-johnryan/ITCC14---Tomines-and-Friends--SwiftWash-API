# SwiftWash frontend

A dependency-free HTML, CSS, and JavaScript frontend for the supplied Flask API.

## Run and connect

Serve `dist/` using a static server, for example `python -m http.server 8080 --directory dist`, and open `http://localhost:8080`.

The app starts in **demo mode**, using sample data stored only in this browser. Booking and order changes in demo mode do not reach your backend. Open the app's connection settings to choose live mode and enter your server origin or full API base URL, for example `http://localhost:5000` or `https://api.example.com/api/v1`. The frontend adds `/api/v1` when necessary. No API secret belongs in the frontend.

Live requests use your Flask routes and JWT bearer authentication. The JWT and current user are kept in `sessionStorage`; only the API base URL and selected mode persist in `localStorage`. Demo state is also local. Passwords are sent only for login, registration, or a password change and are not stored by this frontend. A hosted HTTPS frontend needs a reachable HTTPS backend with CORS configured to allow the frontend origin. `localhost` points to the visitor's own computer.

Demo accounts are `customer@swiftwash.demo`, `partner@swiftwash.demo`, `rider@swiftwash.demo`, and `admin@swiftwash.demo`; use any nonempty password. Demo registration is a browser-local preview and does not provide password authentication.

## Required backend serialization fix

The supplied `public()` helper converts only top-level `ObjectId` values. Orders contain nested `items[].serviceId` values, so `jsonify(order_public(order))` will fail with `ObjectId is not JSON serializable`. Replace the serializer with a recursive conversion before testing live order flows:

```python
def json_value(value):
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, dict):
        return {key: json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(item) for item in value]
    return value

def public(doc):
    if not doc:
        return None
    result = dict(doc)
    result["id"] = sid(result.pop("_id", None))
    return json_value(result)
```

Set a fresh `JWT_SECRET_KEY` in the backend environment (the supplied default is public), set `FLASK_DEBUG=false` for deployment, and use your normal production Flask server. The frontend does not modify or deploy the backend.
