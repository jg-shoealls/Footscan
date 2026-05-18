"""
FootScan QR 포털 연동 도구

ShoeallsFootScan 앱의 measurements.db를 읽어 검사 결과를 웹 포털에 등록하고,
QR 코드가 삽입된 결과지 PDF를 생성합니다.

사용법:
  # 최근 측정 목록 확인
  python footscan_qr_watcher.py list

  # 특정 측정 결과를 포털에 등록 (QR 삽입 PDF 생성)
  python footscan_qr_watcher.py register --id 3 --name "홍길동" --birth "1990-01-15"

  # 새 측정 자동 감시 (백그라운드 실행)
  python footscan_qr_watcher.py watch

환경 변수:
  FOOTSCAN_APP_DB   - 앱 DB 경로 (기본: AppData/Local/ShoeallsFootScan/measurements.db)
  FOOTSCAN_API_URL  - Shoealls 백엔드 URL (기본: http://localhost:8000)
  FOOTSCAN_BASE_URL - 환자 포털 URL (기본: http://localhost:3000)
  FOOTSCAN_OUT_DIR  - PDF 출력 폴더 (기본: ~/Documents/FootScan_QR)
"""

import argparse
import io
import json
import os
import sys

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REMOVED_SCRIPT_PATHS = []
for _path in list(sys.path):
    _resolved = os.path.abspath(_path or os.getcwd())
    if _resolved == _SCRIPT_DIR:
        sys.path.remove(_path)
        _REMOVED_SCRIPT_PATHS.append(_path)
import sqlite3
for _path in reversed(_REMOVED_SCRIPT_PATHS):
    sys.path.insert(0, _path)
del _path, _resolved, _REMOVED_SCRIPT_PATHS, _SCRIPT_DIR

import time
from datetime import datetime
from pathlib import Path

from footscan_pressure_3d import (
    FrameDecodeOptions,
    build_pressure_frames,
    write_pressure_3d_html,
)

APP_DB = Path(os.environ.get(
    "FOOTSCAN_APP_DB",
    Path.home() / "AppData" / "Local" / "ShoeallsFootScan" / "measurements.db"
))
API_URL  = os.environ.get("FOOTSCAN_API_URL",  "http://localhost:8000")
BASE_URL = os.environ.get("FOOTSCAN_BASE_URL", "http://localhost:3000")
OUT_DIR  = Path(os.environ.get("FOOTSCAN_OUT_DIR", Path.home() / "Documents" / "FootScan_QR"))


# ---------------------------------------------------------------------------
# DB 읽기
# ---------------------------------------------------------------------------

def _open_app_db() -> sqlite3.Connection:
    if not APP_DB.exists():
        print(f"[오류] DB를 찾을 수 없습니다: {APP_DB}")
        sys.exit(1)
    conn = sqlite3.connect(str(APP_DB))
    conn.row_factory = sqlite3.Row
    return conn


def list_measurements(limit: int = 20) -> list[dict]:
    conn = _open_app_db()
    rows = conn.execute(
        "SELECT id, timestamp, frame_count, duration_seconds, memo "
        "FROM measurements ORDER BY id DESC LIMIT ?",
        (limit,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_measurement(meas_id: int) -> dict | None:
    conn = _open_app_db()
    row = conn.execute(
        "SELECT * FROM measurements WHERE id = ?", (meas_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def get_frames(meas_id: int) -> list[bytes]:
    conn = _open_app_db()
    rows = conn.execute(
        "SELECT frame_data FROM measurement_frames WHERE measurement_id = ? ORDER BY frame_index",
        (meas_id,)
    ).fetchall()
    conn.close()
    return [r["frame_data"] for r in rows]


# ---------------------------------------------------------------------------
# QR 코드 + PDF 생성
# ---------------------------------------------------------------------------

def _require(pkg: str):
    try:
        return __import__(pkg)
    except ImportError:
        print(f"[오류] 패키지 없음: {pkg}")
        print("  pip install qrcode[pil] reportlab pypdf")
        sys.exit(1)


def generate_result_pdf(
    meas: dict,
    patient_name: str,
    birth_date: str,
    qr_url: str,
    out_path: Path,
) -> None:
    """측정 결과와 QR 코드가 포함된 PDF를 생성합니다."""
    _require("qrcode")
    _require("reportlab")
    import qrcode as qrlib
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor, black, white, Color
    from reportlab.pdfgen import canvas as rl_canvas

    # QR 코드 생성
    qr = qrlib.QRCode(version=1, error_correction=qrlib.constants.ERROR_CORRECT_M, box_size=6, border=3)
    qr.add_data(qr_url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white")
    qr_buf = io.BytesIO()
    qr_img.save(qr_buf, format="PNG")
    qr_buf.seek(0)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    c = rl_canvas.Canvas(str(out_path), pagesize=A4)
    W, H = A4
    primary   = HexColor("#2563EB")
    teal      = HexColor("#0D9488")
    light_bg  = HexColor("#F1F5F9")
    text_pri  = HexColor("#0F172A")
    text_sec  = HexColor("#475569")

    # 헤더 바
    c.setFillColor(primary)
    c.rect(0, H - 22*mm, W, 22*mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(12*mm, H - 14*mm, "Shoealls FootScan")
    c.setFont("Helvetica", 10)
    c.drawRightString(W - 12*mm, H - 14*mm, "족압 검사 결과지")

    # 환자 정보 박스
    c.setFillColor(light_bg)
    c.roundRect(10*mm, H - 58*mm, W - 20*mm, 32*mm, 3*mm, fill=1, stroke=0)
    c.setFillColor(text_pri)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(16*mm, H - 34*mm, "환자 정보")
    c.setFont("Helvetica", 10)
    c.setFillColor(text_sec)
    ts = meas.get("timestamp", "")[:19].replace("T", " ")
    info_lines = [
        ("이름",   patient_name),
        ("검사일", ts or datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("측정시간", f"{meas.get('duration_seconds', 0):.1f}초  |  {meas.get('frame_count', 0)}프레임"),
        ("메모",   meas.get("memo") or "-"),
    ]
    for i, (label, val) in enumerate(info_lines):
        y = H - 43*mm - i * 6*mm
        c.setFillColor(text_sec)
        c.drawString(16*mm, y, f"{label}:")
        c.setFillColor(text_pri)
        c.drawString(42*mm, y, val)

    # 결과 섹션 (압력 데이터 없으면 안내 문구)
    c.setFillColor(text_pri)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(12*mm, H - 72*mm, "측정 요약")
    c.setStrokeColor(primary)
    c.setLineWidth(0.5)
    c.line(12*mm, H - 74*mm, W - 12*mm, H - 74*mm)

    c.setFont("Helvetica", 10)
    c.setFillColor(text_sec)
    summary_items = [
        ("총 프레임 수",   f"{meas.get('frame_count', 0)} 프레임"),
        ("측정 시간",      f"{meas.get('duration_seconds', 0):.1f} 초"),
        ("측정 ID",       f"#{meas.get('id', '-')}"),
        ("기록 시각",      ts),
    ]
    for i, (label, val) in enumerate(summary_items):
        col = i % 2
        row = i // 2
        x = 16*mm + col * 90*mm
        y = H - 84*mm - row * 12*mm
        c.setFillColor(light_bg)
        c.roundRect(x - 2*mm, y - 3*mm, 84*mm, 10*mm, 2*mm, fill=1, stroke=0)
        c.setFillColor(text_sec)
        c.drawString(x, y, label + ":")
        c.setFillColor(text_pri)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(x + 32*mm, y, val)
        c.setFont("Helvetica", 10)

    # QR 코드 영역
    qr_size = 38*mm
    qr_x = W - qr_size - 14*mm
    qr_y = 18*mm

    c.setFillColor(light_bg)
    c.roundRect(qr_x - 4*mm, qr_y - 4*mm, qr_size + 8*mm, qr_size + 16*mm, 3*mm, fill=1, stroke=0)
    c.drawImage(qr_buf, qr_x, qr_y + 8*mm, qr_size, qr_size, mask="auto")

    c.setFont("Helvetica-Bold", 7)
    c.setFillColor(primary)
    c.drawCentredString(qr_x + qr_size/2, qr_y + 5*mm, "QR 스캔으로 결과 조회")
    c.setFont("Helvetica", 6)
    c.setFillColor(text_sec)
    c.drawCentredString(qr_x + qr_size/2, qr_y + 2*mm, "생년월일 입력 후 열람")

    # 안내 문구
    c.setFont("Helvetica", 8)
    c.setFillColor(text_sec)
    c.drawString(12*mm, 28*mm, "본 결과지는 참고용이며, 정확한 진단은 전문 의료진과 상담하시기 바랍니다.")
    c.drawString(12*mm, 22*mm, f"결과 조회 URL: {qr_url}")

    # 푸터
    c.setFillColor(primary)
    c.rect(0, 0, W, 10*mm, fill=1, stroke=0)
    c.setFillColor(white)
    c.setFont("Helvetica", 7)
    c.drawString(12*mm, 3.5*mm, "© 2026 Shoealls Advanced Gait AI — 개인정보보호법에 따라 본인 확인 후 열람 가능")
    c.drawRightString(W - 12*mm, 3.5*mm, datetime.now().strftime("%Y-%m-%d"))

    c.save()
    print(f"[완료] PDF 생성: {out_path}")


# ---------------------------------------------------------------------------
# 포털 등록
# ---------------------------------------------------------------------------

def register_to_portal(
    meas: dict,
    patient_name: str,
    birth_date: str,
    pdf_path: Path | None = None,
) -> dict:
    try:
        import requests as req
    except ImportError:
        print("[오류] pip install requests")
        sys.exit(1)

    scan_date = (meas.get("timestamp") or "")[:10] or datetime.now().strftime("%Y-%m-%d")
    result_json = json.dumps({
        "측정 시간": f"{meas.get('duration_seconds', 0):.1f}초",
        "프레임 수": meas.get("frame_count", 0),
        "측정 ID": meas.get("id"),
        "메모": meas.get("memo") or "",
    }, ensure_ascii=False)

    data = {
        "patient_name": patient_name,
        "birth_date":   birth_date,
        "scan_date":    scan_date,
        "result_json":  result_json,
    }
    files = {}
    if pdf_path and pdf_path.exists():
        files["pdf_file"] = (pdf_path.name, open(pdf_path, "rb"), "application/pdf")

    resp = req.post(f"{API_URL}/api/footscan/register", data=data, files=files or None, timeout=30)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# CLI 커맨드
# ---------------------------------------------------------------------------

def cmd_list(args) -> None:
    rows = list_measurements(args.limit)
    if not rows:
        print("측정 데이터가 없습니다. FootScan 앱으로 측정을 먼저 진행하세요.")
        return
    print(f"{'ID':>4}  {'시각':19}  {'초':6}  {'프레임':6}  메모")
    print("-" * 60)
    for r in rows:
        ts = (r.get("timestamp") or "")[:19]
        dur = f"{r.get('duration_seconds', 0):.1f}s"
        fc  = r.get("frame_count", 0)
        memo = r.get("memo") or ""
        print(f"{r['id']:>4}  {ts:19}  {dur:6}  {fc:6}  {memo}")


def cmd_register(args) -> None:
    meas = get_measurement(args.id)
    if not meas:
        print(f"[오류] ID {args.id} 측정 결과를 찾을 수 없습니다.")
        sys.exit(1)

    print(f"\n측정 정보: ID={meas['id']}, 시각={meas.get('timestamp','')[:19]}")
    name  = args.name  or input("환자 이름: ").strip()
    birth = args.birth or input("생년월일 (YYYY-MM-DD): ").strip()

    # 1. 우선 토큰 없이 포털 등록 → URL 확보
    print("\n[1/3] 포털 등록 중...")
    try:
        info = register_to_portal(meas, name, birth, None)
        token   = info["token"]
        qr_url  = info["url"]
        print(f"  토큰: {token}")
        print(f"  URL : {qr_url}")
    except Exception as e:
        print(f"[경고] 백엔드 연결 실패: {e}")
        import secrets
        token  = secrets.token_urlsafe(10)
        qr_url = f"{BASE_URL}/scan/{token}"
        print(f"  오프라인 모드로 진행: {qr_url}")

    # 2. PDF 생성
    print("[2/3] PDF 생성 중...")
    scan_date = (meas.get("timestamp") or "")[:10] or datetime.now().strftime("%Y-%m-%d")
    pdf_name  = f"FootScan_{scan_date}_{name}_{token[:6]}.pdf"
    pdf_path  = OUT_DIR / pdf_name
    generate_result_pdf(meas, name, birth, qr_url, pdf_path)

    # 3. PDF 업로드
    print("[3/3] PDF 업로드 중...")
    try:
        register_to_portal(meas, name, birth, pdf_path)
        print("  업로드 완료")
    except Exception as e:
        print(f"  [경고] 업로드 실패 (로컬 PDF는 저장됨): {e}")

    print(f"\n완료! 환자에게 아래를 안내하세요:")
    print(f"  URL: {qr_url}")
    print(f"  PDF: {pdf_path}")
    print(f"  인증: 생년월일 입력")


def cmd_watch(args) -> None:
    print(f"[감시 중] {APP_DB}")
    print("새 측정 감지 시 환자 정보 입력 프롬프트가 표시됩니다. (Ctrl+C 종료)\n")

    conn = _open_app_db()
    last_id = conn.execute("SELECT COALESCE(MAX(id),0) FROM measurements").fetchone()[0]
    conn.close()

    try:
        while True:
            time.sleep(3)
            conn = _open_app_db()
            row = conn.execute(
                "SELECT id FROM measurements WHERE id > ? ORDER BY id DESC LIMIT 1", (last_id,)
            ).fetchone()
            conn.close()
            if row:
                new_id = row["id"]
                last_id = new_id
                print(f"\n새 측정 감지: ID={new_id}")
                meas = get_measurement(new_id)
                memo = meas.get("memo") or ""
                if memo:
                    print(f"  앱 메모: {memo}")
                name  = input("  환자 이름: ").strip()
                birth = input("  생년월일 (YYYY-MM-DD): ").strip()

                # Namespace로 args 재사용
                class A:
                    id = new_id
                    name = None
                    birth = None
                A.name  = name
                A.birth = birth
                cmd_register(A)
    except KeyboardInterrupt:
        print("\n감시 종료.")


def cmd_visualize3d(args) -> None:
    meas = get_measurement(args.id)
    if not meas:
        print(f"[error] Measurement ID {args.id} was not found.")
        sys.exit(1)

    blobs = get_frames(args.id)
    if not blobs:
        print(f"[error] Measurement ID {args.id} has no frame data.")
        sys.exit(1)

    measurement_type = args.type
    if measurement_type == "auto":
        measurement_type = "static" if len(blobs) <= 1 else "dynamic"

    options = FrameDecodeOptions(
        rows=args.rows,
        cols=args.cols,
        dtype=args.dtype,
        max_frames=args.max_frames,
        smooth=not args.no_smooth,
        normalize=args.normalize,
    )

    try:
        frames = build_pressure_frames(blobs, options)
    except Exception as exc:
        print(f"[error] Could not decode pressure frames: {exc}")
        print("        If the sensor grid is fixed, retry with --rows, --cols, and --dtype.")
        sys.exit(1)

    if measurement_type == "static" and len(frames) > 1:
        import numpy as _np

        frames = [_np.asarray(frames, dtype=_np.float32).mean(axis=0).round(4).tolist()]

    scan_date = (meas.get("timestamp") or "")[:10] or datetime.now().strftime("%Y-%m-%d")
    out_path = Path(args.output) if args.output else OUT_DIR / "3d" / f"FootScan3D_{scan_date}_{args.id}.html"
    write_pressure_3d_html(
        frames,
        out_path,
        title=f"FootScan 3D Pressure - Measurement #{args.id}",
        measurement={
            "id": meas.get("id"),
            "timestamp": (meas.get("timestamp") or "")[:19],
            "duration_seconds": meas.get("duration_seconds"),
            "frame_count": meas.get("frame_count"),
            "memo": meas.get("memo") or "",
        },
        measurement_type=measurement_type,
    )
    print(f"[done] 3D pressure visualization written to: {out_path}")


# ---------------------------------------------------------------------------
# 진입점
# ---------------------------------------------------------------------------

def main():
    p = argparse.ArgumentParser(description="FootScan QR 포털 연동 도구")
    sub = p.add_subparsers(dest="cmd", required=True)

    l = sub.add_parser("list", help="최근 측정 목록 출력")
    l.add_argument("--limit", type=int, default=20)

    r = sub.add_parser("register", help="측정 결과를 포털에 등록")
    r.add_argument("--id",    type=int, required=True, help="측정 ID (list 명령으로 확인)")
    r.add_argument("--name",  help="환자 이름 (생략 시 입력 프롬프트)")
    r.add_argument("--birth", help="생년월일 YYYY-MM-DD (생략 시 입력 프롬프트)")

    sub.add_parser("watch", help="새 측정 자동 감시")

    v = sub.add_parser("visualize3d", help="3D 압력분포 등고선 HTML 생성")
    v.add_argument("--id", type=int, required=True, help="측정 ID (list 명령으로 확인)")
    v.add_argument("--type", choices=("auto", "static", "dynamic"), default="auto", help="측정 타입")
    v.add_argument("--rows", type=int, help="센서 그리드 행 수")
    v.add_argument("--cols", type=int, help="센서 그리드 열 수")
    v.add_argument("--dtype", default="auto", help="원시 프레임 dtype: auto, <u2, <f4, <u1 등")
    v.add_argument("--max-frames", type=int, default=240, help="동적 HTML에 포함할 최대 프레임 수")
    v.add_argument("--output", help="출력 HTML 경로")
    v.add_argument("--no-smooth", action="store_true", help="3x3 smoothing 비활성화")
    v.add_argument("--normalize", action="store_true", help="프레임별 압력값을 0..1로 정규화")

    args = p.parse_args()
    {
        "list": cmd_list,
        "register": cmd_register,
        "watch": cmd_watch,
        "visualize3d": cmd_visualize3d,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
