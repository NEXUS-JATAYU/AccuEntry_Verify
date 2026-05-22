from fastapi import FastAPI, UploadFile, File, WebSocket, WebSocketDisconnect
import shutil
import os
import json
from datetime import datetime
from app.face_service import verify_live_video, verify_faces
from app.webrtc_service import manager

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


def _normalize_name(value: str | None) -> str:
    return " ".join(
        chunk for chunk in "".join(c if c.isalpha() else " " for c in (value or "").upper()).split() if chunk
    )


def _normalize_dob(value: str | None) -> str | None:
    if not value:
        return None
    try:
        return normalize_ocr_date(value).isoformat()
    except Exception:
        try:
            return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
        except Exception:
            return None


def _names_match(left: str | None, right: str | None) -> bool:
    clean_left = _normalize_name(left)
    clean_right = _normalize_name(right)
    if not clean_left or not clean_right:
        return False
    return clean_left == clean_right or clean_left in clean_right or clean_right in clean_left


def _lookup_pan_master(pan_number: str | None, name: str | None, dob: str | None) -> dict | None:
    candidates = []
    if pan_number:
        candidates.append(pan_db.find_one({"pan_number": pan_number}, {"_id": 0}))
    normalized_name = _normalize_name(name)
    normalized_dob = _normalize_dob(dob)
    if normalized_name and normalized_dob:
        candidates.append(pan_db.find_one({"name": normalized_name, "dob": normalized_dob}, {"_id": 0}))
    for candidate in candidates:
        if candidate:
            return candidate
    return None


def _extract_document_fields(kyc: dict) -> dict[str, str | None]:
    """OCR/master identity fields for downstream fraud Layer 3 (never raises)."""
    document_name: str | None = None
    document_dob: str | None = None
    document_address: str | None = None
    try:
        pan = kyc.get("pan") if isinstance(kyc.get("pan"), dict) else {}
        aadhaar = kyc.get("aadhaar") if isinstance(kyc.get("aadhaar"), dict) else {}

        for section in (aadhaar, pan):
            master = section.get("matched_master_record")
            if not isinstance(master, dict):
                continue
            if not document_name and master.get("name"):
                document_name = str(master["name"]).strip() or None
            if not document_dob and master.get("dob") is not None:
                document_dob = _normalize_dob(str(master.get("dob")))
            if not document_address and master.get("address"):
                document_address = str(master["address"]).strip() or None
    except Exception:
        pass

    return {
        "document_name": document_name,
        "document_dob": document_dob,
        "document_address": document_address,
    }


def _section_failed(kyc: dict, section: str) -> bool:
    """True only when a doc was uploaded and explicitly not verified."""
    sub = kyc.get(section)
    if not isinstance(sub, dict) or not sub:
        return False
    if "verified" not in sub:
        return False
    return sub.get("verified") is False


def _lookup_aadhaar_master(aadhaar_number: str | None, name: str | None, dob: str | None) -> dict | None:
    candidates = []
    if aadhaar_number:
        candidates.append(aadhaar_db.find_one({"aadhaar_number": aadhaar_number}, {"_id": 0}))
    normalized_name = _normalize_name(name)
    normalized_dob = _normalize_dob(dob)
    if normalized_name and normalized_dob:
        candidates.append(aadhaar_db.find_one({"name": normalized_name, "dob": normalized_dob}, {"_id": 0}))
    for candidate in candidates:
        if candidate:
            return candidate
    return None


@app.get("/")
def home():
    return {"message": "KYC Verification API Running"}

@app.get("/kyc/status")
def kyc_status(user_id: str):
    kyc = kyc_db.find_one({"user_id": user_id})
    if not kyc:
        return {
            "pan_verified": False,
            "aadhaar_verified": False,
            "face_verified": False,
            "video_kyc_verified": False,
            "pan_failed": False,
            "aadhaar_failed": False,
            "face_failed": False,
            "video_kyc_failed": False,
            "document_name": None,
            "document_dob": None,
            "document_address": None,
        }

    pan_v = bool((kyc.get("pan") or {}).get("verified"))
    aadhaar_v = bool((kyc.get("aadhaar") or {}).get("verified"))
    face_v = bool((kyc.get("face") or {}).get("verified"))
    video_kyc_v = bool((kyc.get("video_kyc") or {}).get("verified"))

    doc_fields = _extract_document_fields(kyc)
    return {
        "pan_verified": pan_v,
        "aadhaar_verified": aadhaar_v,
        "face_verified": face_v,
        "video_kyc_verified": video_kyc_v,
        "pan_failed": _section_failed(kyc, "pan"),
        "aadhaar_failed": _section_failed(kyc, "aadhaar"),
        "face_failed": _section_failed(kyc, "face"),
        "video_kyc_failed": _section_failed(kyc, "video_kyc"),
        **doc_fields,
    }

# ------------------------------------------------
# LIVE VERIFICATION SIGNALING API (WebRTC)
# ------------------------------------------------
@app.websocket("/ws/signaling/{room_id}/{client_id}")
async def websocket_signaling(websocket: WebSocket, room_id: str, client_id: str):
    await manager.connect(room_id, client_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                message = json.loads(data)
                await manager.broadcast(room_id, message, sender_id=client_id)
            except json.JSONDecodeError:
                pass
    except WebSocketDisconnect:
        manager.disconnect(room_id, client_id)
        await manager.broadcast(room_id, {"type": "disconnect", "client_id": client_id}, sender_id=client_id)


# ------------------------------------------------
# PAN VERIFICATION API
# ------------------------------------------------
@app.post("/upload-pan")
async def upload_pan(user_id: str, expected_name: str = None, file: UploadFile = File(...)):

    os.makedirs("uploads/pan", exist_ok=True)

    path = f"uploads/pan/{user_id}_{file.filename}"

    with open(path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    text = extract_text(path)

    pan_number = extract_pan(text)
    name = extract_name(text)
    dob = extract_dob(text)
    normalized_ocr_dob = _normalize_dob(dob)

    print("OCR PAN:", pan_number)
    print("OCR NAME:", name)
    print("OCR DOB:", dob)

    master_record = _lookup_pan_master(pan_number, name, dob)
    master_name = master_record.get("name") if master_record else None
    master_dob = master_record.get("dob") if master_record else None

    name_match = _names_match(name, master_name)
    if expected_name:
        name_match = name_match and _names_match(name, expected_name)

    dob_match = bool(normalized_ocr_dob and master_dob and normalized_ocr_dob == master_dob)
    pan_match = bool(pan_number and master_record and master_record.get("pan_number") == pan_number)

    # If a master PAN record exists, use it as the ground truth for
    # identification. Fall back to OCR-only checks only when the master
    # dataset does not have a record for this PAN.
    verified = bool(master_record) and name_match and (dob_match or not normalized_ocr_dob)
    if not master_record:
        verified = bool(pan_number) and name_match and dob_match

    # SAVE IN USER-SCOPED KYC RECORD
    kyc_db.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "pan": {
                    "number": pan_number,
                    "verified": verified,
                    "matched_master_record": master_record,
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

    pan_db.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "pan_number": pan_number,
                "name": name,
                "dob": dob,
                "expected_name": expected_name,
                "verified": verified,
                "matched_master_record": master_record,
                "matched_by": "pan_number" if pan_match else ("name_dob" if master_record else "ocr_only"),
                "checks": {
                    "pan_match": pan_match,
                    "name_match": name_match,
                    "dob_match": dob_match,
                },
                "image_path": path,
                "updated_at": datetime.utcnow(),
            }
        },
        upsert=True,
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
async def upload_aadhaar(user_id: str, expected_name: str = None, file: UploadFile = File(...)):

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
    normalized_ocr_dob = _normalize_dob(dob)

    print("OCR AADHAAR:", aadhaar_number)
    print("OCR NAME:", name)
    print("OCR DOB:", dob)

    if not aadhaar_number:
        return {"verified": False, "error": "aadhaar_not_detected"}

    master_record = _lookup_aadhaar_master(aadhaar_number, name, dob)
    master_name = master_record.get("name") if master_record else None
    master_dob = master_record.get("dob") if master_record else None

    name_match = _names_match(name, master_name)
    if expected_name:
        name_match = name_match and _names_match(name, expected_name)

    dob_match = bool(normalized_ocr_dob and master_dob and normalized_ocr_dob == master_dob)
    aadhaar_match = bool(aadhaar_number and master_record and master_record.get("aadhaar_number") == aadhaar_number)

    verified = bool(master_record) and name_match and (dob_match or not normalized_ocr_dob)
    if not master_record:
        verified = bool(aadhaar_number) and name_match and dob_match

    # store everything in KYC document
    kyc_db.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "aadhaar": {
                    "number": aadhaar_number,
                    "verified": verified,
                    "image_path": path,
                    "matched_master_record": master_record,
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

    aadhaar_db.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "user_id": user_id,
                "aadhaar_number": aadhaar_number,
                "name": name,
                "dob": dob,
                "expected_name": expected_name,
                "verified": verified,
                "matched_master_record": master_record,
                "matched_by": "aadhaar_number" if aadhaar_match else ("name_dob" if master_record else "ocr_only"),
                "checks": {
                    "aadhaar_match": aadhaar_match,
                    "name_match": name_match,
                    "dob_match": dob_match,
                },
                "image_path": path,
                "updated_at": datetime.utcnow(),
            }
        },
        upsert=True,
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
    similarity = result.get("distance", 0.0)

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
# LIVE KYC VERIFICATION API (Video Liveness)
# ------------------------------------------------
@app.post("/live-kyc")
async def live_kyc(user_id: str, file: UploadFile = File(...)):
    os.makedirs("uploads/live_kyc", exist_ok=True)
    video_path = f"uploads/live_kyc/{user_id}_{file.filename}"
    with open(video_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    kyc_record = kyc_db.find_one({"user_id": user_id})
    if not kyc_record or "aadhaar" not in kyc_record:
        return {"verified": False, "error": "aadhaar_not_uploaded"}

    aadhaar_path = kyc_record["aadhaar"]["image_path"]

    result = verify_live_video(aadhaar_path, video_path)

    face_verified = result["verified"]
    similarity = result.get("distance", 0.0)
    is_real = result.get("is_real", True)

    final_verified = face_verified and is_real

    kyc_db.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "live_video_checks": {
                    "verified": final_verified,
                    "similarity": similarity,
                    "is_real": is_real,
                    "face_match": face_verified,
                    "anti_spoofing": is_real
                }
            }
        }
    )
    return {
        "verified": final_verified,
        "similarity_score": similarity,
        "is_real": is_real
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