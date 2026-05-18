# Shoealls FootScan

족압(발바닥 압력) 측정 및 분석 소프트웨어입니다. 측정 결과를 QR 코드와 웹 포털로 환자에게 제공하는 기능을 포함합니다.

---

## 주요 기능

- **족압 실시간 측정** — USB 센서를 통해 발바닥 압력 분포를 프레임 단위로 수집
- **결과 분석 및 시각화** — 좌/우발 압력 비교, 아치 유형 분류 등 측정 데이터 분석
- **QR 결과 포털** — 결과지 하단 QR 코드 스캔으로 환자가 웹에서 결과 조회 및 PDF 저장
- **생년월일 본인 확인** — 간단한 인증으로 개인 측정 결과 열람

---

## 시스템 요구 사항

| 항목 | 최소 사양 |
|------|----------|
| OS | Windows 10 64-bit 이상 |
| RAM | 4 GB |
| Python | 3.8 (앱에 내장됨, 별도 설치 불필요) |
| 네트워크 | 결과 포털 사용 시 필요 |

---

## 설치

1. `unins000.exe` 또는 설치 파일로 설치 후 `Shoealls FootScan.exe` 실행
2. 측정 데이터는 아래 경로에 자동 생성됩니다:
   ```
   %LOCALAPPDATA%\ShoeallsFootScan\measurements.db
   %LOCALAPPDATA%\ShoeallsFootScan\device_config.json
   ```

---

## 디렉토리 구조

```
Shoealls FootScan/
├── Shoealls FootScan.exe   # 메인 애플리케이션
├── assets/                 # 발 유형 분류 이미지 (a_1~g_3.png)
├── PyQt5/                  # GUI 프레임워크 런타임
├── numpy/ scipy/           # 수치 연산 라이브러리
├── result_portal/          # 웹 결과 포털 (자체 서버 방식)
│   ├── server.py           # 경량 HTTP 서버
│   ├── register_result.py  # 결과 등록 CLI
│   └── data/               # 결과 JSON, PDF, QR 이미지 저장
└── footscan_qr_watcher.py  # DB 연동 QR 포털 CLI
```

---

## 결과 포털 사용법

측정 결과를 환자가 QR 코드로 조회할 수 있도록 두 가지 방식을 지원합니다.

### 방식 1 — 자체 HTTP 서버 (`result_portal/`)

외부 백엔드 없이 로컬 PC에서 직접 운영할 때 사용합니다.

**1. 서버 실행**
```powershell
python result_portal\server.py --host 0.0.0.0 --port 8080 --base-url http://내IP:8080
```

**2. 결과 등록 (PDF 첨부)**
```powershell
python result_portal\register_result.py `
  --name "홍길동" `
  --birth-date 1990-01-01 `
  --pdf "C:\path\to\result.pdf"
```
→ QR 이미지(`data/qr/`)와 조회 링크 출력

**3. 환자 안내**
- 결과지 하단 QR 스캔 또는 출력된 URL 접속
- 생년월일 입력 → 결과 확인 및 PDF 다운로드

---

### 방식 2 — Shoealls 백엔드 연동 (`footscan_qr_watcher.py`)

Shoealls AI 플랫폼 백엔드와 연결하여 운영할 때 사용합니다.

**최근 측정 목록 확인**
```powershell
python footscan_qr_watcher.py list
```

**특정 측정 결과 등록 (QR PDF 자동 생성)**
```powershell
python footscan_qr_watcher.py register --id 3 --name "홍길동" --birth "1990-01-15"
```

**새 측정 자동 감시**
```powershell
python footscan_qr_watcher.py watch
```
→ 새 측정 감지 시 환자 이름/생년월일 입력 프롬프트 표시

**환경 변수**

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `FOOTSCAN_API_URL` | Shoealls 백엔드 주소 | `http://localhost:8000` |
| `FOOTSCAN_BASE_URL` | 환자 포털 도메인 | `http://localhost:3000` |
| `FOOTSCAN_OUT_DIR` | 생성 PDF 저장 경로 | `~/Documents/FootScan_QR` |
| `FOOTSCAN_APP_DB` | 앱 DB 경로 | `%LOCALAPPDATA%\ShoeallsFootScan\measurements.db` |

---

## 장치 설정 (`device_config.json`)

```json
{
  "vmin": 60,        // 압력 최솟값 (단위: raw)
  "vmax": 400,       // 압력 최댓값
  "duration": 20,    // 측정 시간 (초)
  "countdown": 3,    // 측정 시작 카운트다운 (초)
  "noise_filter": false,
  "dark_mode": false
}
```

---

## 보안 안내

- 생년월일은 SHA-256 해시(salt 포함)로 저장되며 원문은 보관하지 않습니다.
- 외부망 운영 시 HTTPS 설정, 접근 로그 관리, 만료일 설정을 권장합니다.
- 결과는 등록 후 **90일** 뒤 자동 만료됩니다.

---

## 라이선스

© 2026 Shoealls. All rights reserved.
