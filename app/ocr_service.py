import pytesseract
from PIL import Image, ImageOps, ImageEnhance, ImageFilter
import re
from datetime import datetime

# Set Tesseract path (Windows)
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


def extract_text(image_path):
    img = Image.open(image_path)
    texts = _ocr_multi_pass(img)
    return max(texts, key=len) if texts else ""


def extract_text_candidates(image_path):
    img = Image.open(image_path)
    return _ocr_multi_pass(img)


def _ocr_multi_pass(img):
    """Run OCR on multiple preprocessed variants to improve consistency."""
    variants = []

    base = img.convert("RGB")
    variants.append(base)

    gray = ImageOps.grayscale(base)
    variants.append(gray)

    # Increase contrast and sharpness for low-quality scans/photos.
    contrast = ImageEnhance.Contrast(gray).enhance(2.0)
    sharp = ImageEnhance.Sharpness(contrast).enhance(2.0)
    variants.append(sharp)

    # Binary threshold variant for text-heavy regions.
    bw = sharp.point(lambda p: 255 if p > 150 else 0)
    variants.append(bw)

    # Upscaled variant helps with small text.
    upscaled = bw.resize((bw.width * 2, bw.height * 2), Image.Resampling.LANCZOS)
    variants.append(upscaled)

    outputs = []
    configs = [
        r"--oem 3 --psm 6",
        r"--oem 3 --psm 11",
    ]

    for v in variants:
        for cfg in configs:
            try:
                txt = pytesseract.image_to_string(v, config=cfg)
                if txt:
                    outputs.append(txt)
            except Exception:
                continue

    return outputs


def _normalize_pan_token(token):
    """Fix common OCR confusions for PAN format AAAAA9999A."""
    cleaned = re.sub(r"[^A-Za-z0-9]", "", (token or "").upper())
    if len(cleaned) != 10:
        return None

    chars = list(cleaned)
    letter_map = {
        "0": "O",
        "1": "I",
        "2": "Z",
        "5": "S",
        "6": "G",
        "8": "B",
    }
    digit_map = {
        "O": "0",
        "Q": "0",
        "D": "0",
        "I": "1",
        "L": "1",
        "Z": "2",
        "S": "5",
        "G": "6",
        "B": "8",
    }

    # PAN: first 5 letters
    for i in range(5):
        chars[i] = letter_map.get(chars[i], chars[i])

    # next 4 digits
    for i in range(5, 9):
        chars[i] = digit_map.get(chars[i], chars[i])

    # last letter
    chars[9] = letter_map.get(chars[9], chars[9])

    normalized = "".join(chars)
    if re.fullmatch(r"[A-Z]{5}[0-9]{4}[A-Z]", normalized):
        return normalized

    return None


# -------------------------
# PAN NUMBER
# -------------------------
def extract_pan(text):
    text = (text or "").upper()

    # Fast path: clean PAN already present.
    direct = re.search(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b", text)
    if direct:
        return direct.group(0)

    # PAN can appear split by spaces or hyphens: "ABCDE 1234 F".
    segmented = re.search(r"\b([A-Z]{5})[\s\-]*([0-9]{4})[\s\-]*([A-Z])\b", text)
    if segmented:
        return "".join(segmented.groups())

    # OCR sometimes adds separators/noise; compact and scan again.
    compact = re.sub(r"[^A-Z0-9]", "", text)
    compact_match = re.search(r"[A-Z]{5}[0-9]{4}[A-Z]", compact)
    if compact_match:
        return compact_match.group(0)

    # Fallback: try token normalization for OCR-confused strings.
    tokens = re.findall(r"[A-Z0-9]{8,14}", text)
    for token in tokens:
        pan = _normalize_pan_token(token)
        if pan:
            return pan

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