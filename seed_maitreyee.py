"""Insert MAITREYEE PURANIK test records into pan_records and aadhaar_records."""
from app.database import pan_db, aadhaar_db

# PAN record
pan_db.update_one(
    {"pan_number": "ABCDE1234F", "name": "MAITREYEE PURANIK"},
    {"$set": {"pan_number": "ABCDE1234F", "name": "MAITREYEE PURANIK", "dob": "2004-05-24"}},
    upsert=True,
)
print("PAN record inserted/updated for MAITREYEE PURANIK (ABCDE1234F)")

# Aadhaar record
aadhaar_db.update_one(
    {"aadhaar_number": "123456789012", "name": "MAITREYEE PURANIK"},
    {"$set": {"aadhaar_number": "123456789012", "name": "MAITREYEE PURANIK", "dob": "2004-05-24"}},
    upsert=True,
)
print("Aadhaar record inserted/updated for MAITREYEE PURANIK (123456789012)")

# Verify
print("\n--- All PAN records for ABCDE1234F ---")
for r in pan_db.find({"pan_number": "ABCDE1234F"}):
    print(f"  name={r.get('name')}  dob={r.get('dob')}")

print("\n--- All Aadhaar records for 123456789012 ---")
for r in aadhaar_db.find({"aadhaar_number": "123456789012"}):
    print(f"  name={r.get('name')}  dob={r.get('dob')}")
