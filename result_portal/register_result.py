import argparse
import base64
import hashlib
import json
import os
import secrets
import shutil
from datetime import datetime, timezone
from pathlib import Path

import qrcode


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
PDF_DIR = DATA_DIR / "pdfs"
QR_DIR = DATA_DIR / "qr"
RESULTS_FILE = DATA_DIR / "results.json"
DEFAULT_BASE_URL = "http://localhost:8080"


def normalize_birth_date(value):
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    if len(digits) == 6:
        return f"19{digits[:2]}-{digits[2:4]}-{digits[4:]}"
    return value.strip()


def hash_birth_date(birth_date, salt):
    normalized = normalize_birth_date(birth_date)
    payload = f"{salt}:{normalized}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_results():
    if not RESULTS_FILE.exists():
        return {}
    with RESULTS_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def save_results(results):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with RESULTS_FILE.open("w", encoding="utf-8") as file:
        json.dump(results, file, ensure_ascii=False, indent=2)


def build_token():
    return base64.urlsafe_b64encode(secrets.token_bytes(18)).decode("ascii").rstrip("=")


def copy_pdf(pdf_path, token):
    if not pdf_path:
        return None
    source = Path(pdf_path).expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(f"PDF not found: {source}")
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    target = PDF_DIR / f"{token}.pdf"
    shutil.copy2(source, target)
    return str(target.relative_to(ROOT))


def make_qr(link, token):
    QR_DIR.mkdir(parents=True, exist_ok=True)
    qr_path = QR_DIR / f"{token}.png"
    image = qrcode.make(link)
    image.save(qr_path)
    return qr_path


def main():
    parser = argparse.ArgumentParser(description="Register a FootScan result and generate a QR code.")
    parser.add_argument("--name", required=True, help="User name shown after verification.")
    parser.add_argument("--birth-date", required=True, help="Birth date for verification, e.g. 1990-01-01.")
    parser.add_argument("--pdf", help="Path to the result analysis PDF.")
    parser.add_argument("--base-url", default=os.environ.get("FOOTSCAN_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--memo", default="", help="Optional memo shown on the web result page.")
    args = parser.parse_args()

    token = build_token()
    salt = secrets.token_hex(16)
    link = f"{args.base_url.rstrip('/')}/r/{token}"
    pdf_rel_path = copy_pdf(args.pdf, token)
    qr_path = make_qr(link, token)

    results = load_results()
    results[token] = {
        "token": token,
        "name": args.name,
        "birth_hash": hash_birth_date(args.birth_date, salt),
        "birth_salt": salt,
        "pdf_path": pdf_rel_path,
        "memo": args.memo,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    save_results(results)

    print(json.dumps({
        "token": token,
        "link": link,
        "qr_path": str(qr_path),
        "pdf_path": pdf_rel_path,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
