import os, math
from datetime import datetime, timezone, timedelta
from functools import wraps

from flask import Flask, request, jsonify
from flask_cors import CORS
from flask_pymongo import PyMongo
from flask_bcrypt import Bcrypt
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required,
    get_jwt_identity, get_jwt
)
from bson import ObjectId
from bson.errors import InvalidId
from dotenv import load_dotenv

load_dotenv()
app = Flask(__name__)
app.config["MONGO_URI"] = os.getenv("MONGO_URI", "mongodb://localhost:27017/SwiftWash")
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET_KEY", "2c04d952967f987d8140fab2f48e23403e5142637d5e96ea7e5fc269a89b50a2")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=12)
CORS(app)
mongo = PyMongo(app)
bcrypt = Bcrypt(app)
jwt = JWTManager(app)

users, partners, services = mongo.db.users, mongo.db.partners, mongo.db.services
orders, reviews = mongo.db.orders, mongo.db.reviews

ROLES = {"customer", "partner", "rider", "admin"}
ORDER_STATUSES = {"pending", "confirmed", "inprogress", "completed", "cancelled"}
STAGES = ["not_started", "out_for_pickup", "picked_up", "ready_for_delivery", "out_for_delivery", "delivered"]
ACTIVE_STATUSES = {"pending", "confirmed", "inprogress"}

def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def oid(value):
    try:
        return ObjectId(value)
    except (InvalidId, TypeError):
        raise ApiError(400, "Invalid ID format.")

def sid(value):
    return str(value) if value is not None else None

def public(doc):
    if not doc: return None
    d = dict(doc)
    d["id"] = sid(d.pop("_id", None))
    for k, v in list(d.items()):
        if isinstance(v, ObjectId): d[k] = sid(v)
    return d

def user_public(doc):
    if not doc: return None
    return {k:v for k,v in public(doc).items() if k != "passwordHash"}

def partner_public(doc):
    return public(doc)

def order_public(doc):
    return public(doc)

class ApiError(Exception):
    def __init__(self, status, message, details=None):
        self.status, self.message, self.details = status, message, details

@app.errorhandler(ApiError)
def api_error(e):
    body = {"status": e.status, "error": {
        400:"Bad Request",401:"Unauthorized",403:"Forbidden",404:"Not Found",
        409:"Conflict",422:"Unprocessable Entity"
    }.get(e.status,"Error"), "message":e.message}
    if e.details is not None: body["details"] = e.details
    return jsonify(body), e.status

@app.errorhandler(InvalidId)
def invalid_id(_): return jsonify(status=400,error="Bad Request",message="Invalid ID format."),400

@app.errorhandler(404)
def not_found(_): return jsonify(status=404,error="Not Found",message="Route not found."),404

@app.errorhandler(400)
def bad_request(_): return jsonify(status=400,error="Bad Request",message="Malformed request."),400

@app.errorhandler(422)
def jwt_or_validation(e):
    return jsonify(status=422,error="Unprocessable Entity",message="Request validation failed."),422

def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict): raise ApiError(400, "Request body must be valid JSON.")
    return data

def require_fields(data, fields):
    missing = [f for f in fields if f not in data]
    if missing: raise ApiError(422, "Validation failed.", [{"field":f,"message":"This field is required."} for f in missing])

def text_field(data, key, minimum=1, maximum=500, required=False):
    value = data.get(key)
    if value is None and not required: return value
    if not isinstance(value, str) or len(value.strip()) < minimum or len(value) > maximum:
        raise ApiError(422, "Validation failed.", [{"field":key,"message":f"Must be {minimum}-{maximum} characters."}])
    return value.strip()

def number(value, field, minimum=0):
    if isinstance(value, bool) or not isinstance(value, (int,float)) or value < minimum:
        raise ApiError(422, "Validation failed.", [{"field":field,"message":f"Must be a number >= {minimum}."}])
    return float(value)

def valid_location(loc, field="address"):
    if not isinstance(loc, dict) or not loc.get("street") or not loc.get("city"):
        raise ApiError(422, "Validation failed.", [{"field":field,"message":"street and city are required."}])
    out = {"street":str(loc["street"]).strip(), "city":str(loc["city"]).strip()}
    for key, low, high in (("latitude",-90,90),("longitude",-180,180)):
        if key in loc and loc[key] is not None:
            n = number(loc[key], f"{field}.{key}", low)
            if n > high: raise ApiError(422,"Validation failed.",[{"field":f"{field}.{key}","message":"Out of range."}])
            out[key] = n
    return out

def parse_date(value, field):
    try:
        dt = datetime.fromisoformat(value.replace("Z","+00:00"))
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        raise ApiError(422,"Validation failed.",[{"field":field,"message":"Must be an ISO date-time."}])

def current_user():
    ident = get_jwt_identity()
    user = users.find_one({"_id":oid(ident)})
    if not user or not user.get("isActive", True): raise ApiError(401,"Account is unavailable.")
    return user

def auth(optional=False):
    def deco(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            if optional:
                from flask_jwt_extended import verify_jwt_in_request
                try: verify_jwt_in_request(optional=True)
                except Exception: raise ApiError(401,"Authentication token is invalid.")
                return fn(*args, **kwargs)
            return fn(*args, **kwargs)
        return wrapper
    return deco

def roles(*allowed):
    def deco(fn):
        @wraps(fn)
        @jwt_required()
        def wrapper(*args, **kwargs):
            u = current_user()
            if u["role"] not in allowed: raise ApiError(403,"You do not have permission to perform this action.")
            return fn(*args, **kwargs)
        return wrapper
    return deco

def actor_ref(u, partner_name=False):
    name = u.get("name","")
    if partner_name and u["role"] == "partner":
        p = partners.find_one({"userId":u["_id"]})
        if p: name = p.get("businessName",name)
    return {"id":sid(u["_id"]),"name":name,"role":u["role"]}

def add_history(order, kind, old, new, actor, note=None):
    order.setdefault("statusHistory",[]).append({
        "kind":kind,"from":str(old) if old is not None else None,
        "to":str(new),"note":note,"updatedBy":actor_ref(actor, True),"timestamp":now()
    })
    order["updatedAt"] = now()

def partner_for_user(user):
    p = partners.find_one({"userId":user["_id"]})
    if not p: raise ApiError(403,"Create a partner profile first.")
    return p

def order_access(order, user):
    if user["role"] == "admin": return
    if user["role"] == "customer" and order["customerId"] == user["_id"]: return
    if user["role"] == "rider" and order.get("riderId") == user["_id"]: return
    if user["role"] == "partner":
        p = partners.find_one({"userId":user["_id"]})
        if p and order["partnerId"] == p["_id"]: return
    raise ApiError(403,"You do not have permission to access this order.")

def page_result(items, page, limit):
    total = len(items)
    start = (page-1)*limit
    return {"data":items[start:start+limit],"meta":{"page":page,"limit":limit,"total":total,"totalPages":math.ceil(total/limit) if total else 0}}

def pagination():
    try:
        page=max(1,int(request.args.get("page",1)))
        limit=min(100,max(1,int(request.args.get("limit",10))))
    except ValueError: raise ApiError(400,"page and limit must be integers.")
    return page,limit

@app.get("/")
def root(): return jsonify(message="SwiftWash API is running.", version="1.1.0", base="/api/v1")

@app.get("/api/v1/health")
def health():
    mongo.db.command("ping")
    return jsonify(status="ok",database="connected",timestamp=now())

# AUTH
@app.post("/api/v1/auth/register")
def register():
    d=body(); require_fields(d,["role","name","email","password"])
    if d["role"] not in {"customer","partner","rider"}: raise ApiError(422,"Validation failed.",[{"field":"role","message":"Role must be customer, partner, or rider."}])
    name=text_field(d,"name",2,100,True); email=text_field(d,"email",5,254,True).lower()
    password=text_field(d,"password",8,128,True)
    if "@" not in email: raise ApiError(422,"Invalid email address.",[{"field":"email","message":"Must be a valid email."}])
    if users.find_one({"email":email}): raise ApiError(409,"An account with this email already exists.")
    doc={"role":d["role"],"name":name,"email":email,"passwordHash":bcrypt.generate_password_hash(password).decode(),
         "isActive":True,"createdAt":now(),"updatedAt":now()}
    if d.get("address") is not None: doc["address"]=valid_location(d["address"])
    result=users.insert_one(doc); doc["_id"]=result.inserted_id
    token=create_access_token(identity=sid(result.inserted_id),additional_claims={"role":doc["role"]})
    return jsonify(token=token,user=user_public(doc)),201

@app.post("/api/v1/auth/login")
def login():
    d=body(); require_fields(d,["email","password"])
    u=users.find_one({"email":str(d["email"]).lower()})
    if not u or not bcrypt.check_password_hash(u["passwordHash"],str(d["password"])): raise ApiError(401,"Email or password is incorrect.")
    if not u.get("isActive",True): raise ApiError(403,"This account has been deactivated.")
    token=create_access_token(identity=sid(u["_id"]),additional_claims={"role":u["role"]})
    return jsonify(token=token,user=user_public(u))

# USERS
@app.get("/api/v1/users/me")
@jwt_required()
def me(): return jsonify(user_public(current_user()))

@app.get("/api/v1/users")
@roles("admin")
def list_users():
    page,limit=pagination(); q={}
    if request.args.get("role"): q["role"]=request.args["role"]
    if request.args.get("isActive") is not None: q["isActive"]=request.args["isActive"].lower()=="true"
    if request.args.get("search"):
        import re
        term=re.escape(request.args["search"]); q["$or"]=[{"name":{"$regex":term,"$options":"i"}},{"email":{"$regex":term,"$options":"i"}}]
    docs=[user_public(x) for x in users.find(q).sort("createdAt",-1)]
    return jsonify(page_result(docs,page,limit))

@app.route("/api/v1/users/<user_id>",methods=["GET","PATCH","DELETE"])
@jwt_required()
def user_detail(user_id):
    u=current_user(); target=users.find_one({"_id":oid(user_id)})
    if not target: raise ApiError(404,"User not found.")
    if request.method=="GET":
        if u["role"]!="admin" and u["_id"]!=target["_id"]: raise ApiError(403,"Not allowed.")
        return jsonify(user_public(target))
    if request.method=="PATCH":
        d=body()
        if not d: raise ApiError(422,"At least one field is required.")
        allowed={"name","address","password","currentPassword","role","isActive"}
        if set(d)-allowed: raise ApiError(422,"Unknown fields are not allowed.",[{"field":x,"message":"Unknown field."} for x in set(d)-allowed])
        admin=u["role"]=="admin"
        if not admin and u["_id"]!=target["_id"]: raise ApiError(403,"Not allowed.")
        if not admin and ({"role","isActive"} & set(d)): raise ApiError(403,"Only admins can change role or active status.")
        updates={}
        if "name" in d: updates["name"]=text_field(d,"name",2,100,True)
        if "address" in d: updates["address"]=valid_location(d["address"])
        if "isActive" in d:
            if not isinstance(d["isActive"],bool): raise ApiError(422,"isActive must be boolean.")
            updates["isActive"]=d["isActive"]
        if "role" in d:
            if d["role"] not in ROLES: raise ApiError(422,"Invalid role.")
            updates["role"]=d["role"]
        if "password" in d:
            if not admin and (not d.get("currentPassword") or not bcrypt.check_password_hash(target["passwordHash"],d["currentPassword"])):
                raise ApiError(401,"Current password is incorrect.")
            updates["passwordHash"]=bcrypt.generate_password_hash(text_field(d,"password",8,128,True)).decode()
        updates["updatedAt"]=now(); users.update_one({"_id":target["_id"]},{"$set":updates})
        return jsonify(user_public(users.find_one({"_id":target["_id"]})))
    if u["role"]!="admin": raise ApiError(403,"Admin only.")
    active=orders.count_documents({"$or":[{"customerId":target["_id"]},{"riderId":target["_id"]}],"status":{"$in":list(ACTIVE_STATUSES)}})
    p=partners.find_one({"userId":target["_id"]})
    if p: active+=orders.count_documents({"partnerId":p["_id"],"status":{"$in":list(ACTIVE_STATUSES)}})
    if active: raise ApiError(409,"User has active orders and cannot be deleted.")
    if p:
        services.delete_many({"partnerId":p["_id"]}); reviews.delete_many({"partnerId":p["_id"]}); partners.delete_one({"_id":p["_id"]})
    users.delete_one({"_id":target["_id"]})
    return "",204

# PARTNERS
@app.route("/api/v1/partners",methods=["GET","POST"])
@auth(optional=True)
def partner_collection():
    if request.method=="POST":
        u=current_user(); 
        if u["role"]!="partner": raise ApiError(403,"Partner role only.")
        if partners.find_one({"userId":u["_id"]}): raise ApiError(409,"Partner profile already exists.")
        d=body(); require_fields(d,["businessName","location"])
        name=text_field(d,"businessName",2,120,True)
        doc={"userId":u["_id"],"businessName":name,"description":text_field(d,"description",0,500) or "",
             "location":valid_location(d["location"]),"rating":0,"ratingCount":0,"isApproved":False,"createdAt":now(),"updatedAt":now()}
        r=partners.insert_one(doc); doc["_id"]=r.inserted_id
        return jsonify(partner_public(doc)),201
    u=None
    from flask_jwt_extended import get_jwt_identity
    if get_jwt_identity(): u=current_user()
    q={}
    if request.args.get("mine","false").lower()=="true":
        if not u or u["role"]!="partner": raise ApiError(403,"Partner role only.")
        q["userId"]=u["_id"]
    elif not u or u["role"]!="admin": q["isApproved"]=True
    elif request.args.get("isApproved") is not None: q["isApproved"]=request.args["isApproved"].lower()=="true"
    if request.args.get("search"): q["businessName"]={"$regex":request.args["search"],"$options":"i"}
    if request.args.get("minRating"):
        try:q["rating"]={"$gte":float(request.args["minRating"])}
        except ValueError: raise ApiError(400,"minRating must be numeric.")
    docs=[partner_public(x) for x in partners.find(q).sort("rating",-1)]
    if all(k in request.args for k in ("lat","lng")):
        lat,lng=float(request.args["lat"]),float(request.args["lng"]); radius=float(request.args.get("radiusKm",5))
        def distance(loc):
            if "latitude" not in loc or "longitude" not in loc:return 1e9
            a,b=math.radians(lat),math.radians(loc["latitude"]); dl=math.radians(loc["longitude"]-lng)
            return 6371*2*math.asin(math.sqrt(math.sin((b-a)/2)**2+math.cos(a)*math.cos(b)*math.sin(dl/2)**2))
        docs=[x for x in docs if distance(x["location"])<=radius]
    page,limit=pagination()
    return jsonify(page_result(docs,page,limit))

@app.route("/api/v1/partners/<partner_id>",methods=["GET","PUT","DELETE"])
@auth(optional=True)
def partner_detail(partner_id):
    p=partners.find_one({"_id":oid(partner_id)})
    if not p: raise ApiError(404,"Partner not found.")
    from flask_jwt_extended import get_jwt_identity
    u=current_user() if get_jwt_identity() else None
    owner=u and u["role"]=="partner" and p["userId"]==u["_id"]
    admin=u and u["role"]=="admin"
    if not p["isApproved"] and not owner and not admin: raise ApiError(404,"Partner not found.")
    if request.method=="GET": return jsonify(partner_public(p))
    if not u or not (owner or admin): raise ApiError(403,"Partner owner or admin only.")
    if request.method=="PUT":
        d=body(); require_fields(d,["businessName","location"])
        updates={"businessName":text_field(d,"businessName",2,120,True),"description":text_field(d,"description",0,500) or "",
                 "location":valid_location(d["location"]),"updatedAt":now()}
        partners.update_one({"_id":p["_id"]},{"$set":updates})
        return jsonify(partner_public(partners.find_one({"_id":p["_id"]})))
    if orders.count_documents({"partnerId":p["_id"],"status":{"$in":list(ACTIVE_STATUSES)}}): raise ApiError(409,"Partner has active orders.")
    services.delete_many({"partnerId":p["_id"]}); reviews.delete_many({"partnerId":p["_id"]}); partners.delete_one({"_id":p["_id"]})
    return "",204

@app.patch("/api/v1/partners/<partner_id>/approval")
@roles("admin")
def partner_approval(partner_id):
    d=body(); require_fields(d,["isApproved"])
    if not isinstance(d["isApproved"],bool): raise ApiError(422,"isApproved must be boolean.")
    p=partners.find_one_and_update({"_id":oid(partner_id)},{"$set":{"isApproved":d["isApproved"],"updatedAt":now()}},return_document=True)
    if not p: raise ApiError(404,"Partner not found.")
    return jsonify(partner_public(p))

# SERVICES
@app.route("/api/v1/services",methods=["GET","POST"])
@auth(optional=True)
def service_collection():
    from flask_jwt_extended import get_jwt_identity
    u=current_user() if get_jwt_identity() else None
    if request.method=="POST":
        if not u or u["role"]!="partner": raise ApiError(403,"Partner role only.")
        p=partner_for_user(u); d=body(); require_fields(d,["type","name","price"])
        if d["type"] not in {"wash","dry","fold"}: raise ApiError(422,"Invalid service type.")
        unit=d.get("unit","kg")
        if unit not in {"kg","piece","load"}: raise ApiError(422,"Invalid unit.")
        price=number(d["price"],"price")
        name=text_field(d,"name",2,100,True)
        if services.find_one({"partnerId":p["_id"],"type":d["type"],"name":name}): raise ApiError(409,"Duplicate service.")
        doc={"partnerId":p["_id"],"type":d["type"],"name":name,"price":price,"unit":unit,"isAvailable":d.get("isAvailable",True),"createdAt":now(),"updatedAt":now()}
        r=services.insert_one(doc); doc["_id"]=r.inserted_id
        return jsonify(public(doc)),201
    q={}
    if request.args.get("partnerId"): q["partnerId"]=oid(request.args["partnerId"])
    if request.args.get("type"): q["type"]=request.args["type"]
    if request.args.get("maxPrice"):
        try:q["price"]={"$lte":float(request.args["maxPrice"])}
        except ValueError: raise ApiError(400,"maxPrice must be numeric.")
    visible=[]
    for svc in services.find(q):
        p=partners.find_one({"_id":svc["partnerId"]})
        own=u and u["role"]=="partner" and p and p["userId"]==u["_id"]
        admin=u and u["role"]=="admin"
        if (p and p.get("isApproved") and svc.get("isAvailable")) or own or admin: visible.append(public(svc))
    page,limit=pagination()
    return jsonify(page_result(visible,page,limit))

@app.route("/api/v1/services/<service_id>",methods=["GET","PUT","DELETE"])
@auth(optional=True)
def service_detail(service_id):
    s=services.find_one({"_id":oid(service_id)})
    if not s: raise ApiError(404,"Service not found.")
    p=partners.find_one({"_id":s["partnerId"]})
    from flask_jwt_extended import get_jwt_identity
    u=current_user() if get_jwt_identity() else None
    own=u and u["role"]=="partner" and p and p["userId"]==u["_id"]
    admin=u and u["role"]=="admin"
    if not ((p and p.get("isApproved") and s.get("isAvailable")) or own or admin): raise ApiError(404,"Service not found.")
    if request.method=="GET": return jsonify(public(s))
    if not u or not (own or admin): raise ApiError(403,"Partner owner or admin only.")
    if request.method=="PUT":
        d=body(); require_fields(d,["type","name","price"])
        if d["type"] not in {"wash","dry","fold"}: raise ApiError(422,"Invalid type.")
        unit=d.get("unit","kg"); available=d.get("isAvailable",True)
        if unit not in {"kg","piece","load"} or not isinstance(available,bool): raise ApiError(422,"Invalid unit or availability.")
        updates={"type":d["type"],"name":text_field(d,"name",2,100,True),"price":number(d["price"],"price"),"unit":unit,"isAvailable":available,"updatedAt":now()}
        services.update_one({"_id":s["_id"]},{"$set":updates})
        return jsonify(public(services.find_one({"_id":s["_id"]})))
    if orders.count_documents({"status":{"$in":list(ACTIVE_STATUSES)},"items.serviceId":s["_id"]}): raise ApiError(409,"Service is used by an active order.")
    services.delete_one({"_id":s["_id"]}); return "",204

@app.get("/api/v1/partners/<partner_id>/services")
@auth(optional=True)
def partner_services(partner_id):
    p=partners.find_one({"_id":oid(partner_id)})
    if not p: raise ApiError(404,"Partner not found.")
    from flask_jwt_extended import get_jwt_identity
    u=current_user() if get_jwt_identity() else None
    own=u and u["role"]=="partner" and p["userId"]==u["_id"]
    if not p["isApproved"] and not own and not (u and u["role"]=="admin"): raise ApiError(404,"Partner not found.")
    q={"partnerId":p["_id"]}
    if not own and not (u and u["role"]=="admin"): q["isAvailable"]=True
    docs=[public(x) for x in services.find(q)]
    page,limit=pagination(); return jsonify(page_result(docs,page,limit))

# RIDERS
@app.get("/api/v1/riders")
@roles("partner","admin")
def list_riders():
    u=current_user()
    if u["role"]=="partner":
        p=partner_for_user(u)
        if not p.get("isApproved"): raise ApiError(403,"Partner profile must be approved.")
    docs=[]
    for rider in users.find({"role":"rider","isActive":True}):
        active=orders.count_documents({"riderId":rider["_id"],"fulfillmentStage":{"$in":["out_for_pickup","out_for_delivery"]}})
        active_count=orders.count_documents({"riderId":rider["_id"],"status":{"$in":list(ACTIVE_STATUSES)}})
        available=active==0
        if request.args.get("available","false").lower()=="true" and not available: continue
        if request.args.get("search") and request.args["search"].lower() not in rider["name"].lower(): continue
        docs.append({"id":sid(rider["_id"]),"name":rider["name"],"isAvailable":available,"activeOrderCount":active_count})
    page,limit=pagination(); return jsonify(page_result(docs,page,limit))

# ORDERS
def build_order_items(partner_id, items):
    if not isinstance(items,list) or not items: raise ApiError(422,"At least one item is required.")
    result=[]; total=0
    for i,item in enumerate(items):
        if not isinstance(item,dict) or not item.get("serviceId") or "estimatedQuantity" not in item:
            raise ApiError(422,"Validation failed.",[{"field":f"items[{i}]","message":"serviceId and estimatedQuantity are required."}])
        svc=services.find_one({"_id":oid(item["serviceId"])})
        if not svc or svc["partnerId"]!=partner_id: raise ApiError(422,"Validation failed.",[{"field":f"items[{i}].serviceId","message":"Service does not belong to the chosen partner."}])
        if not svc.get("isAvailable"): raise ApiError(409,"A selected service is unavailable.")
        qty=number(item["estimatedQuantity"],f"items[{i}].estimatedQuantity",0.5)
        if svc["unit"] in {"piece","load"} and not qty.is_integer(): raise ApiError(422,"piece and load quantities must be whole numbers.")
        subtotal=round(qty*svc["price"],2); total+=subtotal
        result.append({"id":sid(ObjectId()),"serviceId":svc["_id"],"type":svc["type"],"name":svc["name"],"unit":svc["unit"],
            "description":str(item.get("description",""))[:200],"estimatedQuantity":qty,"actualQuantity":None,
            "unitPrice":svc["price"],"subtotal":subtotal})
    return result,round(total,2)

@app.route("/api/v1/orders",methods=["GET","POST"])
@jwt_required()
def order_collection():
    u=current_user()
    if request.method=="POST":
        if u["role"]!="customer": raise ApiError(403,"Customer role only.")
        d=body(); require_fields(d,["partnerId","items","pickupDate","deliveryDate","pickupAddress"])
        p=partners.find_one({"_id":oid(d["partnerId"])})
        if not p: raise ApiError(404,"Partner not found.")
        if not p.get("isApproved"): raise ApiError(409,"Partner is not approved.")
        pickup=parse_date(d["pickupDate"],"pickupDate"); delivery=parse_date(d["deliveryDate"],"deliveryDate")
        if pickup<=datetime.now(timezone.utc) or delivery<=pickup: raise ApiError(422,"Pickup must be in the future and delivery must be later.")
        items,total=build_order_items(p["_id"],d["items"]); t=now()
        order={"customerId":u["_id"],"partnerId":p["_id"],"riderId":None,"items":items,"pickupDate":pickup.isoformat().replace("+00:00","Z"),
            "deliveryDate":delivery.isoformat().replace("+00:00","Z"),"pickupAddress":valid_location(d["pickupAddress"],"pickupAddress"),
            "deliveryAddress":valid_location(d["deliveryAddress"],"deliveryAddress") if d.get("deliveryAddress") else valid_location(d["pickupAddress"],"pickupAddress"),
            "specialInstructions":str(d.get("specialInstructions",""))[:500],"status":"pending","fulfillmentStage":"not_started",
            "estimatedTotal":total,"finalTotal":None,"totalPrice":total,"statusHistory":[],"createdAt":t,"updatedAt":t}
        add_history(order,"status",None,"pending",u,"Order booked.")
        r=orders.insert_one(order); order["_id"]=r.inserted_id
        return jsonify(order_public(order)),201
    q={}
    if u["role"]=="customer": q["customerId"]=u["_id"]
    elif u["role"]=="partner":
        p=partner_for_user(u); q["partnerId"]=p["_id"]
    elif u["role"]=="rider": q["riderId"]=u["_id"]
    if u["role"]=="admin" and request.args.get("partnerId"): q["partnerId"]=oid(request.args["partnerId"])
    if request.args.get("status"): q["status"]=request.args["status"]
    if request.args.get("fulfillmentStage"): q["fulfillmentStage"]=request.args["fulfillmentStage"]
    if request.args.get("riderId") and u["role"] in {"admin","partner"}: q["riderId"]=oid(request.args["riderId"])
    docs=[order_public(x) for x in orders.find(q).sort("createdAt",-1)]
    page,limit=pagination(); return jsonify(page_result(docs,page,limit))

@app.route("/api/v1/orders/<order_id>",methods=["GET","PUT","DELETE"])
@jwt_required()
def order_detail(order_id):
    u=current_user(); o=orders.find_one({"_id":oid(order_id)})
    if not o: raise ApiError(404,"Order not found.")
    order_access(o,u)
    if request.method=="GET": return jsonify(order_public(o))
    if request.method=="PUT":
        if not (u["role"]=="admin" or (u["role"]=="customer" and o["customerId"]==u["_id"])): raise ApiError(403,"Customer owner or admin only.")
        if o["status"]!="pending": raise ApiError(409,"Only pending orders can be edited.")
        d=body(); require_fields(d,["items","pickupDate","deliveryDate","pickupAddress"])
        p=partners.find_one({"_id":o["partnerId"]})
        if not p or not p.get("isApproved"): raise ApiError(409,"Partner is not approved.")
        pickup=parse_date(d["pickupDate"],"pickupDate"); delivery=parse_date(d["deliveryDate"],"deliveryDate")
        if pickup<=datetime.now(timezone.utc) or delivery<=pickup: raise ApiError(422,"Invalid pickup or delivery date.")
        items,total=build_order_items(o["partnerId"],d["items"])
        updates={"items":items,"pickupDate":pickup.isoformat().replace("+00:00","Z"),"deliveryDate":delivery.isoformat().replace("+00:00","Z"),
            "pickupAddress":valid_location(d["pickupAddress"]),"deliveryAddress":valid_location(d["deliveryAddress"]) if d.get("deliveryAddress") else valid_location(d["pickupAddress"]),
            "specialInstructions":str(d.get("specialInstructions",""))[:500],"estimatedTotal":total,"finalTotal":None,"totalPrice":total,"updatedAt":now()}
        orders.update_one({"_id":o["_id"]},{"$set":updates})
        return jsonify(order_public(orders.find_one({"_id":o["_id"]})))
    if u["role"]!="admin" and not (u["role"]=="customer" and o["customerId"]==u["_id"] and o["status"] in {"pending","cancelled"}):
        raise ApiError(409,"This order cannot be deleted.")
    if u["role"]=="admin" and o["status"]=="completed": reviews.delete_many({"orderId":o["_id"]}); recalc_rating(o["partnerId"])
    orders.delete_one({"_id":o["_id"]}); return "",204

@app.patch("/api/v1/orders/<order_id>/status")
@jwt_required()
def order_status(order_id):
    u=current_user(); o=orders.find_one({"_id":oid(order_id)})
    if not o: raise ApiError(404,"Order not found.")
    d=body(); require_fields(d,["status"]); new=d["status"]
    if new not in {"confirmed","cancelled"}: raise ApiError(422,"Only confirmed or cancelled may be set here.")
    is_partner=False
    if u["role"]=="partner":
        p=partner_for_user(u); is_partner=p["_id"]==o["partnerId"]
    is_customer=u["role"]=="customer" and u["_id"]==o["customerId"]
    if u["role"]!="admin" and not (is_partner or is_customer): raise ApiError(403,"Not allowed.")
    old=o["status"]
    allowed=(new=="confirmed" and old=="pending" and (is_partner or u["role"]=="admin")) or (new=="cancelled" and old in {"pending","confirmed"} and (is_partner or is_customer or u["role"]=="admin"))
    if not allowed: raise ApiError(409,"Invalid order status transition.")
    add_history(o,"status",old,new,u,d.get("note"))
    o["status"]=new; orders.replace_one({"_id":o["_id"]},o)
    return jsonify(order_public(o))

@app.patch("/api/v1/orders/<order_id>/rider")
@jwt_required()
def assign_rider(order_id):
    u=current_user(); o=orders.find_one({"_id":oid(order_id)})
    if not o: raise ApiError(404,"Order not found.")
    partner_owner=False
    if u["role"]=="partner":
        p=partner_for_user(u); partner_owner=p["_id"]==o["partnerId"]
    if u["role"]!="admin" and not partner_owner: raise ApiError(403,"Partner owner or admin only.")
    if o["status"] not in {"confirmed","inprogress"}: raise ApiError(409,"Order is not assignable.")
    if o["fulfillmentStage"] in {"out_for_pickup","out_for_delivery"} and u["role"]!="admin": raise ApiError(409,"Rider cannot be reassigned during a trip.")
    d=body(); require_fields(d,["riderId"]); rider=users.find_one({"_id":oid(d["riderId"]),"role":"rider","isActive":True})
    if not rider: raise ApiError(422,"Rider must be an active rider account.")
    busy=orders.find_one({"riderId":rider["_id"],"_id":{"$ne":o["_id"]},"fulfillmentStage":{"$in":["out_for_pickup","out_for_delivery"]}})
    if busy: raise ApiError(409,"Rider is currently on another trip.")
    old=o.get("riderId"); o["riderId"]=rider["_id"]; add_history(o,"rider_assignment",old,rider["_id"],u,d.get("note"))
    orders.replace_one({"_id":o["_id"]},o); return jsonify(order_public(o))

@app.patch("/api/v1/orders/<order_id>/fulfillment")
@jwt_required()
def fulfillment(order_id):
    u=current_user(); o=orders.find_one({"_id":oid(order_id)})
    if not o: raise ApiError(404,"Order not found.")
    d=body(); require_fields(d,["stage"]); new=d["stage"]; old=o["fulfillmentStage"]
    if new not in STAGES or new=="not_started": raise ApiError(422,"Invalid fulfillment stage.")
    idx=STAGES.index(old)
    if idx>=len(STAGES)-1 or STAGES[idx+1]!=new: raise ApiError(409,"Fulfillment stages must advance one step at a time.")
    partner_owner=False
    if u["role"]=="partner":
        p=partner_for_user(u); partner_owner=p["_id"]==o["partnerId"]
    rider_owner=u["role"]=="rider" and o.get("riderId")==u["_id"]
    if u["role"]!="admin" and not (partner_owner or rider_owner): raise ApiError(403,"Not allowed.")
    if new=="out_for_pickup" and not (rider_owner or u["role"]=="admin"): raise ApiError(403,"Assigned rider only.")
    if new=="picked_up" and not (rider_owner or u["role"]=="admin"): raise ApiError(403,"Assigned rider only.")
    if new=="ready_for_delivery":
        if not (partner_owner or u["role"]=="admin"): raise ApiError(403,"Partner only.")
        if any(x.get("actualQuantity") is None for x in o["items"]): raise ApiError(409,"Record actual quantities first.")
    if new in {"out_for_delivery","delivered"} and not (rider_owner or u["role"]=="admin"): raise ApiError(403,"Assigned rider only.")
    if new=="out_for_pickup" and (o["status"]!="confirmed" or not o.get("riderId")): raise ApiError(409,"Order must be confirmed with a rider assigned.")
    add_history(o,"fulfillment",old,new,u,d.get("note")); o["fulfillmentStage"]=new
    if new=="picked_up":
        old_status=o["status"]; o["status"]="inprogress"; add_history(o,"status",old_status,"inprogress",u,"Set automatically when laundry was picked up.")
    if new=="delivered":
        old_status=o["status"]; o["status"]="completed"; add_history(o,"status",old_status,"completed",u,"Set automatically when laundry was delivered.")
    orders.replace_one({"_id":o["_id"]},o); return jsonify(order_public(o))

@app.patch("/api/v1/orders/<order_id>/actual-quantities")
@jwt_required()
def actual_quantities(order_id):
    u=current_user(); o=orders.find_one({"_id":oid(order_id)})
    if not o: raise ApiError(404,"Order not found.")
    partner_owner=False
    if u["role"]=="partner":
        p=partner_for_user(u); partner_owner=p["_id"]==o["partnerId"]
    if u["role"]!="admin" and not partner_owner: raise ApiError(403,"Partner owner or admin only.")
    if o["status"]!="inprogress" or o["fulfillmentStage"]!="picked_up": raise ApiError(409,"Quantities can only be recorded after pickup and before ready for delivery.")
    d=body(); require_fields(d,["items"])
    entries=d["items"]
    if not isinstance(entries,list) or len(entries)!=len(o["items"]): raise ApiError(422,"Exactly one quantity is required for every order item.")
    by_id={x["id"]:x for x in o["items"]}
    if {x.get("itemId") for x in entries}!=set(by_id): raise ApiError(422,"Unknown or missing itemId.")
    old_total=o["totalPrice"]
    for entry in entries:
        item=by_id[entry["itemId"]]; qty=number(entry.get("actualQuantity"),"actualQuantity",0.1)
        if item["unit"] in {"piece","load"} and not qty.is_integer(): raise ApiError(422,"piece and load quantities must be whole numbers.")
        item["actualQuantity"]=qty; item["subtotal"]=round(qty*item["unitPrice"],2)
    final=round(sum(x["subtotal"] for x in o["items"]),2)
    o["finalTotal"]=final; o["totalPrice"]=final
    add_history(o,"weights_recorded",old_total,final,u,d.get("note"))
    orders.replace_one({"_id":o["_id"]},o); return jsonify(order_public(o))

# REVIEWS
def recalc_rating(partner_id):
    vals=[x["rating"] for x in reviews.find({"partnerId":partner_id})]
    partners.update_one({"_id":partner_id},{"$set":{"rating":round(sum(vals)/len(vals),2) if vals else 0,"ratingCount":len(vals)}})

@app.route("/api/v1/reviews",methods=["GET","POST"])
@auth(optional=True)
def review_collection():
    from flask_jwt_extended import get_jwt_identity
    u=current_user() if get_jwt_identity() else None
    if request.method=="POST":
        if not u or u["role"]!="customer": raise ApiError(403,"Customer role only.")
        d=body(); require_fields(d,["orderId","rating"])
        if not isinstance(d["rating"],int) or not 1<=d["rating"]<=5: raise ApiError(422,"rating must be an integer from 1 to 5.")
        o=orders.find_one({"_id":oid(d["orderId"])})
        if not o: raise ApiError(404,"Order not found.")
        if o["customerId"]!=u["_id"]: raise ApiError(403,"You do not own this order.")
        if o["status"]!="completed": raise ApiError(409,"Only completed orders can be reviewed.")
        if reviews.find_one({"orderId":o["_id"]}): raise ApiError(409,"This order has already been reviewed.")
        doc={"customerId":u["_id"],"partnerId":o["partnerId"],"orderId":o["_id"],"rating":d["rating"],"comment":str(d.get("comment",""))[:1000],"createdAt":now(),"updatedAt":now()}
        r=reviews.insert_one(doc); doc["_id"]=r.inserted_id; recalc_rating(o["partnerId"])
        return jsonify(public(doc)),201
    q={}
    for key in ("partnerId","customerId"):
        if request.args.get(key): q[key]=oid(request.args[key])
    if request.args.get("minRating"): q["rating"]={"$gte":int(request.args["minRating"])}
    docs=[]
    for x in reviews.find(q).sort("createdAt",-1):
        p=partners.find_one({"_id":x["partnerId"]})
        if p and (p["isApproved"] or (u and u["role"]=="admin")): docs.append(public(x))
    page,limit=pagination(); return jsonify(page_result(docs,page,limit))

@app.route("/api/v1/reviews/<review_id>",methods=["GET","PATCH","DELETE"])
@auth(optional=True)
def review_detail(review_id):
    r=reviews.find_one({"_id":oid(review_id)})
    if not r: raise ApiError(404,"Review not found.")
    p=partners.find_one({"_id":r["partnerId"]})
    from flask_jwt_extended import get_jwt_identity
    u=current_user() if get_jwt_identity() else None
    if p and not p["isApproved"] and not (u and u["role"]=="admin"): raise ApiError(404,"Review not found.")
    if request.method=="GET": return jsonify(public(r))
    if not u or not (u["role"]=="admin" or (u["role"]=="customer" and u["_id"]==r["customerId"])): raise ApiError(403,"Review author or admin only.")
    if request.method=="PATCH":
        d=body()
        if not d or set(d)-{"rating","comment"}: raise ApiError(422,"Only rating and comment may be updated.")
        updates={}
        if "rating" in d:
            if not isinstance(d["rating"],int) or not 1<=d["rating"]<=5: raise ApiError(422,"rating must be 1 to 5.")
            updates["rating"]=d["rating"]
        if "comment" in d: updates["comment"]=str(d["comment"])[:1000]
        updates["updatedAt"]=now(); reviews.update_one({"_id":r["_id"]},{"$set":updates}); recalc_rating(r["partnerId"])
        return jsonify(public(reviews.find_one({"_id":r["_id"]})))
    reviews.delete_one({"_id":r["_id"]}); recalc_rating(r["partnerId"]); return "",204

@app.get("/api/v1/partners/<partner_id>/reviews")
@auth(optional=True)
def partner_reviews(partner_id):
    p=partners.find_one({"_id":oid(partner_id)})
    if not p: raise ApiError(404,"Partner not found.")
    from flask_jwt_extended import get_jwt_identity
    u=current_user() if get_jwt_identity() else None
    if not p["isApproved"] and not (u and u["role"]=="admin"): raise ApiError(404,"Partner not found.")
    docs=[public(x) for x in reviews.find({"partnerId":p["_id"]}).sort("createdAt",-1)]
    page,limit=pagination(); return jsonify(page_result(docs,page,limit))


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT",5000)), debug=os.getenv("FLASK_DEBUG","true").lower()=="true")
