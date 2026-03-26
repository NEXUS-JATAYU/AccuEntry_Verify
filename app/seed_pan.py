from app.database import pan_db


def main():
    doc = {
        "pan_number": "ABCDE1234F",
        "name": "RAHUL GUPTA",
        "dob": "1974-11-23",
    }
    pan_db.update_one({"pan_number": doc["pan_number"]}, {"$set": doc}, upsert=True)
    print("seeded_pan", doc["pan_number"])


if __name__ == "__main__":
    main()
