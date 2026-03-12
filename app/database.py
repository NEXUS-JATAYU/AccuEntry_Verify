from pymongo import MongoClient

MONGO_URL = "mongodb+srv://kycadmin:Omkar%4007@cluster0.mgebaeu.mongodb.net/?appName=Cluster0"

client = MongoClient(MONGO_URL)

db = client["kyc_system"]

pan_db = db["pan_records"]
aadhaar_db = db["aadhaar_records"]
kyc_db = db["kyc_records"]