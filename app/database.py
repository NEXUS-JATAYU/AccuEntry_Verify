import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URL = os.getenv("MONGO_DB_URL") or os.getenv("MONGO_URL")

if not MONGO_URL:
    print("WARNING: MONGO_DB_URL/MONGO_URL is not set; using local MongoDB fallback for startup.")
    MONGO_URL = "mongodb://127.0.0.1:27017"

client = MongoClient(MONGO_URL, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
db = client["kyc_system"]

pan_db = db["pan_records"]
aadhaar_db = db["aadhaar_records"]
kyc_db = db["kyc_records"]
