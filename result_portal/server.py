import argparse
import hashlib
import hmac
import html
import json
import mimetypes
import os
import secrets
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
RESULTS_FILE = DATA_DIR / "results.json"
SESSION_SECRET = os.environ.get("FOOTSCAN_SESSION_SECRET") or secrets.token_hex(32)


def normalize_birth_date(value):
    digits = "".join(ch for ch in value if ch.isdigit())
    if len(digits) == 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:]}"
    if len(digits) == 6:
        return f"19{digits[:2]}-{digits[2:4]}-{digits[4:]}"
    return value.strip()


def hash_birth_date(birth_date, salt):
    normalized = normalize_birth_date(birth_date)
    return hashlib.sha256(f"{salt}:{normalized}".encode("utf-8")).hexdigest()


def load_results():
    if not RESULTS_FILE.exists():
        return {}
    with RESULTS_FILE.open("r", encoding="utf-8") as file:
        return json.load(file)


def page(title, body):
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html.escape(title)}</title>
  <style>
    :root {{ color-scheme: light; font-family: Arial, "Malgun Gothic", sans-serif; }}
    body {{ margin: 0; background: #f5f7fb; color: #172033; }}
    main {{ width: min(920px, calc(100% - 32px)); margin: 42px auto; }}
    .panel {{ background: white; border: 1px solid #d9e0ea; border-radius: 8px; padding: 28px; box-shadow: 0 8px 28px rgba(18, 32, 55, .08); }}
    h1 {{ margin: 0 0 18px; font-size: 26px; }}
    label {{ display: block; margin: 16px 0 8px; font-weight: 700; }}
    input {{ width: 100%; box-sizing: border-box; padding: 12px 14px; border: 1px solid #aeb9c8; border-radius: 6px; font-size: 16px; }}
    button, .button {{ display: inline-block; margin-top: 20px; padding: 11px 16px; border: 0; border-radius: 6px; background: #155eef; color: white; font-weight: 700; font-size: 15px; text-decoration: none; cursor: pointer; }}
    .button.secondary {{ background: #42526d; margin-left: 8px; }}
    .error {{ color: #b42318; font-weight: 700; }}
    .meta {{ border-collapse: collapse; width: 100%; margin: 18px 0; }}
    .meta th, .meta td {{ border-bottom: 1px solid #e4e9f1; padding: 12px 8px; text-align: left; }}
    .meta th {{ width: 160px; color: #526174; }}
    @media print {{ body {{ background: white; }} .panel {{ box-shadow: none; border: 0; }} .actions {{ display: none; }} }}
  </style>
</head>
<body><main><section class="panel">{body}</section></main></body>
</html>"""


class ResultHandler(BaseHTTPRequestHandler):
    server_version = "FootScanResultPortal/1.0"

    def send_html(self, status, content, extra_headers=None):
        encoded = content.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.send_html(HTTPStatus.OK, page("FootScan 결과 조회", "<h1>FootScan 결과 조회</h1><p>결과 분석지의 QR 코드 또는 링크로 접속해 주세요.</p>"))
            return
        if parsed.path.startswith("/r/"):
            token = parsed.path.split("/", 2)[2]
            self.show_verify_form(token)
            return
        if parsed.path.startswith("/pdf/"):
            token = parsed.path.split("/", 2)[2]
            self.serve_pdf(token)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self):
        parsed = urlparse(self.path)
        if not parsed.path.startswith("/r/"):
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        token = parsed.path.split("/", 2)[2]
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        birth_date = parse_qs(body).get("birth_date", [""])[0]
        self.show_result(token, birth_date)

    def find_result(self, token):
        return load_results().get(token)

    def verify(self, result, birth_date):
        if not result or not birth_date:
            return False
        expected = result.get("birth_hash", "")
        actual = hash_birth_date(birth_date, result.get("birth_salt", ""))
        return hmac.compare_digest(expected, actual)

    def sign_session(self, token):
        signature = hmac.new(SESSION_SECRET.encode("utf-8"), token.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{token}.{signature}"

    def has_session(self, token):
        cookies = self.headers.get("Cookie", "")
        sessions = [item.strip().split("=", 1)[1] for item in cookies.split(";") if item.strip().startswith("fs_session=")]
        expected = self.sign_session(token)
        return any(hmac.compare_digest(value, expected) for value in sessions)

    def show_verify_form(self, token, error=""):
        result = self.find_result(token)
        if not result:
            self.send_html(HTTPStatus.NOT_FOUND, page("결과 없음", "<h1>결과를 찾을 수 없습니다</h1><p>링크가 올바른지 확인해 주세요.</p>"))
            return
        error_html = f'<p class="error">{html.escape(error)}</p>' if error else ""
        body = f"""
<h1>본인 확인</h1>
<p>검사 결과를 열람하려면 생년월일을 입력해 주세요.</p>
{error_html}
<form method="post" action="/r/{html.escape(token)}">
  <label for="birth_date">생년월일</label>
  <input id="birth_date" name="birth_date" autocomplete="bday" inputmode="numeric" placeholder="예: 1990-01-01 또는 19900101" required>
  <button type="submit">결과 확인</button>
</form>"""
        self.send_html(HTTPStatus.OK, page("본인 확인", body))

    def show_result(self, token, birth_date):
        result = self.find_result(token)
        if not self.verify(result, birth_date):
            self.show_verify_form(token, "생년월일이 일치하지 않습니다.")
            return
        name = html.escape(result.get("name", ""))
        memo = html.escape(result.get("memo", ""))
        created_at = html.escape(result.get("created_at", ""))
        pdf_button = ""
        if result.get("pdf_path"):
            pdf_button = f'<a class="button" href="/pdf/{html.escape(token)}">PDF 다운로드</a>'
        body = f"""
<h1>검사 결과</h1>
<table class="meta">
  <tr><th>이름</th><td>{name}</td></tr>
  <tr><th>등록일</th><td>{created_at}</td></tr>
  <tr><th>메모</th><td>{memo or "-"}</td></tr>
</table>
<div class="actions">
  {pdf_button}
  <button class="button secondary" onclick="window.print()">현재 화면 PDF 저장</button>
</div>"""
        headers = {"Set-Cookie": f"fs_session={self.sign_session(token)}; HttpOnly; SameSite=Lax; Path=/"}
        self.send_html(HTTPStatus.OK, page("검사 결과", body), headers)

    def serve_pdf(self, token):
        result = self.find_result(token)
        if not result or not self.has_session(token):
            self.send_error(HTTPStatus.FORBIDDEN)
            return
        pdf_rel_path = result.get("pdf_path")
        if not pdf_rel_path:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        pdf_path = (ROOT / pdf_rel_path).resolve()
        if ROOT not in pdf_path.parents or not pdf_path.exists():
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        payload = pdf_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", mimetypes.guess_type(str(pdf_path))[0] or "application/pdf")
        self.send_header("Content-Disposition", f'attachment; filename="{token}.pdf"')
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)


def main():
    parser = argparse.ArgumentParser(description="Run the FootScan result portal.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--base-url", default="")
    args = parser.parse_args()

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((args.host, args.port), ResultHandler)
    print(f"FootScan result portal running at http://{args.host}:{args.port}")
    if args.base_url:
        print(f"Use this base URL when registering results: {args.base_url.rstrip('/')}")
    server.serve_forever()


if __name__ == "__main__":
    main()
