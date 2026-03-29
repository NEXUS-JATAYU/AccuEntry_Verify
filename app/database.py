import os
from dotenv import load_dotenv

load_dotenv()

from pymongo import MongoClient

MONGO_URL = os.getenv("MONGO_DB_URL")

client = MongoClient(MONGO_URL)

db = client["kyc_system"]

pan_db = db["pan_records"]
aadhaar_db = db["aadhaar_records"]
kyc_db = db["kyc_records"]