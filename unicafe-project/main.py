import os
import uuid
from datetime import datetime, timedelta
from typing import List, Optional
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

load_dotenv()

# Check if Firebase app is already initialized
try:
    firebase_admin.get_app()
    # Firebase app already exists, skip initialization
    pass
except ValueError:
    # Firebase app not initialized, proceed with initialization
    cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
    if cred_path:
        cred = credentials.Certificate(cred_path)   # serviceAccountKey.json ফাইল ব্যবহার করে
        firebase_admin.initialize_app(cred)
    else:
        cred = credentials.ApplicationDefault()
        firebase_admin.initialize_app(cred)

db = firestore.client()

import google.generativeai as genai
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from passlib.context import CryptContext
import jwt
from jwt.exceptions import InvalidTokenError

SECRET_KEY = "your-secret-key-change-in-production"
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    gemini_model = genai.GenerativeModel('gemini-1.5-flash')
else:
    gemini_model = None

pwd_context = CryptContext(schemes=["pbkdf2_sha256"], deprecated="auto")
security = HTTPBearer()

class UserCreate(BaseModel):
    email: str
    full_name: str
    password: str

class UserLogin(BaseModel):
    email: str
    password: str

class Token(BaseModel):
    access_token: str
    token_type: str
    is_admin: bool

class MenuItemCreate(BaseModel):
    name: str
    description: str
    price: float
    category: str

class MenuItemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    category: Optional[str] = None
    is_available: Optional[bool] = None

class OrderItemCreate(BaseModel):
    menu_item_id: str
    quantity: int

class OrderCreate(BaseModel):
    items: List[OrderItemCreate]
    pickup_time: Optional[str] = None

class OrderStatusUpdate(BaseModel):
    status: str

class AIAssistantRequest(BaseModel):
    message: str

def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

def get_password_hash(password):
    return pwd_context.hash(password)

def create_access_token(data: dict):
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        user_id: str = payload.get("sub")
        if user_id is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")
    user_doc = db.collection("users").document(user_id).get()
    if not user_doc.exists:
        raise HTTPException(status_code=401, detail="User not found")
    user_data = user_doc.to_dict()
    user_data["id"] = user_doc.id
    return user_data

async def get_current_admin(current_user: dict = Depends(get_current_user)):
    if not current_user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="Admin access required")
    return current_user

def get_ai_response(prompt: str) -> str:
    if not gemini_model:
        return "AI service is not configured."
    try:
        response = gemini_model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"AI error: {str(e)}"

async def generate_ai_recommendations(user_id: Optional[str] = None):
    menu_docs = db.collection("menu_items").where("is_available", "==", True).stream()
    menu_items = []
    for doc in menu_docs:
        item = doc.to_dict()
        item["id"] = doc.id
        menu_items.append(item)
    menu_text = "\n".join([f"- {item['name']}: ${item['price']} ({item['category']})" for item in menu_items])
    user_history = ""
    if user_id:
        orders_ref = db.collection("orders").where("user_id", "==", user_id).stream()
        ordered_names = set()
        for order_doc in orders_ref:
            order = order_doc.to_dict()
            for item in order.get("items", []):
                ordered_names.add(item.get("name", ""))
        if ordered_names:
            user_history = f"User's previous orders include: {', '.join(ordered_names)}."
    prompt = f"""
    You are an AI cafe assistant for UniCafe. Based on the following menu and user history, recommend 3-5 items the user might like.
    Menu:
    {menu_text}
    {user_history}
    Provide a short, friendly recommendation explaining why each item is a good choice. Keep it concise (max 150 words).
    """
    return get_ai_response(prompt)

async def generate_admin_insights():
    week_ago = datetime.utcnow() - timedelta(days=7)
    orders_ref = db.collection("orders").where("order_date", ">=", week_ago).stream()
    total_orders = 0
    total_revenue = 0.0
    item_sales = {}
    for doc in orders_ref:
        order = doc.to_dict()
        total_orders += 1
        total_revenue += order.get("total_amount", 0)
        for item in order.get("items", []):
            name = item.get("name")
            qty = item.get("quantity", 0)
            item_sales[name] = item_sales.get(name, 0) + qty
    top_items = sorted(item_sales.items(), key=lambda x: x[1], reverse=True)[:5]
    top_items_text = ", ".join([f"{name} ({qty} sold)" for name, qty in top_items])
    prompt = f"""
    You are an AI analytics assistant for UniCafe. Analyze the following cafe data for the last 7 days and provide insights and recommendations.
    Data:
    - Total Orders: {total_orders}
    - Total Revenue: ${total_revenue:.2f}
    - Top Selling Items: {top_items_text}
    Provide actionable insights about menu popularity, suggestions for promotions, and operational improvements. Keep response under 200 words.
    """
    return get_ai_response(prompt)

async def ai_chat_assistant(message: str):
    menu_docs = db.collection("menu_items").where("is_available", "==", True).limit(10).stream()
    menu_summary = ""
    for doc in menu_docs:
        item = doc.to_dict()
        menu_summary += f"{item['name']} (${item['price']}): {item['description'][:50]}\n"
    prompt = f"""
    You are UniCafe's AI ordering assistant. Help users with menu suggestions, answer questions about food items, and provide friendly service.
    Current Menu (sample):
    {menu_summary}
    User question: {message}
    Respond helpfully, suggest items if they ask for recommendations, and keep tone warm and professional.
    """
    return get_ai_response(prompt)

app = FastAPI(title="UniCafe API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

def seed_initial_data():
    admin_query = db.collection("users").where("email", "==", "admin@unicafe.com").limit(1).stream()
    if not any(admin_query):
        admin_id = str(uuid.uuid4())
        db.collection("users").document(admin_id).set({
            "email": "admin@unicafe.com",
            "full_name": "Cafe Admin",
            "hashed_password": get_password_hash("admin123"),
            "is_admin": True,
            "created_at": datetime.utcnow()
        })
    menu_count = len(list(db.collection("menu_items").limit(1).stream()))
    if menu_count == 0:
        sample_items = [
            {"name": "Classic Latte", "description": "Smooth espresso with steamed milk", "price": 3.50, "category": "Coffee", "is_available": True},
            {"name": "Cappuccino", "description": "Espresso with foamy milk", "price": 3.50, "category": "Coffee", "is_available": True},
            {"name": "Iced Americano", "description": "Refreshing cold espresso", "price": 3.00, "category": "Coffee", "is_available": True},
            {"name": "Chicken Sandwich", "description": "Grilled chicken with lettuce and mayo", "price": 5.50, "category": "Snacks", "is_available": True},
            {"name": "Vegan Wrap", "description": "Hummus, fresh veggies in tortilla", "price": 5.00, "category": "Wraps", "is_available": True},
            {"name": "Cheese Toast", "description": "Toasted bread with melted cheese", "price": 2.50, "category": "Snacks", "is_available": True},
            {"name": "Blueberry Muffin", "description": "Soft muffin with fresh blueberries", "price": 2.00, "category": "Desserts", "is_available": True},
            {"name": "Chocolate Croissant", "description": "Flaky pastry with chocolate filling", "price": 2.50, "category": "Desserts", "is_available": True},
            {"name": "Matcha Latte", "description": "Premium matcha with oat milk", "price": 4.00, "category": "Coffee", "is_available": True},
            {"name": "Turkey Club Wrap", "description": "Turkey, bacon, avocado wrap", "price": 6.00, "category": "Wraps", "is_available": True},
        ]
        for item in sample_items:
            doc_id = str(uuid.uuid4())
            db.collection("menu_items").document(doc_id).set(item)

seed_initial_data()

@app.post("/api/auth/register", response_model=Token)
async def register(user_data: UserCreate):
    existing = db.collection("users").where("email", "==", user_data.email).limit(1).stream()
    if any(existing):
        raise HTTPException(status_code=400, detail="Email already registered")
    user_id = str(uuid.uuid4())
    user_doc = {
        "email": user_data.email,
        "full_name": user_data.full_name,
        "hashed_password": get_password_hash(user_data.password),
        "is_admin": False,
        "created_at": datetime.utcnow()
    }
    db.collection("users").document(user_id).set(user_doc)
    token = create_access_token({"sub": user_id, "is_admin": False})
    return {"access_token": token, "token_type": "bearer", "is_admin": False}

@app.post("/api/auth/login", response_model=Token)
async def login(user_data: UserLogin):
    users_ref = db.collection("users").where("email", "==", user_data.email).limit(1).stream()
    user_doc = None
    for doc in users_ref:
        user_doc = doc
        break
    if not user_doc:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    user_data_dict = user_doc.to_dict()
    if not verify_password(user_data.password, user_data_dict["hashed_password"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_access_token({"sub": user_doc.id, "is_admin": user_data_dict.get("is_admin", False)})
    return {"access_token": token, "token_type": "bearer", "is_admin": user_data_dict.get("is_admin", False)}

@app.get("/api/menu")
async def get_menu(category: Optional[str] = None):
    query = db.collection("menu_items").where("is_available", "==", True)
    if category:
        query = query.where("category", "==", category)
    docs = query.stream()
    items = []
    for doc in docs:
        item = doc.to_dict()
        item["id"] = doc.id
        items.append(item)
    return items

@app.post("/api/orders")
async def create_order(order_data: OrderCreate, current_user: dict = Depends(get_current_user)):
    total = 0.0
    order_items = []
    for item in order_data.items:
        menu_doc = db.collection("menu_items").document(item.menu_item_id).get()
        if not menu_doc.exists:
            raise HTTPException(status_code=400, detail=f"Item {item.menu_item_id} not found")
        menu_item = menu_doc.to_dict()
        if not menu_item.get("is_available", True):
            raise HTTPException(status_code=400, detail=f"Item {menu_item['name']} not available")
        item_price = menu_item["price"]
        total += item_price * item.quantity
        order_items.append({
            "menu_item_id": item.menu_item_id,
            "name": menu_item["name"],
            "quantity": item.quantity,
            "price": item_price
        })
    pickup_dt = None
    if order_data.pickup_time:
        try:
            pickup_dt = datetime.fromisoformat(order_data.pickup_time.replace('Z', '+00:00'))
        except:
            pickup_dt = datetime.utcnow() + timedelta(minutes=30)
    else:
        pickup_dt = datetime.utcnow() + timedelta(minutes=30)
    order_id = str(uuid.uuid4())
    order = {
        "user_id": current_user["id"],
        "order_date": datetime.utcnow(),
        "status": "pending",
        "total_amount": total,
        "pickup_time": pickup_dt,
        "items": order_items
    }
    db.collection("orders").document(order_id).set(order)
    return {"order_id": order_id, "total": total, "status": "pending"}

@app.get("/api/orders")
async def get_my_orders(current_user: dict = Depends(get_current_user)):
    orders_ref = db.collection("orders").where("user_id", "==", current_user["id"]).order_by("order_date", direction=firestore.Query.DESCENDING).stream()
    result = []
    for doc in orders_ref:
        order = doc.to_dict()
        result.append({
            "id": doc.id,
            "order_date": order["order_date"].isoformat(),
            "status": order["status"],
            "total_amount": order["total_amount"],
            "pickup_time": order["pickup_time"].isoformat() if order["pickup_time"] else None,
            "items": order.get("items", [])
        })
    return result

@app.get("/api/admin/orders")
async def admin_get_orders(current_admin: dict = Depends(get_current_admin)):
    orders_ref = db.collection("orders").order_by("order_date", direction=firestore.Query.DESCENDING).stream()
    result = []
    for doc in orders_ref:
        order = doc.to_dict()
        user_doc = db.collection("users").document(order["user_id"]).get()
        user_name = user_doc.to_dict().get("full_name", "Unknown") if user_doc.exists else "Unknown"
        user_email = user_doc.to_dict().get("email", "") if user_doc.exists else ""
        result.append({
            "id": doc.id,
            "user_email": user_email,
            "user_name": user_name,
            "order_date": order["order_date"].isoformat(),
            "status": order["status"],
            "total_amount": order["total_amount"],
            "pickup_time": order["pickup_time"].isoformat() if order["pickup_time"] else None,
            "items": order.get("items", [])
        })
    return result

@app.put("/api/admin/orders/{order_id}/status")
async def admin_update_order_status(order_id: str, status_update: OrderStatusUpdate, current_admin: dict = Depends(get_current_admin)):
    order_ref = db.collection("orders").document(order_id)
    if not order_ref.get().exists:
        raise HTTPException(status_code=404, detail="Order not found")
    order_ref.update({"status": status_update.status})
    return {"message": "Status updated", "status": status_update.status}

@app.get("/api/admin/stats")
async def admin_get_stats(current_admin: dict = Depends(get_current_admin)):
    all_orders = list(db.collection("orders").stream())
    total_orders = len(all_orders)
    total_revenue = sum(order.to_dict().get("total_amount", 0) for order in all_orders)
    pending_orders = sum(1 for order in all_orders if order.to_dict().get("status") == "pending")
    item_qty = {}
    for order_doc in all_orders:
        for item in order_doc.to_dict().get("items", []):
            name = item.get("name")
            qty = item.get("quantity", 0)
            item_qty[name] = item_qty.get(name, 0) + qty
    popular = sorted(item_qty.items(), key=lambda x: x[1], reverse=True)[:5]
    popular_items = [{"name": name, "quantity": qty} for name, qty in popular]
    return {
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "pending_orders": pending_orders,
        "popular_items": popular_items
    }

@app.get("/api/ai/recommend")
async def ai_recommend(current_user: dict = Depends(get_current_user)):
    recommendations = await generate_ai_recommendations(current_user["id"])
    return {"recommendations": recommendations}

@app.post("/api/ai/assistant")
async def ai_assistant(request: AIAssistantRequest):
    response = await ai_chat_assistant(request.message)
    return {"response": response}

@app.get("/api/ai/admin-insights")
async def admin_insights(current_admin: dict = Depends(get_current_admin)):
    insights = await generate_admin_insights()
    return {"insights": insights}

# Menu Management Endpoints (Admin Only)
@app.post("/api/admin/menu")
async def admin_create_menu_item(item: MenuItemCreate, current_admin: dict = Depends(get_current_admin)):
    item_id = str(uuid.uuid4())
    item_data = {
        "name": item.name,
        "description": item.description,
        "price": item.price,
        "category": item.category,
        "is_available": True,
        "created_at": datetime.utcnow()
    }
    db.collection("menu_items").document(item_id).set(item_data)
    return {"message": "Menu item created", "item_id": item_id}

@app.put("/api/admin/menu/{item_id}")
async def admin_update_menu_item(item_id: str, item: MenuItemUpdate, current_admin: dict = Depends(get_current_admin)):
    item_ref = db.collection("menu_items").document(item_id)
    if not item_ref.get().exists:
        raise HTTPException(status_code=404, detail="Menu item not found")

    update_data = {}
    if item.name is not None:
        update_data["name"] = item.name
    if item.description is not None:
        update_data["description"] = item.description
    if item.price is not None:
        update_data["price"] = item.price
    if item.category is not None:
        update_data["category"] = item.category
    if item.is_available is not None:
        update_data["is_available"] = item.is_available

    if update_data:
        item_ref.update(update_data)

    return {"message": "Menu item updated"}

@app.delete("/api/admin/menu/{item_id}")
async def admin_delete_menu_item(item_id: str, current_admin: dict = Depends(get_current_admin)):
    item_ref = db.collection("menu_items").document(item_id)
    if not item_ref.get().exists:
        raise HTTPException(status_code=404, detail="Menu item not found")

    item_ref.delete()
    return {"message": "Menu item deleted"}

# User Profile Management
@app.get("/api/profile")
async def get_user_profile(current_user: dict = Depends(get_current_user)):
    return {
        "id": current_user["id"],
        "email": current_user["email"],
        "full_name": current_user["full_name"],
        "is_admin": current_user.get("is_admin", False),
        "created_at": current_user.get("created_at", datetime.utcnow()).isoformat()
    }

@app.put("/api/profile")
async def update_user_profile(profile_data: dict, current_user: dict = Depends(get_current_user)):
    allowed_fields = ["full_name", "email"]
    update_data = {}

    for field in allowed_fields:
        if field in profile_data:
            update_data[field] = profile_data[field]

    if update_data:
        # Check if email is already taken by another user
        if "email" in update_data:
            existing = db.collection("users").where("email", "==", update_data["email"]).stream()
            for doc in existing:
                if doc.id != current_user["id"]:
                    raise HTTPException(status_code=400, detail="Email already in use")

        db.collection("users").document(current_user["id"]).update(update_data)

    return {"message": "Profile updated"}

# Order Cancellation
@app.put("/api/orders/{order_id}/cancel")
async def cancel_order(order_id: str, current_user: dict = Depends(get_current_user)):
    order_ref = db.collection("orders").document(order_id)
    order_doc = order_ref.get()

    if not order_doc.exists:
        raise HTTPException(status_code=404, detail="Order not found")

    order_data = order_doc.to_dict()

    # Check if user owns this order or is admin
    if order_data["user_id"] != current_user["id"] and not current_user.get("is_admin", False):
        raise HTTPException(status_code=403, detail="Not authorized to cancel this order")

    # Only allow cancellation of pending orders
    if order_data.get("status") != "pending":
        raise HTTPException(status_code=400, detail="Only pending orders can be cancelled")

    order_ref.update({"status": "cancelled"})
    return {"message": "Order cancelled successfully"}

# Advanced Analytics
@app.get("/api/admin/analytics")
async def admin_get_analytics(current_admin: dict = Depends(get_current_admin)):
    # Get date range (last 30 days)
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)

    # Get all orders in the last 30 days
    orders_ref = db.collection("orders").where("order_date", ">=", thirty_days_ago).stream()
    orders = [doc.to_dict() for doc in orders_ref]

    # Calculate metrics
    total_orders = len(orders)
    total_revenue = sum(order.get("total_amount", 0) for order in orders)
    completed_orders = sum(1 for order in orders if order.get("status") == "completed")
    cancelled_orders = sum(1 for order in orders if order.get("status") == "cancelled")

    # Daily revenue trend
    daily_revenue = {}
    for order in orders:
        date = order["order_date"].date().isoformat()
        daily_revenue[date] = daily_revenue.get(date, 0) + order.get("total_amount", 0)

    # Popular items
    item_sales = {}
    for order in orders:
        for item in order.get("items", []):
            name = item.get("name")
            qty = item.get("quantity", 0)
            item_sales[name] = item_sales.get(name, 0) + qty

    popular_items = sorted(item_sales.items(), key=lambda x: x[1], reverse=True)[:10]

    # Peak hours
    hourly_orders = {}
    for order in orders:
        hour = order["order_date"].hour
        hourly_orders[hour] = hourly_orders.get(hour, 0) + 1

    peak_hour = max(hourly_orders.items(), key=lambda x: x[1]) if hourly_orders else (12, 0)

    return {
        "total_orders": total_orders,
        "total_revenue": total_revenue,
        "completed_orders": completed_orders,
        "cancelled_orders": cancelled_orders,
        "completion_rate": (completed_orders / total_orders * 100) if total_orders > 0 else 0,
        "daily_revenue": daily_revenue,
        "popular_items": [{"name": name, "quantity": qty} for name, qty in popular_items],
        "peak_hour": f"{peak_hour[0]:02d}:00",
        "avg_order_value": total_revenue / total_orders if total_orders > 0 else 0
    }

# Inventory Management (Simple stock tracking)
class InventoryUpdate(BaseModel):
    item_id: str
    stock_quantity: int

@app.put("/api/admin/inventory")
async def update_inventory(inventory: InventoryUpdate, current_admin: dict = Depends(get_current_admin)):
    item_ref = db.collection("menu_items").document(inventory.item_id)
    if not item_ref.get().exists:
        raise HTTPException(status_code=404, detail="Menu item not found")

    item_ref.update({
        "stock_quantity": inventory.stock_quantity,
        "is_available": inventory.stock_quantity > 0
    })

    return {"message": "Inventory updated"}

@app.get("/api/admin/inventory")
async def get_inventory(current_admin: dict = Depends(get_current_admin)):
    items_ref = db.collection("menu_items").stream()
    inventory = []

    for doc in items_ref:
        item = doc.to_dict()
        inventory.append({
            "id": doc.id,
            "name": item["name"],
            "category": item["category"],
            "stock_quantity": item.get("stock_quantity", 0),
            "is_available": item.get("is_available", True)
        })

    return inventory

# Customer Feedback System
class FeedbackCreate(BaseModel):
    order_id: str
    rating: int  # 1-5
    comment: Optional[str] = None

@app.post("/api/feedback")
async def submit_feedback(feedback: FeedbackCreate, current_user: dict = Depends(get_current_user)):
    # Verify order belongs to user
    order_ref = db.collection("orders").document(feedback.order_id)
    order_doc = order_ref.get()

    if not order_doc.exists:
        raise HTTPException(status_code=404, detail="Order not found")

    order_data = order_doc.to_dict()
    if order_data["user_id"] != current_user["id"]:
        raise HTTPException(status_code=403, detail="Not authorized to provide feedback for this order")

    # Check rating range
    if feedback.rating < 1 or feedback.rating > 5:
        raise HTTPException(status_code=400, detail="Rating must be between 1 and 5")

    feedback_id = str(uuid.uuid4())
    feedback_data = {
        "id": feedback_id,
        "order_id": feedback.order_id,
        "user_id": current_user["id"],
        "rating": feedback.rating,
        "comment": feedback.comment,
        "created_at": datetime.utcnow()
    }

    db.collection("feedback").document(feedback_id).set(feedback_data)
    return {"message": "Feedback submitted successfully"}

@app.get("/api/admin/feedback")
async def get_feedback(current_admin: dict = Depends(get_current_admin)):
    feedback_ref = db.collection("feedback").order_by("created_at", direction=firestore.Query.DESCENDING).stream()
    feedback_list = []

    for doc in feedback_ref:
        feedback = doc.to_dict()
        user_doc = db.collection("users").document(feedback["user_id"]).get()
        user_name = user_doc.to_dict().get("full_name", "Unknown") if user_doc.exists else "Unknown"

        feedback_list.append({
            "id": doc.id,
            "user_name": user_name,
            "rating": feedback["rating"],
            "comment": feedback.get("comment"),
            "created_at": feedback["created_at"].isoformat()
        })

    return feedback_list

# Notification System (Simple in-app notifications)
@app.get("/api/notifications")
async def get_notifications(current_user: dict = Depends(get_current_user)):
    # Get recent orders and create notifications
    notifications = []

    # Check for ready orders
    orders_ref = db.collection("orders").where("user_id", "==", current_user["id"]).where("status", "==", "ready").stream()
    for doc in orders_ref:
        order = doc.to_dict()
        notifications.append({
            "id": f"ready_{doc.id}",
            "type": "order_ready",
            "title": "Your order is ready!",
            "message": f"Order #{doc.id[:8]} is ready for pickup",
            "created_at": order["order_date"].isoformat()
        })

    # Check for completed orders (for feedback)
    completed_orders = db.collection("orders").where("user_id", "==", current_user["id"]).where("status", "==", "completed").stream()
    for doc in completed_orders:
        order = doc.to_dict()
        # Check if feedback already given
        feedback_exists = db.collection("feedback").where("order_id", "==", doc.id).limit(1).stream()
        if not any(feedback_exists):
            notifications.append({
                "id": f"feedback_{doc.id}",
                "type": "feedback_request",
                "title": "How was your experience?",
                "message": f"Help us improve by rating your recent order #{doc.id[:8]}",
                "created_at": order["order_date"].isoformat()
            })

    return notifications

app.mount("/", StaticFiles(directory="static", html=True), name="static")