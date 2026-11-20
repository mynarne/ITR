# ITR · Is This Real?

**한국어** · [English](README.en.md) · **1.0.0-rc.1**

ITR은 제품 목표와 요구를 먼저 고정한 뒤, **승인한 프로젝트 테스트가 어떤 조건을 확인했고 무엇을 남겼는지** 기록하는 독립 QA 스킬이다. 사용할 모델, 편집기, 운영 서버를 지정하지 않는다. 실제 검사와 보고서의 근거는 회차별 로컬 파일에 남는다. 날짜와 사용자 표시 시각은 KST다.

[0.1 실제 기록 리플레이](examples/preview/replay.html) · [같은 시도의 PDF](examples/preview/report.pdf) · [RC 검증 결과](VERIFICATION.ko.md) · [에이전트 지침](SKILL.md)

## 처음 한 번 실행하기

ZIP을 풀어 `VERSION`이 있는 폴더로 이동한다. 기본 경로에는 Python 3.9 이상과 표준 라이브러리만 필요하다. Windows의 런처가 `py -3`인 경우 아래의 `python3`를 바꿔 사용한다.

1. **검토한다.** 아래 명령은 테스트에 사용할 파일·실행기 지문, 명령 인수, 버전과 승인 SHA-256을 출력한다. `examples/project`는 키와 네트워크를 사용하지 않는 작은 재고 분류 예제다. `checks.py`가 수량과 예상·실제 분류를 비교하는지 확인한다.

   ```sh
   python3 tools/project.py inspect --workspace examples/project --plan examples/project/plan.json
   ```

2. **확인한 계획만 실행한다.** `COPY_REVIEWED_SHA256`을 첫 명령의 `approval_sha256` 64자리 값으로 바꾼다. 다른 위치에서 압축을 풀거나 입력·실행기가 바뀌었으면 다시 확인한다.

   ```sh
   python3 tools/project.py run --workspace examples/project --plan examples/project/plan.json --approve COPY_REVIEWED_SHA256 --store itr-runs --round 1 --require-pass
   python3 tools/project.py verify itr-runs/round-0001/attempt-0001/record.json
   python3 views/render.py itr-runs/round-0001/attempt-0001/record.json --out my-first-report
   ```

   선택한 두 검사에서 수량 5는 `ready`, 2는 `low`다. `my-first-report/replay.html`에서 검사 카드와 근거를 연다. 수량 0의 결함을 보려면 `plan-defect.json`을 별도로 확인하고 새 SHA를 사용한다. 같은 저장소에서는 `--round 2 --previous round-0001/attempt-0001/record.json`을 지정한다. 기대값 `empty`와 실제값 `low`가 다르므로 이 실행의 `--require-pass` 종료값은 3이다.

3. **실행 중에 보려면** 별도 터미널에서 아래 관찰자를 *실행 전에* 시작한다. `itr-progress/index.html`을 브라우저로 열어 둔다. 포트와 서버가 필요 없다. `--out`은 매번 새 폴더, `--store`는 러너와 같은 폴더를 사용한다.

   ```sh
   python3 tools/progress.py --store itr-runs --watch --out itr-progress
   ```

   입력 고정부터 진행 중인 검사, 병렬 상태, 중단과 새 시도를 확인할 수 있다. 짧은 검사는 두 번의 폴링 사이에 끝날 수 있다. 봉인 리플레이에는 모든 이벤트가 보존된다. 관찰자 종료는 Ctrl+C다. 완결 시도는 결과 보고서로 연결된다. `python3 tools/progress.py --store itr-runs --once --json`은 같은 상태를 한 번 읽는다. 기본 브라우저에서 로컬 스크립트가 제한되면 CLI 관찰 결과를 사용할 수 있다.

## 내 프로젝트 연결

[프로젝트 계획 예시](examples/project/plan.json)와 [ITR 자체 검사 계획](examples/itr-selfcheck.json)을 참고한다. 후자는 이 패키지 자체를 실제 대상으로 삼는다. 위 명령에서 `--workspace . --plan examples/itr-selfcheck.json`으로 바꾸고 별도 저장소를 사용하면 ITR의 계약 검증기와 실제 회귀 시험을 실행한다.

- `input`에 목표·선택된 스킬 규칙·프로젝트 요구사항의 버전, 리비전, 검사별 기준 ID·관찰할 통과 조건과 필요한 능력을 넣는다. `files`는 프로젝트 루트 기준 **명시한 파일 목록**이다. 테스트가 사용할 모듈·데이터를 함께 넣는다.
- `commands`는 검사 ID별 `argv`, `timeout_s` 및 선택적 `pass_marker`다. 승인 대상에는 계획 바이트, 파일 지문, 실행기 지문, 대상 위치와 확인된 능력이 포함된다. 러너는 승인된 명령을 셸 경유 없이 검사별 임시 사본에서 실행한다. 환경의 자격 증명은 자식 프로세스에 전달하지 않는다. 신뢰하는 프로젝트 테스트만 등록한다. 파일 목록과 새 프로세스는 호스트의 OS 보안 샌드박스를 제공하지 않는다.
- 종료 0은 명령이 확인한 관찰 조건에 대해 통과다. `pass_marker`가 있으면 보존된 표준 출력에서 해당 문구도 확인해야 한다. 테스트를 발견하지 못해도 0을 반환하는 도구는 실제 검사 완료 문구를 지정하거나 작은 래퍼에서 미실행을 77로 변환한다. 종료 1은 실패, 77은 미실행, 기타 종료값·시간 초과·필수 능력 부족은 차단이다. 저장소 작성 오류는 CLI 종료 2다.
- 통합 판정은 선택된 검사에 대해 실패 → 차단 → 미실행 → 통과 순이다. 증거는 종료 코드, 경과 시간, 표준 출력/오류, 잘림 여부, 원본 해시를 남긴다. 고유 결함을 묶을 때는 실제 공통 근거를 확인하고 동일한 `fingerprint`를 지정한다. 인수 시나리오와 별도로 발주자·사용자 승인 증빙을 남긴다. 실행 승인을 프로젝트 인수 서명으로 쓸 수 없다.
- 재시도는 같은 회차의 새 `--attempt N --retry 상대경로`, 정정은 새 `--attempt N --corrects 상대경로 --reason "사유"`, 새 리비전은 새 회차와 `--previous`로 잇는다. 실패·중단된 원본은 보존한다. `progress.py`의 가변 색인은 사용자가 지정한 별도 출력 폴더에만 있다.

## 호환 범위와 재현

| 범위 | 확인 수준 |
|---|---|
| Linux x86_64 · Python 3.12 | 로컬 프로젝트 실행·중단·동시 작성·변조 확인, 실제 ITR 자체 테스트. 세부 수치는 검증 요약에 있다. |
| 브라우저 | 리플레이와 진행 지도, 모션 감소·수동 탐색을 제공한다. 이 세션의 실제 Chromium은 페이지를 열기 전 소켓 생성이 차단됐다. DOM 모형 시험과 실제 픽셀·모션 검수 상태는 따로 기록했다. |
| 다른 OS / 시뮬레이터 / 실기기 | 공통 입력과 능력 탐지 계약을 제공한다. Windows·macOS 제품 실행 및 실기기 확인은 이번 세션에서 미검증이다. |
| 다른 AI / 외부 협업 | 다른 에이전트가 같은 JSON을 읽을 수 있다. 여섯 역할의 독립 컨텍스트를 실제 AI 서비스에 연결하는 절차와 ANDA의 승인 후 Notion·Discord 전달은 설계 범위다. |
| PDF | 동봉 PDF는 실제 생성본이다. 새 PDF를 만들 때만 PyMuPDF가 추가로 필요하다. 브라우저용 인쇄 HTML도 제공한다. |

```sh
python3 -B qa/check_project.py
python3 -B qa/check_progress.py
python3 -B tools/check_itr.py
python3 -B qa/check_views.py examples/runs/round-0001/attempt-0001/record.json examples/preview --pdf
node qa/check_replay.cjs examples/preview/replay.html
```

표준 라이브러리만 있는 경우 처음 세 명령부터 사용한다. 실제 Chromium 환경의 선택 검사는 `python3 qa/check_browser.py examples/preview/replay.html --out NEW_BROWSER_QA`다. MD·인쇄 HTML·리플레이는 동일한 `record.json`에서 생성되며, `python3 qa/print_pdf.py my-first-report/print.html my-first-report/report.pdf`로 새 PDF를 만들 수 있다.

## 설계와 표준

[평가 설계와 ISO 공식 자료](docs/assessment.ko.md)는 ISO/IEC 25010:2023의 제품 품질, 25019:2023의 사용 맥락 품질, ISO/IEC/IEEE 29119-1~4의 테스트 개념·절차·문서·설계, ISO/IEC 20246의 산출물 리뷰를 각각 매핑한다. 25040은 선택적 평가 프레임이다. 시도마다 적용하거나 제외한 이유를 기록한다. [저장·어댑터 계약](docs/architecture.ko.md), [공통 기록 스키마](schemas/record.schema.json), [검증 게이트](docs/gates.ko.md), [배포 점검](docs/release.ko.md)에 상세가 있다. 보안 품질 검토 범위는 방어적 소스·설정 점검이다.
