from fastapi import FastAPI, UploadFile, File
import shutil
import os
from datetime import datetime
from app.face_service import verify_faces

from app.database import pan_db, aadhaar_db, kyc_db
from app.ocr_service import (
    extract_text,
    extract_pan,
    extract_name,
    extract_dob,
    extract_aadhaar,
    normalize_ocr_date
)

app = FastAPI()


@app.get("/")
def home():
    return {"message": "KYC Verification API Running"}


@app.get("/kyc/status")
def kyc_status(user_id: str):
    """Expose KYC flags for AccuEntry doc_verification polling (kyc_db)."""
    kyc = kyc_db.find_one({"user_id": user_id})
    if not kyc:
        return {
            "pan_verified": False,
            "aadhaar_verified": False,
            "face_verified": False,
            "pan_failed": False,
            "aadhaar_failed": False,
            "face_failed": False,
        }

    def failed(section: str) -> bool:
        sub = kyc.get(section)
        if sub is None:
            return False
        return not bool(sub.get("verified", False))

    pan_v = bool(kyc.get("pan", {}).get("verified", False))
    aadhaar_v = bool(kyc.get("aadhaar", {}).get("verified", False))
    face_v = bool(kyc.get("face", {}).get("verified", False))

    return {
        "pan_verified": pan_v,
        "aadhaar_verified": aadhaar_v,
        "face_verified": face_v,
        "pan_failed": failed("pan"),
        "aadhaar_failed": failed("aadhaar"),
        "face_failed": failed("face"),
    }


# ------------------------------------------------
# PAN VERIFICATION API
# ------------------------------------------------
@app.post("/upload-pan")
async def upload_pan(user_id: str, file: UploadFile = File(...)):

    os.makedirs("uploads/pan", exist_ok=True)

    path = f"uploads/pan/{user_id}_{file.filename}"

    with open(path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    text = extract_text(path)

    pan_number = extract_pan(text)
    name = extract_name(text)
    dob = extract_dob(text)

    print("OCR PAN:", pan_number)
    print("OCR NAME:", name)
    print("OCR DOB:", dob)

    record = pan_db.find_one({"pan_number": pan_number})

    if not record:
        return {"verified": False, "error": "pan_not_found"}

    db_name = record["name"]
    db_dob = record["dob"]

    pan_match = True
    name_match = name and name.upper() == db_name.upper()

    ocr_date = normalize_ocr_date(dob)
    db_date = datetime.strptime(db_dob, "%Y-%m-%d").date()

    dob_match = ocr_date == db_date

    verified = pan_match and name_match and dob_match

    # SAVE IN KYC RECORD
    kyc_db.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "pan": {
                    "number": pan_number,
                    "verified": verified,
                    "checks": {
                        "pan_match": pan_match,
                        "name_match": name_match,
                        "dob_match": dob_match
                    }
                }
            }
        },
        upsert=True
    )

    return {
        "verified": verified,
        "checks": {
            "pan_match": pan_match,
            "name_match": name_match,
            "dob_match": dob_match
        }
    }

# ------------------------------------------------
# AADHAAR VERIFICATION API
# ------------------------------------------------
@app.post("/upload-aadhaar")
async def upload_aadhaar(user_id: str, file: UploadFile = File(...)):

    os.makedirs("uploads/aadhaar", exist_ok=True)

    path = f"uploads/aadhaar/{user_id}_{file.filename}"

    with open(path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    text = extract_text(path)

    print("\n===== OCR TEXT =====")
    print(text)
    print("====================")

    aadhaar_number = extract_aadhaar(text)
    name = extract_name(text)
    dob = extract_dob(text)

    print("OCR AADHAAR:", aadhaar_number)
    print("OCR NAME:", name)
    print("OCR DOB:", dob)

    if not aadhaar_number:
        return {"verified": False, "error": "aadhaar_not_detected"}

    record = aadhaar_db.find_one({"aadhaar_number": aadhaar_number})

    if not record:
        return {"verified": False, "error": "aadhaar_not_found"}

    db_name = record["name"]
    db_dob = record["dob"]

    name_match = name and name.upper() == db_name.upper()

    ocr_date = normalize_ocr_date(dob)
    db_date = datetime.strptime(db_dob, "%Y-%m-%d").date()

    dob_match = ocr_date == db_date

    aadhaar_match = True

    verified = aadhaar_match and name_match and dob_match

    # store everything in KYC document
    kyc_db.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "aadhaar": {
                    "number": aadhaar_number,
                    "verified": verified,
                    "image_path": path,
                    "checks": {
                        "aadhaar_match": aadhaar_match,
                        "name_match": name_match,
                        "dob_match": dob_match
                    }
                }
            }
        },
        upsert=True
    )

    return {
        "verified": verified,
        "aadhaar_number": aadhaar_number,
        "checks": {
            "aadhaar_match": aadhaar_match,
            "name_match": name_match,
            "dob_match": dob_match
        }
    }
# ------------------------------------------------
# SELFIE VERIFICATION API
# ------------------------------------------------

@app.post("/upload-selfie")
async def upload_selfie(user_id: str, file: UploadFile = File(...)):

    os.makedirs("uploads/selfie", exist_ok=True)

    selfie_path = f"uploads/selfie/{user_id}_{file.filename}"

    with open(selfie_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    kyc_record = kyc_db.find_one({"user_id": user_id})

    if not kyc_record or "aadhaar" not in kyc_record:
        return {"verified": False, "error": "aadhaar_not_uploaded"}

    aadhaar_path = kyc_record["aadhaar"]["image_path"]

    result = verify_faces(aadhaar_path, selfie_path)

    face_verified = result["verified"]
    similarity = result.get("distance")

    kyc_db.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "face": {
                    "verified": face_verified,
                    "similarity": similarity
                }
            }
        }
    )

    return {
        "verified": face_verified,
        "similarity_score": similarity
    }

# ------------------------------------------------
# APPROVE KYC API
# ------------------------------------------------
@app.post("/agent/approve-kyc")
def approve_kyc(user_id: str, agent_id: str):

    kyc = kyc_db.find_one({"user_id": user_id})

    if not kyc:
        return {"error": "kyc_record_not_found"}

    pan_verified = kyc.get("pan", {}).get("verified", False)
    aadhaar_verified = kyc.get("aadhaar", {}).get("verified", False)
    face_verified = kyc.get("face", {}).get("verified", False)

    if pan_verified and aadhaar_verified and face_verified:

        kyc_db.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "agent_verification": {
                        "status": "approved",
                        "agent_id": agent_id,
                        "reason": None
                    },
                    "kyc_status": "verified"
                }
            }
        )

        return {"status": "kyc_approved"}

    return {
        "status": "cannot_approve",
        "message": "automatic verification not complete"
    }

@app.post("/agent/reject-kyc")
def reject_kyc(user_id: str, agent_id: str, reason: str):

    kyc_db.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "agent_verification": {
                    "status": "rejected",
                    "agent_id": agent_id,
                    "reason": reason
                },
                "kyc_status": "rejected"
            }
        }
    )

    return {
        "status": "kyc_rejected",
        "reason": reason
    }

@app.get("/agent/pending-kyc")
def get_pending_kyc():

    records = list(
        kyc_db.find({"kyc_status": "pending_agent_review"}, {"_id": 0})
    )

    return {"pending_cases": records}