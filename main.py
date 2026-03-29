from fastapi import FastAPI, UploadFile, File
import shutil
import os
import re
import csv
import io
from datetime import datetime
from app.face_service import verify_faces

from app.database import pan_db, aadhaar_db, kyc_db
from app.ocr_service import (
    extract_text,
    extract_text_candidates,
    extract_pan,
    extract_name,
    extract_dob,
    extract_aadhaar,
    normalize_ocr_date,
)

app = FastAPI()


def _normalize_name(value: str | None) -> str:
    """Uppercase and strip non-letters so OCR punctuation/spacing does not cause false mismatch."""
    if not value:
        return ""
    return re.sub(r"[^A-Z]", "", value.upper())


def _names_match(ocr_name: str | None, db_name: str | None) -> bool:
    o = _normalize_name(ocr_name)
    d = _normalize_name(db_name)
    if not o or not d:
        return False
    return o == d or o in d or d in o


def _row_value(row: dict, *keys: str) -> str | None:
    lowered = {str(k).strip().lower(): v for k, v in row.items()}
    for key in keys:
        value = lowered.get(key.lower())
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def _normalize_pan_number(value: str | None) -> str | None:
    cleaned = re.sub(r"[^A-Z0-9]", "", (value or "").upper())
    return cleaned if re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", cleaned) else None


def _normalize_aadhaar_number(value: str | None) -> str | None:
    cleaned = re.sub(r"\D", "", (value or ""))
    return cleaned if re.fullmatch(r"\d{12}", cleaned) else None


def _normalize_master_dob(value: str | None) -> str | None:
    raw = (value or "").strip()
    if not raw:
        return None

    for fmt in ("%Y-%m-%d", "%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y"):
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    return None


def _decode_csv_content(content: bytes) -> str:
    return content.decode("utf-8-sig", errors="ignore")


def _seed_pan_csv(content: bytes) -> dict:
    text = _decode_csv_content(content)
    reader = csv.DictReader(io.StringIO(text))

    if not reader.fieldnames:
        return {"inserted": 0, "updated": 0, "skipped": 0, "errors": ["CSV header missing"]}

    inserted = 0
    updated = 0
    skipped = 0
    errors = []

    for line_no, row in enumerate(reader, start=2):
        pan_number = _normalize_pan_number(_row_value(row, "pan_number", "pan", "pan_no", "panno"))
        name = _row_value(row, "name", "full_name", "customer_name")
        dob = _normalize_master_dob(_row_value(row, "dob", "date_of_birth", "birth_date"))

        if not pan_number or not name or not dob:
            skipped += 1
            errors.append(f"line {line_no}: invalid pan/name/dob")
            continue

        result = pan_db.update_one(
            {"pan_number": pan_number},
            {"$set": {"pan_number": pan_number, "name": name.upper(), "dob": dob}},
            upsert=True,
        )
        if result.upserted_id is not None:
            inserted += 1
        else:
            updated += 1

    return {"inserted": inserted, "updated": updated, "skipped": skipped, "errors": errors}


def _seed_aadhaar_csv(content: bytes) -> dict:
    text = _decode_csv_content(content)
    reader = csv.DictReader(io.StringIO(text))

    if not reader.fieldnames:
        return {"inserted": 0, "updated": 0, "skipped": 0, "errors": ["CSV header missing"]}

    inserted = 0
    updated = 0
    skipped = 0
    errors = []

    for line_no, row in enumerate(reader, start=2):
        aadhaar_number = _normalize_aadhaar_number(_row_value(row, "aadhaar_number", "aadhaar", "aadhaar_no", "aadhar_number", "aadhar"))
        name = _row_value(row, "name", "full_name", "customer_name")
        dob = _normalize_master_dob(_row_value(row, "dob", "date_of_birth", "birth_date"))

        if not aadhaar_number or not name or not dob:
            skipped += 1
            errors.append(f"line {line_no}: invalid aadhaar/name/dob")
            continue

        result = aadhaar_db.update_one(
            {"aadhaar_number": aadhaar_number},
            {"$set": {"aadhaar_number": aadhaar_number, "name": name.upper(), "dob": dob}},
            upsert=True,
        )
        if result.upserted_id is not None:
            inserted += 1
        else:
            updated += 1

    return {"inserted": inserted, "updated": updated, "skipped": skipped, "errors": errors}


@app.get("/")
def home():
    return {"message": "KYC Verification API Running"}


@app.post("/admin/seed-master-data")
async def seed_master_data(
    pan_file: UploadFile | None = File(default=None),
    aadhaar_file: UploadFile | None = File(default=None),
):
    if not pan_file and not aadhaar_file:
        return {"ok": False, "error": "no_files_uploaded"}

    response = {"ok": True, "pan": None, "aadhaar": None}

    if pan_file:
        pan_content = await pan_file.read()
        response["pan"] = _seed_pan_csv(pan_content)

    if aadhaar_file:
        aadhaar_content = await aadhaar_file.read()
        response["aadhaar"] = _seed_aadhaar_csv(aadhaar_content)

    return response


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
    video_kyc_v = bool(kyc.get("video_kyc", {}).get("verified", False))

    return {
        "pan_verified": pan_v,
        "aadhaar_verified": aadhaar_v,
        "face_verified": face_v,
        "video_kyc_verified": video_kyc_v,
        "pan_failed": failed("pan"),
        "aadhaar_failed": failed("aadhaar"),
        "face_failed": failed("face"),
        "video_kyc_failed": failed("video_kyc"),
    }


# ------------------------------------------------
# PAN VERIFICATION API
# ------------------------------------------------
@app.post("/upload-pan")
async def upload_pan(user_id: str, file: UploadFile = File(...)):

    print(f"PAN upload started | user_id={user_id} | filename={file.filename}")

    os.makedirs("uploads/pan", exist_ok=True)

    path = f"uploads/pan/{user_id}_{file.filename}"

    with open(path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    text = extract_text(path)

    pan_number = (extract_pan(text) or "").upper() or None
    name = extract_name(text)
    dob = extract_dob(text)

    # Retry extraction using multiple OCR variants if primary pass misses PAN.
    if not pan_number:
        try:
            for candidate_text in extract_text_candidates(path):
                cand_pan = (extract_pan(candidate_text) or "").upper() or None
                if cand_pan:
                    pan_number = cand_pan
                    name = name or extract_name(candidate_text)
                    dob = dob or extract_dob(candidate_text)
                    break
        except Exception:
            pass

    print(f"PAN OCR result | user_id={user_id} | filename={file.filename} | pan={pan_number} | name={name} | dob={dob}")

    if not pan_number:
        return {"verified": False, "error": "pan_not_detected"}

    pan_lookup_pattern = f"^{pan_number[:5]}[\\s\\-]*{pan_number[5:9]}[\\s\\-]*{pan_number[9]}$"
    record = pan_db.find_one({"pan_number": {"$regex": pan_lookup_pattern, "$options": "i"}})

    if not record:
        return {"verified": False, "error": "pan_not_found"}

    db_name = record.get("name")
    db_dob = record.get("dob")

    pan_match = True
    name_match = _names_match(name, db_name)

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

    error = None
    if not verified:
        if not name_match:
            error = "name_mismatch"
        elif not dob_match:
            error = "dob_mismatch"
        else:
            error = "pan_verification_failed"

    return {
        "verified": verified,
        "error": error,
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

    print(f"Aadhaar upload started | user_id={user_id} | filename={file.filename}")

    os.makedirs("uploads/aadhaar", exist_ok=True)

    path = f"uploads/aadhaar/{user_id}_{file.filename}"

    with open(path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    text = extract_text(path)

    aadhaar_number = extract_aadhaar(text)
    name = extract_name(text)
    dob = extract_dob(text)

    if not aadhaar_number:
        try:
            for candidate_text in extract_text_candidates(path):
                cand_aadhaar = extract_aadhaar(candidate_text)
                if cand_aadhaar:
                    aadhaar_number = cand_aadhaar
                    name = name or extract_name(candidate_text)
                    dob = dob or extract_dob(candidate_text)
                    break
        except Exception:
            pass

    print(f"Aadhaar OCR result | user_id={user_id} | filename={file.filename} | aadhaar={aadhaar_number} | name={name} | dob={dob}")

    if not aadhaar_number:
        return {"verified": False, "error": "aadhaar_not_detected"}

    aadhaar_lookup_pattern = f"^{aadhaar_number[0:4]}[\\s\\-]*{aadhaar_number[4:8]}[\\s\\-]*{aadhaar_number[8:12]}$"
    record = aadhaar_db.find_one({"aadhaar_number": {"$regex": aadhaar_lookup_pattern, "$options": "i"}})

    if not record:
        return {"verified": False, "error": "aadhaar_not_found"}

    db_name = record.get("name")
    db_dob = record.get("dob")

    name_match = _names_match(name, db_name)

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

    error = None
    if not verified:
        if not name_match:
            error = "name_mismatch"
        elif not dob_match:
            error = "dob_mismatch"
        else:
            error = "aadhaar_verification_failed"

    return {
        "verified": verified,
        "error": error,
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

    print(f"Selfie upload started | user_id={user_id} | filename={file.filename}")

    os.makedirs("uploads/selfie", exist_ok=True)

    selfie_path = f"uploads/selfie/{user_id}_{file.filename}"

    with open(selfie_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    kyc_record = kyc_db.find_one({"user_id": user_id})

    if not kyc_record or "aadhaar" not in kyc_record:
        return {"verified": False, "error": "aadhaar_not_uploaded"}

    aadhaar_path = kyc_record.get("aadhaar", {}).get("image_path")
    if not aadhaar_path or not os.path.exists(aadhaar_path):
        return {"verified": False, "error": "aadhaar_image_missing"}

    result = verify_faces(aadhaar_path, selfie_path)

    face_verified = result["verified"]
    similarity = result.get("distance")
    face_error = result.get("error")

    print(
        f"Selfie verification result | user_id={user_id} | aadhaar_path={aadhaar_path} | selfie_path={selfie_path} | verified={face_verified} | similarity={similarity} | error={face_error}"
    )

    kyc_db.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "face": {
                    "verified": face_verified,
                    "similarity": similarity,
                    "error": face_error,
                    "image_path": selfie_path
                }
            }
        }
    )

    return {
        "verified": face_verified,
        "similarity_score": similarity,
        "error": face_error
    }


# ------------------------------------------------
# VIDEO KYC VERIFICATION API
# ------------------------------------------------
@app.post("/upload-video-kyc")
async def upload_video_kyc(user_id: str, file: UploadFile = File(...)):

    print(f"Video KYC upload started | user_id={user_id} | filename={file.filename}")

    os.makedirs("uploads/video_kyc", exist_ok=True)
    video_path = f"uploads/video_kyc/{user_id}_{file.filename}"

    with open(video_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    kyc_record = kyc_db.find_one({"user_id": user_id})

    if not kyc_record or "face" not in kyc_record:
        return {"verified": False, "error": "selfie_not_uploaded"}

    selfie_path = kyc_record.get("face", {}).get("image_path")
    if not selfie_path or not os.path.exists(selfie_path):
        return {"verified": False, "error": "selfie_image_missing"}

    from app.face_service import verify_live_video
    result = verify_live_video(selfie_path, video_path)

    verified = result.get("verified", False)
    
    print(f"Video KYC verification result | user_id={user_id} | verified={verified} | is_real={result.get('is_real')}")

    kyc_db.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "video_kyc": {
                    "verified": verified,
                    "is_real": result.get("is_real", False),
                    "distance": result.get("distance", 0.0),
                    "error": result.get("error")
                }
            }
        }
    )

    return result

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