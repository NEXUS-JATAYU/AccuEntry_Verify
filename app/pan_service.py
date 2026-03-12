from database import pan_db

def verify_pan(pan_number):

    record = pan_db.find_one({"pan_number": pan_number}, {"_id": 0})

    if record:
        return True
    return False