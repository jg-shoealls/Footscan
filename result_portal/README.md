# FootScan result portal

FootScan에서 생성된 결과 분석지 PDF를 웹 조회용으로 등록하고, 결과지 하단에 넣을 QR 코드와 링크를 생성하는 보조 모듈입니다.

## 사용 순서

1. 서버 실행

```powershell
python result_portal\server.py --host 0.0.0.0 --port 8080 --base-url http://localhost:8080
```

2. 결과 등록

```powershell
python result_portal\register_result.py --name "홍길동" --birth-date 1990-01-01 --pdf "C:\path\to\result.pdf"
```

3. 출력된 `link` 텍스트 또는 `qr_path`의 QR 이미지를 결과 분석지 하단에 삽입합니다.

사용자는 QR을 스캔해 웹페이지로 이동한 뒤 생년월일을 입력하면 결과를 확인하고 PDF를 다운로드하거나 브라우저 인쇄 기능으로 PDF 저장을 할 수 있습니다.

## 저장 위치

- 등록 정보: `result_portal\data\results.json`
- 원본 PDF 사본: `result_portal\data\pdfs`
- QR 이미지: `result_portal\data\qr`

## 운영 메모

생년월일은 원문 저장하지 않고 salt를 포함한 SHA-256 해시로 저장합니다. 실제 외부 운영 시에는 HTTPS, 접근 로그 관리, 만료일, 관리자 인증, 개인정보 처리방침을 추가해야 합니다.
