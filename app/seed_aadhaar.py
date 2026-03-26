from app.database import aadhaar_db


def main():
    doc = {
        "aadhaar_number": "123456789012",
        "name": "SAMARTH SHARMA",
        "dob": "1986-06-20",
    }
    aadhaar_db.update_one({"aadhaar_number": doc["aadhaar_number"]}, {"$set": doc}, upsert=True)
    print("seeded_aadhaar", doc["aadhaar_number"])


if __name__ == "__main__":
    main()
