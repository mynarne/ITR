# ITR · Is This Real?

[한국어](README.ko.md) · [English](README.md) · **1.0.0-rc.2**

AI가 작업을 마쳤다고 답했을 때, 어느 요구사항까지 실제로 확인됐을까? ITR은 그 질문에 증거로 답하는 독립 소프트웨어 QA 스킬이다. 실행 전에 제품 리비전과 목표, 이번에 선택한 스킬 규칙, 프로젝트 요구사항의 버전을 고정한다. 검사마다 확인할 기준, 통과로 인정할 관찰값, 그 증거를 얻을 수 있는 환경을 정한다. 에이전트마다 다른 모델을 써도 같은 로컬 기록을 이어 읽을 수 있으며 운영 서버도 필요 없다. 사용자에게 보이는 날짜와 시각은 한국 표준시(KST)로 표시한다.

![한 손으로 턱을 괴고 다른 손에 파란 돋보기를 낮춰 든 채 AI 글씨를 살피는 막대인간](assets/itr-mascot-aligned.svg)

[진행 지도 리플레이 열기](examples/preview/replay.html) · [같은 시도의 PDF 보기](examples/preview/report.pdf) · [RC.2 후속 검증](docs/verification-rc2-followup.ko.md) · [이전 RC.2 검증](docs/verification-rc2.ko.md) · [에이전트 지침](SKILL.md)

## 한 회차에서 무엇을 읽을 수 있나

진행 지도에서 단위·통합·시스템·인수 시나리오와 필요한 경우 시스템 간 통합 검사를 단계와 검토 역할별로 따라간다. 실패 카드를 열면 어긋난 목표나 요구사항에서 로그 또는 수집한 캡처로 이동할 수 있다. 러너는 실행 전에 정한 `fingerprint`로 실패를 묶으며, 기본은 검사당 한 건이다. 확인 원인과 가설은 비어 있다. 자동으로 들어가는 수정·재검사 문구는 검토자가 채울 내용을 안내한다.

산출물을 읽은 인스펙션과 프로그램을 실행한 테스트는 각각 판정한다. 필요한 실기기가 없으면 **차단**, 이번 범위에서 뺀 검사는 **미실행**으로 남겨 통과·실패와 따로 센다. 정밀 모드는 제품 전반을 살피고, 일상 변경분 모드는 변경된 경로와 의존성, 관련 과거 결함을 따라간다. 인수 시나리오가 통과해도 발주자나 사용자의 실제 승인은 별도로 기록한다.

새 회차와 같은 회차의 재시도·정정은 각자 새 시도 폴더를 쓴다. 한 시도를 공유할 때는 봉인된 `record.json`을 `reports/round-0001/attempt-0002/`처럼 새로운 출력 폴더에 렌더링한다. 이 기록에서 `report.md`·`replay.html`·`print.html`이 만들어지고, PDF가 필요하면 같은 폴더의 새 `report.pdf`로 내보낸다. 이전 보고서와 실패하거나 중단된 시도의 증거도 그대로 남는다.

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

   입력 고정부터 진행 중인 검사, 병렬 상태, 중단과 새 시도를 확인할 수 있다. 짧은 검사는 두 번의 폴링 사이에 끝날 수 있다. 봉인 리플레이에는 모든 이벤트가 보존된다. Windows 읽기 잠금 중에도 관찰자는 원본 저널을 따라가며 게시를 재시도한다. 이미 관찰한 봉인·중단 상태는 대기열에 남긴다. Ctrl+C와 `--once --out`은 최대 2초 동안 게시를 마무리하며, 종료 2는 화면 색인이 오래된 상태일 수 있음을 뜻한다. 완결 시도는 결과 보고서로 연결된다. `python3 tools/progress.py --store itr-runs --once --json`은 같은 상태를 한 번 읽는다. 기본 브라우저에서 로컬 스크립트가 제한되면 CLI 관찰 결과를 사용할 수 있다.

## 내 프로젝트 연결

[프로젝트 계획 예시](examples/project/plan.json)와 [ITR 자체 검사 계획](examples/itr-selfcheck.json)을 참고한다. 후자는 이 패키지 자체를 실제 대상으로 삼는다. 위 명령에서 `--workspace . --plan examples/itr-selfcheck.json`으로 바꾸고 별도 저장소를 사용하면 ITR의 계약 검증기와 실제 회귀 시험을 실행한다.

- `input`에 목표·선택된 스킬 규칙·프로젝트 요구사항의 버전, 리비전, 검사별 기준 ID·관찰할 통과 조건과 필요한 능력을 넣는다. `files`는 프로젝트 루트 기준 **명시한 파일 목록**이다. 테스트가 사용할 모듈·데이터를 함께 넣는다.
- `commands`는 검사 ID별 `argv`, `timeout_s` 및 선택적 `pass_marker`다. 승인 대상에는 계획 바이트, 파일 지문, 실행기 지문, 대상 위치와 확인된 능력이 포함된다. 러너는 승인된 명령을 셸 경유 없이 검사별 임시 사본에서 실행한다. 환경의 자격 증명은 자식 프로세스에 전달하지 않는다. 신뢰하는 프로젝트 테스트만 등록한다. 파일 목록과 새 프로세스는 호스트의 OS 보안 샌드박스를 제공하지 않는다.
- 종료 0은 명령이 확인한 관찰 조건에 대해 통과다. `pass_marker`가 있으면 디코딩한 표준 출력 전체에서 실제 문구를 확인해야 한다. 테스트를 발견하지 못해도 0을 반환하는 도구는 실제 검사 완료 문구를 지정하거나 작은 래퍼에서 미실행을 77로 변환한다. 종료 1은 실패, 77은 미실행, 기타 종료값·시간 초과·필수 능력 부족은 차단이다. 저장소 작성 오류는 CLI 종료 2다.
- 통합 판정은 선택된 검사에 대해 실패 → 차단 → 미실행 → 통과 순이다. 증거는 종료 코드, 경과 시간, 표준 출력/오류, 잘림 여부, 원본 해시를 남긴다. 고유 결함을 묶을 때는 실제 공통 근거를 확인하고 동일한 `fingerprint`를 지정한다. 인수 시나리오와 별도로 발주자·사용자 승인 증빙을 남긴다. 실행 승인을 프로젝트 인수 서명으로 쓸 수 없다.
- 재시도는 같은 회차의 새 `--attempt N --retry 상대경로`, 정정은 새 `--attempt N --corrects 상대경로 --reason "사유"`, 새 리비전은 새 회차와 `--previous`로 잇는다. 실패·중단된 원본은 보존한다. `progress.py`의 가변 색인은 사용자가 지정한 별도 출력 폴더에만 있다.

기본 출력 인코딩은 UTF-8이다. 실제 CP949를 출력하는 실행기에는 명령에 `"output_encoding": "cp949"`를 넣는다. 스트림별 처음 64 KiB의 원시 바이트를 디코딩해 보존한다. 그 경계를 걸치거나 넘어 확인한 첫 통과 문구는 `stdout_marker_excerpt`에 해당 문구(최대 256 UTF-8 바이트)와 0부터 센 디코딩 문자 위치로 남긴다. 총 바이트 수와 잘림 여부도 기록한다. 전체 로그가 필요하면 승인된 별도 수집을 사용한다. 기본값에서 `{python}` 자식은 `-X utf8` UTF-8 모드로 실행되므로 `open()`의 기본 인코딩도 UTF-8이 된다. [프로젝트 증거 2.0](schemas/project-evidence.schema.json)은 실제 프로세스에 전달한 `launch_argv`를 기록한다. 프로세스를 호출하기 전에 차단되면 이 필드는 `null`이다. RC.1과 기존 RC.2 증거는 원래 규칙으로 검증하며 실제 실행 인수 미기록으로 표시한다. 절대 실행 경로와 인수가 포함될 수 있으므로 작업 증거는 로컬에 보관하고 공유 전 내용을 검토한다. `"output_encoding": "cp949"`는 디코딩에 CP949를 사용하고 `{python}`의 자동 `-X utf8`을 끈다. 자식의 실제 로캘은 실행 환경과 명령에 따라 달라진다.

Windows는 `{python}`과 `-m pytest`, 또는 신뢰하는 절대 `.exe` 경로를 사용한다. 예를 들어 Node 실행 파일의 경로와 고정 목록에 포함한 로컬 스크립트 인수를 함께 지정한다. 이름만 주면 Python의 디렉터리와 Windows System32에서 찾는다. 파일은 명시 목록의 합계 64 MiB까지 복사하며 설치 의존성은 함께 복사하지 않는다. 작업별 `TEMP`, `TMP`, `TMPDIR`을 제공하며 사용자 PATH, 배치 래퍼, `USERPROFILE`, `APPDATA`, 자격 증명은 이 계약 범위에 없다. RC.2는 실행 정책도 승인에 묶으므로 새로 `inspect`한다. 승인 지문이 달라진 RC.1 시도를 이어갈 때는 사유가 있는 정정 또는 새 회차를 연결한다. `itr.py`, `project.py`, `progress.py`의 리디렉션 출력은 UTF-8이다. Windows PowerShell 5.1에서 변수나 파이프로 받을 때는 `[Console]::OutputEncoding = [Text.Encoding]::UTF8`을 설정한다. UTF-8 텍스트 파일이 필요하면 `| Set-Content -Encoding UTF8 결과.txt`를 사용한다. PowerShell 5.1의 이 명령은 BOM을 추가하며, 기본 `>`는 별도 인코딩 규칙을 따른다. 실행 증거 2.0은 새 승인 지문을 사용하므로 다시 `inspect`해야 한다.

## 자동 실행과 독립 검토

- 로컬 러너의 `reviews`는 명령 결과의 역할별 집계다. 동봉 데모가 여섯 역할의 형식을 보여 준다. 실제 독립 검토는 역할별 검토자나 별도 세션에 허용된 입력만 준 뒤, 첫 판정을 보존하고 나서 통합한다.
- 원인·가설이나 권한자의 인수 승인은 봉인 기록 SHA-256을 참조하는 별도 기록에 남긴다. 주석과 승인 입력 CLI, ANDA·Notion·Discord 전송은 미구현이다.
- 러너는 `local_command`와 현재 지원 OS 표지만 확인한다. 브라우저·시뮬레이터·실기기는 별도 어댑터가 필요하다. `verify`는 내부 일관성을 검증한다. 독립 증빙이 필요하면 승인된 운영자가 실행하고 그 권한 아래 기록 지문을 별도 보관하거나 재실행한다.

## 호환 범위와 재현

| 범위 | 확인 수준 |
|---|---|
| Linux x86_64 · Python 3.12 | 로컬 프로젝트 실행·중단·동시 작성·변조 확인, 실제 ITR 자체 테스트. 세부 수치는 검증 요약에 있다. |
| 브라우저 | 리플레이와 진행 지도, 모션 감소·수동 탐색을 제공한다. 이 세션의 실제 Chromium은 페이지를 열기 전 소켓 생성이 차단됐다. DOM 모형 시험과 실제 픽셀·모션 검수 상태는 따로 기록했다. |
| 다른 OS / 시뮬레이터 / 실기기 | 공통 입력과 능력 탐지 계약을 제공한다. 이번 Linux 검사에서 Windows 공유 잠금과 CP949를 모의했다. 실제 Windows 읽기 잠금 시험은 Windows에서만 실행된다. macOS·실기기 실측은 이번 클라우드 검사 범위 밖이다. |
| 다른 AI / 외부 협업 | 다른 에이전트가 같은 JSON을 읽을 수 있다. 여섯 역할을 각각 다른 AI 서비스에서 검토하는 방식은 설계 단계다. ANDA 연동은 선택 사항이다. 독립 1차 판정을 봉인한 뒤 별도 승인을 받은 새 Notion 페이지나 새 Discord 메시지·스레드로 전달하도록 설계했다. |
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

[평가 설계와 ISO 공식 자료](docs/assessment.ko.md)는 ISO/IEC 25010:2023의 제품 품질, 25019:2023의 사용 맥락 품질, ISO/IEC/IEEE 29119-1~4의 테스트 개념·절차·문서·설계, ISO/IEC 20246의 산출물 리뷰를 각각 매핑한다. 25040은 선택적 평가 프레임이다. 시도마다 적용하거나 제외한 이유를 기록한다. 이 매핑은 평가 설계를 위한 참고이며 표준 준수나 인증을 보장하지 않는다. [저장·어댑터 계약](docs/architecture.ko.md), [공통 기록 스키마](schemas/record.schema.json), [검증 게이트](docs/gates.ko.md), [배포 점검](docs/release.ko.md)에 상세가 있다. 보안 품질 검토 범위는 방어적 소스·설정 점검이다.
