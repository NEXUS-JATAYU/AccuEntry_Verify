from deepface import DeepFace


def verify_faces(aadhaar_image, selfie_image):

    try:
        result = DeepFace.verify(
            img1_path=aadhaar_image,
            img2_path=selfie_image,
            model_name="Facenet",
            enforce_detection=False
        )

        return {
            "verified": result["verified"],
            "distance": result["distance"]
        }

    except Exception as e:
        return {
            "verified": False,
            "error": str(e)
        }