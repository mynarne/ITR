# 독자용 QA 보고서 · Pretendard

첨부 레퍼런스에서 관찰한 넓은 바깥 여백, 왼쪽에 정렬된 제목과 본문, 얇은 표 구분선, 제한적인 굵기 강조를 가져왔다. A4 세로의 흰 바탕에 요약, 검사 결과, 실행 환경, 근거와 검증 식별자를 배치했다. 판정은 텍스트로 표시한다. 표지에서 축약한 리비전과 긴 설명은 상세에서 확인할 수 있다.

기존 PyMuPDF 의존성을 사용한다. 독자용 프로필은 저장소의 정적 TrueType 폰트 두 파일을 직접 읽어 제목·수치에는 SemiBold, 일반 본문에는 Regular를 임베드한다. 페이지를 넘겨도 같은 폰트를 쓴다. 폰트에 없는 글자가 들어오거나 텍스트 추출 대조에 실패하면 새 PDF를 만들기 전에 오류를 알린다. 기본 감사 프로필의 명령은 `qa/print_pdf.py PRINT.html NEW.pdf`다.

```sh
python3 -B qa/print_pdf.py --profile reader examples/runs/round-0001/attempt-0001/record.json ITR-QA-report-pretendard.pdf
python3 -B qa/check_reader_pdf.py
pdffonts ITR-QA-report-pretendard.pdf
```

`pdffonts`는 Poppler의 선택 도구다. 없으면 `check_reader_pdf.py`가 내장 글꼴이 동봉 Pretendard 파일과 같은지 대신 확인한다.

출력은 원본 시도 폴더 밖의 새 경로로 지정한다. 원본 `record.json`, 완료 해시, 증거, 기존 PDF는 그대로 보존한다.

## 서체 출처와 권리

`assets/fonts/`의 Regular와 SemiBold는 [Pretendard v1.3.9 공식판](https://github.com/orioncactus/pretendard/releases/tag/v1.3.9)의 `packages/pretendard/dist/public/static/alternative/`에서 가져온 두 파일이다. SIL Open Font License 1.1 및 원저작권 고지는 [동봉된 전문](../LICENSES/Pretendard-OFL-1.1.txt)을 따른다.
