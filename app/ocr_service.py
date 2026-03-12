import pytesseract
from PIL import Image
import re
from datetime import datetime

# Set Tesseract path (Windows)
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def extract_text(image_path):
    img = Image.open(image_path)
    text = pytesseract.image_to_string(img)
    return text


# -------------------------
# PAN NUMBER
# -------------------------
def extract_pan(text):

    pattern = r"[A-Z]{5}[0-9]{4}[A-Z]"

    match = re.search(pattern, text)

    if match:
        return match.group(0)

    return None


# -------------------------
# AADHAAR NUMBER
# -------------------------
def extract_aadhaar(text):

    pattern = r"\b\d{4}[\s\-]?\d{4}[\s\-]?\d{4}\b"

    match = re.search(pattern, text)

    if match:
        aadhaar = match.group(0)

        aadhaar = aadhaar.replace(" ", "")
        aadhaar = aadhaar.replace("-", "")

        return aadhaar

    return None


# -------------------------
# NAME EXTRACTION
# -------------------------
def extract_name(text):

    lines = text.split("\n")

    blacklist = [
        "INCOME TAX",
        "DEPARTMENT",
        "GOVERNMENT",
        "INDIA",
        "PERMANENT",
        "ACCOUNT",
        "NUMBER",
        "SIGNATURE",
        "SAMPLE",
        "UNIQUE",
        "IDENTIFICATION",
        "AUTHORITY",
        "DOB"
    ]

    for line in lines:

        line = line.strip()

        if not line:
            continue

        if line.isupper() and len(line.split()) >= 2:

            ignore = False

            for word in blacklist:
                if word in line:
                    ignore = True
                    break

            if not ignore:
                return line

    return None


# -------------------------
# DOB EXTRACTION
# Supports:
# 20/04/1999
# 20-04-1999
# 20.04.1999
# -------------------------
def extract_dob(text):

    pattern = r"\b\d{2}[\/\-.]\d{2}[\/\-.]\d{4}\b"

    match = re.search(pattern, text)

    if match:
        return match.group(0)

    return None


# -------------------------
# DATE NORMALIZATION
# Convert OCR date → Python date
# -------------------------
def normalize_ocr_date(date_str):

    if not date_str:
        return None

    date_str = date_str.replace("-", "/")
    date_str = date_str.replace(".", "/")

    try:
        return datetime.strptime(date_str, "%d/%m/%Y").date()
    except:
        return None