import os
from dotenv import load_dotenv
from pymongo import MongoClient

load_dotenv()

MONGO_URL = os.getenv("MONGO_DB_URL") or os.getenv("MONGO_URL")
if not MONGO_URL:
    raise RuntimeError("Set MONGO_DB_URL or MONGO_URL in AccuEntry_Verify/.env")

client = MongoClient(MONGO_URL)
db = client["kyc_system"]

pan_db = db["pan_records"]
aadhaar_db = db["aadhaar_records"]
kyc_db = db["kyc_records"]
