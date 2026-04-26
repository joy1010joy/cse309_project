# test_firebase.py
import os
import sys
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

print("Starting Firebase test...", file=sys.stderr)

load_dotenv()

cred_path = os.getenv("FIREBASE_CREDENTIALS_PATH")
print(f"Firebase credentials path: {cred_path}", file=sys.stderr)

try:
    if not cred_path:
        print("Using ApplicationDefault credentials...", file=sys.stderr)
        cred = credentials.ApplicationDefault()
    else:
        print(f"Using certificate from: {cred_path}", file=sys.stderr)
        cred = credentials.Certificate(cred_path)
    
    # Check if app already initialized
    try:
        firebase_admin.get_app()
        print("Firebase app already initialized", file=sys.stderr)
    except ValueError:
        firebase_admin.initialize_app(cred)
        print("Firebase app initialized", file=sys.stderr)
    
    db = firestore.client()
    print("Firestore client created", file=sys.stderr)
    
    doc_ref = db.collection("test_connection").document("check")
    doc_ref.set({"message": "Hello from UniCafe!", "timestamp": firestore.SERVER_TIMESTAMP})
    
    print("✅ Test document written to test_connection/check")
    
    read_back = doc_ref.get()
    print(f"📄 Read back: {read_back.to_dict()}")
    print("✅ Firebase connection successful!")
    
except Exception as e:
    print(f"❌ Error: {e}", file=sys.stderr)
    import traceback
    traceback.print_exc()
    sys.exit(1)