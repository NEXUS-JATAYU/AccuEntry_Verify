import os

from pymongo import MongoClient

MONGO_URL = os.getenv("MONGO_URL")

client = MongoClient(MONGO_URL)

db = client["kyc_system"]

pan_db = db["pan_records"]
aadhaar_db = db["aadhaar_records"]
kyc_db = db["kyc_records"]