# ITR 검증 보고서

마을상점 영수증 · 합성 CLI · 1차 / 시도 1 · 정밀 모드

- **실행**　itr-fb61caf8278f4a2eb705aa02a9b8fd1e
- **생성 시각**　2026-11-20 09:46:03 KST
- **대상 리비전**　sha256:ed1c4234d066074ce37720bd540fbb1c1aecbbeeceb05e68325f7f39a054cede
- **원본 SHA-256**　51e474a90a6d5c7aa28899cbf2c4812e63ac5c08d33004c90add262e0451b742
- **통합 판정**　실패
- **판정 사유**　선택한 검사 10건 중 통과 7, 실패 2, 차단 1, 미실행 0. 우선순위는 실패 → 차단 → 미실행 → 통과.
- **발주자·사용자 승인**　요청 전
- **승인자 / 시각**　— / —
- **승인 범위 / 근거**　— / —

## 단계별 검사 결과

| 단계 | 통과 | 실패 | 차단 | 미실행 |
| --- | --- | --- | --- | --- |
| 단위 | 1 | 1 | 0 | 0 |
| 통합 | 2 | 0 | 0 | 0 |
| 시스템 | 3 | 1 | 1 | 0 |
| 시스템 간 통합 | 0 | 0 | 0 | 1 |
| 인수 시나리오 | 1 | 0 | 0 | 0 |

고유 결함 1건 · 동일한 fingerprint는 한 건으로 집계합니다.

## 고정한 기준

G-TOTAL · 제품 목표 · 1.0 — 고객에게 품목 금액과 배송비를 합한 원화 청구액을 표시한다.

R-FREE · 프로젝트 요구사항 · 1.0 — 품목 합계가 10,000원 이상이면 배송비는 0원, 미만이면 3,000원이다.

R-CONTRACT · 프로젝트 요구사항 · 1.0 — 영수증 JSON은 subtotal, shipping, total, currency 필드를 제공한다.

R-OFFLINE · 선택 스킬 규칙 · 1.0 — 합성 결제기는 원화 단위를 사용하고 외부 동기화를 끈다.

R-DEVICE · 프로젝트 요구사항 · 1.0 — 선택된 실제 휴대 단말에서 현장 직원이 영수증을 읽을 수 있다.

R-LEDGER · 프로젝트 요구사항 · 1.0 — 별도 합성 장부가 제공된 회차에만 외부 장부 인계 시나리오를 검증한다.

## 실행 환경

| 능력 | 가용 여부 |
| --- | --- |
| local\_python | 가용 |
| source | 가용 |
| physical\_device | 미지원 |
| sandbox\_ledger | 미지원 |

## 검사별 판정

### unit-subtotal · 품목 합계 · 통과

- **단계 / 역할 / 방법**　단위 / 실행기 / 실행 테스트
- **기준**　G-TOTAL
- **통과 조건**　2×2,500원과 1×1,000원의 품목 합계가 6,000원이다.
- **필요 능력**　local\_python
- **선행 검사**　—
- **관찰**　관찰값이 고정된 통과 조건과 일치.
- **증거**　EV-unit-subtotal

### bb-goal · 장바구니 결제 · 통과

- **단계 / 역할 / 방법**　인수 시나리오 / 목표 충족 / 실행 테스트
- **기준**　G-TOTAL, R-FREE
- **통과 조건**　6,000원 상품 2개의 청구액이 12,000원이며 배송비가 0원이다.
- **필요 능력**　local\_python
- **선행 검사**　system-receipt
- **관찰**　관찰값이 고정된 통과 조건과 일치.
- **증거**　EV-bb-goal

### bb-context · 소액 주문 영수증 · 통과

- **단계 / 역할 / 방법**　시스템 / 사용 맥락 / 실행 테스트
- **기준**　G-TOTAL, R-CONTRACT
- **통과 조건**　4,000원 주문에서 배송비를 포함한 7,000원과 KRW가 출력된다.
- **필요 능력**　local\_python
- **선행 검사**　integration-basket
- **관찰**　관찰값이 고정된 통과 조건과 일치.
- **증거**　EV-bb-context

### bb-boundary · 무료 배송 경계 · 실패

- **단계 / 역할 / 방법**　시스템 / 경계 조건 / 실행 테스트
- **기준**　G-TOTAL, R-FREE
- **통과 조건**　9,999원·10,000원·10,001원의 배송비가 순서대로 3,000·0·0원이다.
- **필요 능력**　local\_python
- **선행 검사**　integration-basket
- **관찰**　10,000원 주문에 배송비 3,000원이 청구됨.
- **증거**　EV-bb-boundary

### wb-logic · 경계 비교식 · 실패

- **단계 / 역할 / 방법**　단위 / 내부 로직 / 인스펙션
- **기준**　R-FREE
- **통과 조건**　배송비 분기의 AST가 subtotal \>= 10000이고 참/거짓 금액이 0/3000이다.
- **필요 능력**　source
- **선행 검사**　unit-subtotal
- **관찰**　shipping의 무료 배송 비교식에서 경계값이 제외됨.
- **증거**　EV-wb-logic

### wb-contract · 영수증 출력 계약 · 통과

- **단계 / 역할 / 방법**　통합 / 모듈 계약 / 인스펙션
- **기준**　R-CONTRACT
- **통과 조건**　receipt가 반환하는 딕셔너리 키가 규정된 네 키와 일치한다.
- **필요 능력**　source
- **선행 검사**　unit-subtotal
- **관찰**　관찰값이 고정된 통과 조건과 일치.
- **증거**　EV-wb-contract

### wb-config · 오프라인 설정 · 통과

- **단계 / 역할 / 방법**　시스템 / 구성·설정 / 인스펙션
- **기준**　R-OFFLINE
- **통과 조건**　설정 리터럴에서 통화 KRW 및 external\_sync=false를 확인한다.
- **필요 능력**　source
- **선행 검사**　unit-subtotal
- **관찰**　관찰값이 고정된 통과 조건과 일치.
- **증거**　EV-wb-config

### integration-basket · 품목·배송비 결합 · 통과

- **단계 / 역할 / 방법**　통합 / 실행기 / 실행 테스트
- **기준**　G-TOTAL, R-CONTRACT
- **통과 조건**　품목 합계 5,500원에 배송비 3,000원을 더해 8,500원의 영수증을 만든다.
- **필요 능력**　local\_python
- **선행 검사**　unit-subtotal, wb-contract
- **관찰**　관찰값이 고정된 통과 조건과 일치.
- **증거**　EV-integration-basket

### system-receipt · 영수증 CLI 왕복 · 통과

- **단계 / 역할 / 방법**　시스템 / 실행기 / 실행 테스트
- **기준**　G-TOTAL, R-CONTRACT
- **통과 조건**　12,500원 입력이 배송비 0원 및 총액 12,500원의 JSON으로 출력된다.
- **필요 능력**　local\_python
- **선행 검사**　integration-basket, wb-contract
- **관찰**　관찰값이 고정된 통과 조건과 일치.
- **증거**　EV-system-receipt

### system-device · 실기기 열람 · 차단

- **단계 / 역할 / 방법**　시스템 / 실행기 / 실행 테스트
- **기준**　R-DEVICE
- **통과 조건**　실기기에서 직원이 추가 확대 없이 청구 총액을 정확히 읽는다.
- **필요 능력**　physical\_device
- **선행 검사**　integration-basket
- **관찰**　필수 실행 능력 미제공 · physical\_device
- **증거**　—

### link-ledger · 장부 인계 · 미실행

- **단계 / 역할 / 방법**　시스템 간 통합 / 실행기 / 실행 테스트
- **기준**　R-LEDGER
- **통과 조건**　영수증과 장부 항목의 금액·통화가 일치한다.
- **필요 능력**　sandbox\_ledger
- **선행 검사**　integration-basket
- **관찰**　선택적 장부 연동은 이번 범위에서 제외.
- **증거**　—

## 결함과 회귀 검사

### D-001 · 무료 배송 기준인 10,000원에서 경계 조건이 어긋난다.

- **같은 결함 식별값**　receipt.shipping.threshold.inclusive
- **관련 검사**　bb-boundary, wb-logic
- **깨진 기준**　G-TOTAL, R-FREE
- **근거**　EV-bb-boundary, EV-wb-logic
- **확인된 원인**　shipping 조건식이 subtotal \> 10000이어서 같은 금액을 제외한다.
- **가설**　기록 없음
- **최소 수정 방향**　무료 배송 비교식에 같은 금액을 포함한다.
- **다음 회귀 검사**　bb-boundary 및 wb-logic으로 9,999·10,000·10,001원 사례와 소스 조건을 재검사한다.

## 독립 검토 기록

목표 충족 · 통과 · 2026-11-20 09:46:04 KST · 검사 bb-goal · 증거 EV-bb-goal

사용 맥락 · 통과 · 2026-11-20 09:46:03 KST · 검사 bb-context · 증거 EV-bb-context

경계 조건 · 실패 · 2026-11-20 09:46:04 KST · 검사 bb-boundary · 증거 EV-bb-boundary

내부 로직 · 실패 · 2026-11-20 09:46:03 KST · 검사 wb-logic · 증거 EV-wb-logic

모듈 계약 · 통과 · 2026-11-20 09:46:03 KST · 검사 wb-contract · 증거 EV-wb-contract

구성·설정 · 통과 · 2026-11-20 09:46:03 KST · 검사 wb-config · 증거 EV-wb-config

## 증거 목록

### EV-unit-subtotal · unit-subtotal · log

- **경로**　evidence/unit-subtotal.json
- **SHA-256**　f1e001f99aaa52a39d49b00a83a8041d1340147c0f4b58244abc2423d5695875
- **미리보기**　해시 대조 완료

    {
      "check_id": "unit-subtotal",
      "condition": "2×2,500원과 1×1,000원의 품목 합계가 6,000원이다.",
      "trace": {
        "items": [
          [
            2,
            2500
          ],
          [
            1,
            1000
          ]
        ]
      },
      "expected": 6000,
      "observed": 6000,
      "status": "passed"
    }

### EV-bb-goal · bb-goal · log

- **경로**　evidence/bb-goal.json
- **SHA-256**　f6296756f8b6581d2626ab6335267edf7524ea133e7cc16c7b5ca39d25a47bf5
- **미리보기**　해시 대조 완료

    {
      "check_id": "bb-goal",
      "condition": "6,000원 상품 2개의 청구액이 12,000원이며 배송비가 0원이다.",
      "trace": {
        "items": [
          [
            2,
            6000
          ]
        ]
      },
      "expected": {
        "subtotal": 12000,
        "shipping": 0,
        "total": 12000,
        "currency": "KRW"
      },
      "observed": {
        "subtotal": 12000,
        "shipping": 0,
        "total": 12000,
        "currency": "KRW"
      },
      "status": "passed"
    }

### EV-bb-context · bb-context · log

- **경로**　evidence/bb-context.json
- **SHA-256**　6298c89bcbd033560e5c220e683c675c487ec379988b00f0f2c8cac60e759b25
- **미리보기**　해시 대조 완료

    {
      "check_id": "bb-context",
      "condition": "4,000원 주문에서 배송비를 포함한 7,000원과 KRW가 출력된다.",
      "trace": {
        "items": [
          [
            1,
            4000
          ]
        ]
      },
      "expected": {
        "subtotal": 4000,
        "shipping": 3000,
        "total": 7000,
        "currency": "KRW"
      },
      "observed": {
        "subtotal": 4000,
        "shipping": 3000,
        "total": 7000,
        "currency": "KRW"
      },
      "status": "passed"
    }

### EV-bb-boundary · bb-boundary · log

- **경로**　evidence/bb-boundary.json
- **SHA-256**　28399ba1b821198b20bfdcb27a4bf881789f275f23a28b98fca7dcd447548c2a
- **미리보기**　해시 대조 완료

    {
      "check_id": "bb-boundary",
      "condition": "9,999원·10,000원·10,001원의 배송비가 순서대로 3,000·0·0원이다.",
      "trace": {
        "subtotals": [
          9999,
          10000,
          10001
        ],
        "receipts": [
          {
            "subtotal": 9999,
            "shipping": 3000,
            "total": 12999,
            "currency": "KRW"
          },
          {
            "subtotal": 10000,
            "shipping": 3000,
            "total": 13000,
            "currency": "KRW"
          },
          {
            "subtotal": 10001,
            "shipping": 0,
            "total": 10001,
            "currency": "KRW"
          }
        ]
      },
      "expected": [
        3000,
        0,
        0
      ],
      "observed": [
        3000,
        3000,
        0
      ],
      "status": "failed"
    }

### EV-wb-logic · wb-logic · review

- **경로**　evidence/wb-logic.json
- **SHA-256**　94698fe35dac1fa713be815287106317a1065e9e5be58fa4e26d4417fafc1c03
- **미리보기**　해시 대조 완료

    {
      "check_id": "wb-logic",
      "condition": "배송비 분기의 AST가 subtotal >= 10000이고 참/거짓 금액이 0/3000이다.",
      "trace": {
        "source": "subject.py",
        "method": "Python AST"
      },
      "expected": "IfExp(test=Compare(left=Name(id='subtotal', ctx=Load()), ops=[GtE()], comparators=[Constant(value=10000)]), body=Constant(value=0), orelse=Constant(value=3000))",
      "observed": "IfExp(test=Compare(left=Name(id='subtotal', ctx=Load()), ops=[Gt()], comparators=[Constant(value=10000)]), body=Constant(value=0), orelse=Constant(value=3000))",
      "status": "failed"
    }

### EV-wb-contract · wb-contract · review

- **경로**　evidence/wb-contract.json
- **SHA-256**　b3f6ccab1ec6135794990610a33aa17c60521fba702bb56337f284f48799bf8e
- **미리보기**　해시 대조 완료

    {
      "check_id": "wb-contract",
      "condition": "receipt가 반환하는 딕셔너리 키가 규정된 네 키와 일치한다.",
      "trace": {
        "source": "subject.py",
        "method": "Python AST"
      },
      "expected": [
        "currency",
        "shipping",
        "subtotal",
        "total"
      ],
      "observed": [
        "currency",
        "shipping",
        "subtotal",
        "total"
      ],
      "status": "passed"
    }

### EV-wb-config · wb-config · review

- **경로**　evidence/wb-config.json
- **SHA-256**　b5050751d48359475abb550acb58c306356ff1020bd830fb459e10fd9ff9e97c
- **미리보기**　해시 대조 완료

    {
      "check_id": "wb-config",
      "condition": "설정 리터럴에서 통화 KRW 및 external_sync=false를 확인한다.",
      "trace": {
        "source": "subject.py",
        "method": "Python AST"
      },
      "expected": {
        "currency": "KRW",
        "external_sync": false
      },
      "observed": {
        "currency": "KRW",
        "external_sync": false
      },
      "status": "passed"
    }

### EV-integration-basket · integration-basket · log

- **경로**　evidence/integration-basket.json
- **SHA-256**　495649d9a1848faa82e7d6f1fde367f23e700759b810a5406ecffd7e38a45c17
- **미리보기**　해시 대조 완료

    {
      "check_id": "integration-basket",
      "condition": "품목 합계 5,500원에 배송비 3,000원을 더해 8,500원의 영수증을 만든다.",
      "trace": {
        "items": [
          [
            1,
            2500
          ],
          [
            2,
            1500
          ]
        ]
      },
      "expected": {
        "subtotal": 5500,
        "shipping": 3000,
        "total": 8500,
        "currency": "KRW"
      },
      "observed": {
        "subtotal": 5500,
        "shipping": 3000,
        "total": 8500,
        "currency": "KRW"
      },
      "status": "passed"
    }

### EV-system-receipt · system-receipt · log

- **경로**　evidence/system-receipt.json
- **SHA-256**　d952b49882b0f5cbc52de4cc0b92f2ef17f9e461db409bd787eecbef2835e75f
- **미리보기**　해시 대조 완료

    {
      "check_id": "system-receipt",
      "condition": "12,500원 입력이 배송비 0원 및 총액 12,500원의 JSON으로 출력된다.",
      "trace": {
        "items": [
          [
            1,
            12500
          ]
        ]
      },
      "expected": {
        "subtotal": 12500,
        "shipping": 0,
        "total": 12500,
        "currency": "KRW"
      },
      "observed": {
        "subtotal": 12500,
        "shipping": 0,
        "total": 12500,
        "currency": "KRW"
      },
      "status": "passed"
    }

## 이벤트 이력

1 · 2026-11-20 09:46:03 KST · unit-subtotal · 대기 — 고정된 검사 계획에 등록.

2 · 2026-11-20 09:46:03 KST · bb-goal · 대기 — 고정된 검사 계획에 등록.

3 · 2026-11-20 09:46:03 KST · bb-context · 대기 — 고정된 검사 계획에 등록.

4 · 2026-11-20 09:46:03 KST · bb-boundary · 대기 — 고정된 검사 계획에 등록.

5 · 2026-11-20 09:46:03 KST · wb-logic · 대기 — 고정된 검사 계획에 등록.

6 · 2026-11-20 09:46:03 KST · wb-contract · 대기 — 고정된 검사 계획에 등록.

7 · 2026-11-20 09:46:03 KST · wb-config · 대기 — 고정된 검사 계획에 등록.

8 · 2026-11-20 09:46:03 KST · integration-basket · 대기 — 고정된 검사 계획에 등록.

9 · 2026-11-20 09:46:03 KST · system-receipt · 대기 — 고정된 검사 계획에 등록.

10 · 2026-11-20 09:46:03 KST · system-device · 대기 — 고정된 검사 계획에 등록.

11 · 2026-11-20 09:46:03 KST · link-ledger · 대기 — 고정된 검사 계획에 등록.

12 · 2026-11-20 09:46:03 KST · unit-subtotal · 실행 중 — 고정된 입력으로 검사 시작.

13 · 2026-11-20 09:46:03 KST · unit-subtotal · 통과 — 관찰값이 고정된 통과 조건과 일치.

14 · 2026-11-20 09:46:03 KST · wb-logic · 실행 중 — 고정된 입력으로 검사 시작.

15 · 2026-11-20 09:46:03 KST · wb-contract · 실행 중 — 고정된 입력으로 검사 시작.

16 · 2026-11-20 09:46:03 KST · wb-config · 실행 중 — 고정된 입력으로 검사 시작.

17 · 2026-11-20 09:46:03 KST · wb-logic · 실패 — shipping의 무료 배송 비교식에서 경계값이 제외됨.

18 · 2026-11-20 09:46:03 KST · wb-contract · 통과 — 관찰값이 고정된 통과 조건과 일치.

19 · 2026-11-20 09:46:03 KST · wb-config · 통과 — 관찰값이 고정된 통과 조건과 일치.

20 · 2026-11-20 09:46:03 KST · integration-basket · 실행 중 — 고정된 입력으로 검사 시작.

21 · 2026-11-20 09:46:03 KST · integration-basket · 통과 — 관찰값이 고정된 통과 조건과 일치.

22 · 2026-11-20 09:46:03 KST · bb-context · 실행 중 — 고정된 입력으로 검사 시작.

23 · 2026-11-20 09:46:03 KST · bb-boundary · 실행 중 — 고정된 입력으로 검사 시작.

24 · 2026-11-20 09:46:03 KST · system-receipt · 실행 중 — 고정된 입력으로 검사 시작.

25 · 2026-11-20 09:46:03 KST · system-device · 차단 — 필수 실행 능력 미제공 · physical\_device

26 · 2026-11-20 09:46:03 KST · link-ledger · 미실행 — 선택적 장부 연동은 이번 범위에서 제외.

27 · 2026-11-20 09:46:03 KST · bb-context · 통과 — 관찰값이 고정된 통과 조건과 일치.

28 · 2026-11-20 09:46:04 KST · system-receipt · 통과 — 관찰값이 고정된 통과 조건과 일치.

29 · 2026-11-20 09:46:04 KST · bb-boundary · 실패 — 10,000원 주문에 배송비 3,000원이 청구됨.

30 · 2026-11-20 09:46:04 KST · bb-goal · 실행 중 — 고정된 입력으로 검사 시작.

31 · 2026-11-20 09:46:04 KST · bb-goal · 통과 — 관찰값이 고정된 통과 조건과 일치.
