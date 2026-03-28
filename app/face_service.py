import cv2
import numpy as np
import uuid
import os
from deepface import DeepFace


def check_video_motion(video_path):
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        return False, 0
        
    ret, prev_frame = cap.read()
    if not ret:
        return False, 0
        
    prev_gray = cv2.cvtColor(prev_frame, cv2.COLOR_BGR2GRAY)
    total_diff = 0
    frames_checked = 0
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
            
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        diff = cv2.absdiff(prev_gray, gray)
        # Count pixels that changed significantly (blocks static frame cheating)
        motion_score = np.sum(diff > 30)
        total_diff += motion_score
        frames_checked += 1
        prev_gray = gray
        
    cap.release()
    # A real human holding a camera for 3 seconds guarantees >5000 diff score
    return total_diff > 5000, frames_checked


def extract_middle_frame(video_path):
    cap = cv2.VideoCapture(video_path)
    length = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    middle_frame_idx = length // 2
    
    cap.set(cv2.CAP_PROP_POS_FRAMES, middle_frame_idx)
    ret, frame = cap.read()
    cap.release()
    
    if ret:
        img_id = str(uuid.uuid4())
        save_path = f"uploads/temp_{img_id}.jpg"
        cv2.imwrite(save_path, frame)
        return save_path
    return None


def verify_live_video(aadhaar_image, video_path):
    try:
        has_motion, frames = check_video_motion(video_path)
        
        if not has_motion or frames < 5:
            return {
                "verified": False,
                "distance": 0.0,
                "is_real": False,
                "error": "static_video_rejected"
            }
            
        frame_path = extract_middle_frame(video_path)
        if not frame_path:
            return {
                "verified": False,
                "distance": 0.0,
                "is_real": False,
                "error": "frame_extraction_failed"
            }
            
        result = DeepFace.verify(
            img1_path=aadhaar_image,
            img2_path=frame_path,
            model_name="Facenet",
            enforce_detection=False,
            anti_spoofing=True
        )

        try:
            os.remove(frame_path)
        except Exception:
            pass

        return {
            "verified": result.get("verified", False),
            "distance": result.get("distance", 0.0),
            "is_real": result.get("is_real", True)
        }

    except Exception as e:
        return {
            "verified": False,
            "error": str(e),
            "is_real": False
        }

def verify_faces(aadhaar_image, selfie_image):
    try:
        result = DeepFace.verify(
            img1_path=aadhaar_image,
            img2_path=selfie_image,
            model_name="Facenet",
            enforce_detection=False
        )
        return {
            "verified": result.get("verified", False),
            "distance": result.get("distance", 0.0)
        }
    except Exception as e:
        return {
            "verified": False,
            "error": str(e)
        }