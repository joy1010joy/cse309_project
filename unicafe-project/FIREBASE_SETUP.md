# Firebase Setup Guide - UniCafe Project

## ✅ Status: Firebase Connected & Authenticated

Your Firebase project is now fully configured and tested with real credentials!

### 🎯 What's Working

- ✅ **Firebase Firestore Database**: Connected and tested
- ✅ **Service Account Authentication**: Real credentials loaded
- ✅ **Backend API**: Ready with authentication endpoints
- ✅ **JWT Token System**: Secure user sessions
- ✅ **Database Seeding**: Admin user and menu items ready

### 📊 Verified Connection

Firebase connection test successful:
```
✅ Firebase app initialized
✅ Firestore client created
✅ Test document written to test_connection/check
✅ Firebase connection successful!
```

### 🔐 Authentication Endpoints

All API endpoints are ready and protected:

#### Public Endpoints
- `POST /api/auth/register` - User registration
- `POST /api/auth/login` - User login
- `GET /api/menu` - View menu items

#### Protected Endpoints (require JWT token)
- `POST /api/orders` - Create orders
- `GET /api/user/profile` - User profile
- `GET /api/orders/history` - Order history

#### Admin Endpoints
- `POST /api/menu` - Add menu items
- `PUT /api/menu/{id}` - Update menu items
- `DELETE /api/menu/{id}` - Delete menu items
- `GET /api/admin/analytics` - View analytics

### 🚀 Quick Start

1. **Start the API Server:**
   ```bash
   python main.py
   ```
   Server will run on: `http://localhost:8000`

2. **Test Authentication:**
   ```bash
   # Login as admin
   curl -X POST http://localhost:8000/api/auth/login \
     -H "Content-Type: application/json" \
     -d '{"email":"admin@unicafe.com","password":"admin123"}'
   
   # Response will include JWT token
   ```

3. **Seed Initial Data:**
   - 10 menu items (Coffee, Snacks, Wraps, Desserts)
   - Admin user created automatically
   - Test collection for verification

### 📁 Project Structure

```
unicafe-project/
├── main.py                    # FastAPI backend
├── serviceAccountKey.json     # Firebase credentials ✅
├── .env                       # Environment variables
├── requirements.txt           # Python dependencies
├── test_firebase.py           # Firebase connection test
├── FIREBASE_SETUP.md         # This file
└── static/                    # Frontend files
    └── index.html
```

### 🔑 Default Credentials

**Admin Account:**
- Email: `admin@unicafe.com`
- Password: `admin123`

### 🌐 Frontend Integration

Your frontend needs to:
1. Call login endpoint to get JWT token
2. Include token in `Authorization: Bearer <token>` header
3. Use token for authenticated requests

Example:
```javascript
// Get token
const response = await fetch('/api/auth/login', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    email: 'user@example.com',
    password: 'password'
  })
});

const { access_token } = await response.json();

// Use token for protected endpoints
const ordersResponse = await fetch('/api/orders', {
  headers: { 'Authorization': `Bearer ${access_token}` }
});
```

### 🛠️ Environment Configuration

`.env` file contains:
```
GEMINI_API_KEY=<your-key>
FIREBASE_CREDENTIALS_PATH=./serviceAccountKey.json
```

### 📝 Notes

- Firebase credentials are stored in `serviceAccountKey.json`
- Never commit this file to version control (check .gitignore)
- JWT tokens expire after 24 hours
- All passwords are hashed with bcrypt
- Firestore uses collections: `users`, `menu_items`, `orders`

### ✨ Features Ready

1. **User Management**
   - Registration with email/password
   - Secure password hashing
   - JWT-based sessions

2. **Menu Management**
   - CRUD operations for menu items
   - Category filtering
   - Availability status

3. **Order System**
   - Create orders with multiple items
   - Order status tracking
   - Order history for users

4. **AI Assistant**
   - Gemini AI integration
   - Menu recommendations
   - Admin analytics

### 🔍 Testing

Run the test file to verify everything:
```bash
python test_firebase.py
```

Expected output:
```
✅ Firebase connection successful!
📄 Read back: {'message': 'Hello from UniCafe!', ...}
```

---

**Setup completed on**: April 26, 2026
**Project**: UniCafe - University Cafe Management System
