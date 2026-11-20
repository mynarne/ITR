# RC 배포 전 점검과 최초 비공개 원격 생성

제품을 사용하면서 생긴 시도 저장소는 **배포 폴더 밖**에 둔다. 이 문서에서 검토하는 대상은 ITR 소스, 고정된 합성 예제, 배포용으로 정리한 검증 결과다. GitHub 단계는 저장소 생성·푸시 권한을 받은 담당자가 자기 환경에서 수행하는 절차다. 인증이 없으면 로컬 후보와 ZIP까지 준비하고 원격 상태를 “미실행”으로 남긴다.

## 파일 출처를 먼저 확인한다

| 대상 | 포함 조건 |
| --- | --- |
| 스킬·소스·문서 | 이번 후보를 위해 작성했거나 출처와 배포 권한을 확인한 파일. README 코드·주석·예제 링크·작성자명과 파일 경로까지 직접 읽는다. |
| 동봉된 0.1 시도 | 공개 가능한 합성 영수증 데이터. 이전 manifest의 SHA-256과 개별 시도 파일 바이트가 일치해야 한다. 시도 전체가 수록되어야 연결을 재검증할 수 있다. |
| 신규 재고 샘플 | 두 Python 파일과 두 계획, 해당 계획으로 실행한 시도 2건(총 36개 파일)을 포함한다. 두 시도의 COMPLETE 지문과 개별 파일 해시를 고정하고 소스·계획 바이트 및 수량별 실제 stdout을 대조했다. 1차(계획 2건)는 통과, 2차(계획 3건)는 0개 재고에서 low를 출력해 1건 실패했다. 다른 프로젝트의 실행 저장소는 배포 대상 밖에 둔다. |
| 제품 자체 검사 | 재현 가능한 계획과 출처를 확인한 결과 요약을 넣는다. 실제 프로젝트의 소스 스냅샷, 원시 stdout·stderr, 세션·브라우저 로그와 고객 자료는 별도 로컬 저장소에 보관한다. |
| 화면·PDF | 내장 JSON, 로그 텍스트, 이미지, 첨부, 링크 목적지, PDF 속성까지 살핀다. 원자료가 비공개라면 파일명을 바꾸거나 해시를 더한 것만으로 공개 가능해지지 않는다. |
| Git | 새 후보 폴더에서 시작한 독립 이력을 쓴다. 원본 저장소의 커밋, 태그, 브랜치, 원격 설정과 메타데이터를 복사하지 않는다. |

사람 이름·서명, 실계정명·메일·연락처, 회사·내부 프로젝트·도메인명, 고객 식별자, 자격 증명, 비공개 절대 경로, 운영 데이터가 있는지 출처를 아는 사람이 검토한다. 필요한 경우 후보 밖의 비공개 텍스트 파일에 조직명·개인명 등 식별 문자열을 한 줄씩 두고 `--private-terms FILE`을 추가한다. 목록과 검출값을 릴리스 기록에 넣지 않는다.

## 로컬 점검

후보 루트에서 실행한다. ZIP은 배포 폴더의 바깥에 만든다. PDF 점검에는 Poppler의 pdfinfo, pdftotext, pdfdetach가 필요하다. Git 이력까지 점검할 때는 Git이 필요하다.

```sh
python3 -B qa/check_release.py --root .
python3 -B qa/check_release.py --root . --zip ../ITR-1.0-rc1.zip
python3 -B qa/check_release.py --root . --zip ../ITR-1.0-rc1.zip --git
```

검사기는 등록한 상대경로, UTF-8 본문, 알려진 자격 증명·개인 연락처 패턴, URL의 호스트, PDF 추출 텍스트·문서 정보·XMP·첨부 및 활성 스크립트를 확인한다. ZIP 또는 Git 게이트는 RC의 전체 구성과 최상위 MANIFEST.sha256을 먼저 확인한다. ZIP 파일 목록과 압축 해제한 각 멤버의 SHA-256을 점검한 폴더와 대조한다. ZIP에 별도 주석이나 부가 필드가 있으면 중단한다. Git 검사는 로컬 HEAD의 추적 파일 및 바이트, 참조가 닿는 커밋의 작성자·커미터·메시지·파일 경로·내용을 확인한다. 소스 전용 검사에서 Git 커밋 수 0 또는 ZIP skipped가 나오면 해당 게이트는 아직 수행하지 않은 상태다.

자동 검사는 파일 출처·재배포 권리, 이미지 속 문자, 개인정보로 쓰인 일반 단어, 인코딩되거나 난독화된 값까지 판별하지 못한다. PDF를 실제로 열어 페이지·링크·숨은 요소를 검토하고 Git 기본 브랜치·전송 대상과 staged diff를 사람이 확인한다. 자료가 잘못 포함됐다면 전송 전 깨끗한 배포 후보 폴더를 다시 만들고 이력까지 재검사한다. 민감 원본을 커밋했다가 다음 커밋에서 삭제하는 방식은 이전 이력을 남긴다.

## 최초 로컬 커밋

작업공간 전체를 대상으로 초기화하지 않는다. 먼저 승인된 전용 후보 루트인지, 상위 프로젝트의 .git을 물려받거나 기존 원격·이력을 재사용하지 않는지 확인한다. 새 후보에만 다음을 적용한다. 두 번째부터는 이미 감사한 기존 로컬 후보를 확인한다.

```sh
git init -b main
git config --local user.name "ITR Release"
git config --local user.email "itr@invalid.example"
git config --local user.useConfigOnly true
git add -- .
git diff --cached --stat
git diff --cached --check
git commit -m "Prepare ITR 1.0 RC1"
python3 -B qa/check_release.py --root . --zip ../ITR-1.0-rc1.zip --git
git rev-parse HEAD
```

커밋의 author와 committer 모두 위의 비개인 신원을 써야 한다. 환경 변수가 로컬 설정을 덮을 수 있으므로 커밋 후 검사 결과를 확인한다. 루트 커밋·검사한 소스와 ZIP·로컬 HEAD SHA를 별도 인계 메모에 기록한다.

## GitHub 최초 도입 · 운영자 개인 소유의 새 비공개 ITR

아래 단계에서 `ITR_OWNER`는 운영자가 지정한 **정확한 계정명**이다. 실계정 이름이나 인증 수단을 배포 파일에 저장하지 않는다. GitHub CLI가 이미 승인된 계정에 연결돼 있어야 한다. GitHub 호스트를 명시한다. 조직 소유 후보는 조직과 생성 권한을 별도로 확인해야 하므로 이 개인 소유 절차에서 생성하지 않는다.

1. `gh api --hostname github.com user --jq .login` 결과를 승인된 소유자와 비교한다. 다른 사용자, 인증 오류, 조회 불가 상태에서는 생성·전송을 중단한다.
2. `gh repo view "github.com/$ITR_OWNER/ITR" --json nameWithOwner,visibility`로 기존 저장소를 조회한다. **기존 저장소가 확인되면 멈춘다.** 비공개 저장소도 접근 권한이 없으면 404일 수 있다. 소유자·호스트·권한과 오류 종류를 확인하고 필요하면 소유자가 비공개 저장소 목록에서도 확인한다. 인증·권한·네트워크 오류를 빈 저장소로 간주하지 않는다.
3. 새 개인 비공개 저장소 생성이 승인됐고 이름 충돌이 없는 것으로 확인됐을 때 생성만 수행한다. 반환된 저장소 ID, 전체 이름, private 여부를 로컬 인계 기록에 보관한다. 자동 초기화는 꺼둔다.

```sh
gh api --hostname github.com --method POST user/repos \
  -f name=ITR -F private=true -F auto_init=false \
  --jq '[.id, .full_name, .private, .html_url] | @tsv'
```

4. 생성이 성공하면 아래 읽기 결과의 ID와 소유자·전체 이름이 영수증과 일치하고 private 값이 true인지 확인한다. 타임아웃이나 결과 불명 시에는 **이 조회부터** 수행한다. 이미 생성된 저장소가 이번 작업에서 새로 생겼다는 점까지 확인할 수 없으면 푸시를 보류한다. 기존 이름 충돌 응답을 받은 저장소에는 쓰지 않는다. 생성 재시도는 미실행을 확인한 경우에만 가능하다.

```sh
gh api --hostname github.com "repos/$ITR_OWNER/ITR" \
  --jq '[.id, .full_name, .private, .default_branch] | @tsv'
```

5. 생성 영수증과 검증한 URL을 사용해 **원격이 없던 전용 후보**에 origin을 한 번 추가한다. 이미 origin이 있으면 먼저 그 주소와 생성 영수증을 대조한다. 알 수 없는 원격을 덮어쓰지 않는다. 아래 URL에는 자격 증명을 포함하지 않는다.

```sh
git remote add origin "https://github.com/$ITR_OWNER/ITR.git"
git ls-remote --symref origin
```

6. 정상 종료한 전체 ref 조회가 비어 있는지 확인한다. 기존 브랜치·태그·커밋이 보이거나 조회 권한을 확인할 수 없으면 중단한다. 로컬 상태와 HEAD SHA, ZIP 검사, 원격 ID·비공개 상태를 최종 대조한 뒤 승인된 main 브랜치만 한 번 푸시한다. 강제 푸시, 미러, 태그 일괄 전송은 사용하지 않는다.

```sh
git push --set-upstream origin refs/heads/main:refs/heads/main
git ls-remote --symref origin HEAD refs/heads/main
gh api --hostname github.com "repos/$ITR_OWNER/ITR" \
  --jq '[.id, .full_name, .private, .default_branch] | @tsv'
```

7. 원격 HEAD가 main을 가리키고 원격 main의 전체 SHA가 검사한 로컬 SHA와 같은지 확인한다. GitHub 응답의 ID, private=true, 기본 브랜치 main도 대조한다. 푸시 응답이 불명확하거나 시간 초과면 재시도에 앞서 똑같은 읽기부터 한다. 이미 일치하면 완료, 불일치·예상치 못한 ref면 보류한다. 체크가 구성된 저장소는 같은 SHA의 체크 실행과 상태를 확인한다. 체크가 없는 새 저장소는 “원격 체크 미구성”으로 기록하고 로컬 검증 근거를 함께 인계한다.

검사한 로컬 SHA를 ITR_SHA에 두고 아래 읽기로 GitHub 체크 실행 건수·상태와 커밋 상태 건수를 확인한다. 원격에서 요구하는 체크가 있다면 미완료 또는 실패한 체크가 해소되기까지 원격 체크 통과 판정을 보류한다.

```sh
gh api --hostname github.com "repos/$ITR_OWNER/ITR/commits/$ITR_SHA/check-runs" --paginate \
  --jq '[.total_count, [.check_runs[] | {name, status, conclusion}]]'
gh api --hostname github.com "repos/$ITR_OWNER/ITR/commits/$ITR_SHA/status" \
  --jq '[.total_count, .state]'
```

API 동작과 명령의 근거는 GitHub의 [저장소 REST API](https://docs.github.com/en/rest/repos/repos), [CLI 명령](https://cli.github.com/manual/gh_api), Git의 [원격 참조 조회](https://git-scm.com/docs/git-ls-remote)와 [푸시](https://git-scm.com/docs/git-push)에서 확인할 수 있다.
