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
    if not cap.isOpened():
        return None
    
    # Read up to the 10th frame to avoid initial dark/blank frames
    # and handle .webm files where random seeking fails
    frame_to_save = None
    for _ in range(10):
        ret, frame = cap.read()
        if not ret:
            break
        frame_to_save = frame
        
    cap.release()
    
    if frame_to_save is not None:
        img_id = str(uuid.uuid4())
        save_path = f"uploads/temp_{img_id}.jpg"
        cv2.imwrite(save_path, frame_to_save)
        return save_path
    
    return None


def check_image_quality(frame_path):
    img = cv2.imread(frame_path)
    if img is None:
        return False, "invalid_image"
        
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur_val = cv2.Laplacian(gray, cv2.CV_64F).var()
    
    if blur_val < 30:
        return False, "blur_detected"
        
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    brightness = np.mean(hsv[:,:,2])
    
    if brightness < 40:
        return False, "low_light_detected"
    if brightness > 230:
        return False, "overexposed_detected"
        
    return True, None


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
            
        is_high_quality, quality_error = check_image_quality(frame_path)
        if not is_high_quality:
            try:
                os.remove(frame_path)
            except Exception:
                pass
            return {
                "verified": False,
                "distance": 0.0,
                "is_real": False,
                "error": quality_error
            }
            
        faces = DeepFace.extract_faces(
            img_path=frame_path,
            enforce_detection=False,
            anti_spoofing=True
        )
        
        is_real = True
        for face in faces:
            if not face.get("is_real", True):
                is_real = False
                break
                
        if not is_real:
            try:
                os.remove(frame_path)
            except Exception:
                pass
            return {
                "verified": False,
                "distance": 0.0,
                "is_real": False,
                "error": "spoofing_detected"
            }

        result = DeepFace.verify(
            img1_path=aadhaar_image,
            img2_path=frame_path,
            model_name="Facenet",
            enforce_detection=False,
            anti_spoofing=False
        )

        try:
            os.remove(frame_path)
        except Exception:
            pass

        distance = result.get("distance", 0.0)
        verified = result.get("verified", False)
        
        # Facenet backend threshold is usually ~0.40 for cosine similarity.
        # Live webcams often have compression artifacts pushing distance to ~0.55
        if not verified and distance <= 0.55:
            verified = True

        return {
            "verified": verified,
            "distance": distance,
            "is_real": True
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