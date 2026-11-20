# RC.2 후속 검증

고친 대상은 로컬 프로젝트 실행 증거다. 정규 `record.json`의 스키마 1.0과 기존 기록의 해시는 유지한다. [이전 RC.2 검증](verification-rc2.ko.md)과 [원래 한·영 안내](history-rc2/)는 당시 바이트를 보존했다.

## 입력과 수정

- 두 입력 패치 SHA-256은 `f09548f2cc790b54181dfa70d0aaa8d12934c7e990484e2297add8fd7e75231f`, `9c14ef7475e91d80edc7fef631e905930b7e51c25fdd6d92d82df7249b2ec245`다. 각각 원래 RC.2 트리와 공개 MIT RC.1 기준 트리에 적용했을 때 같은 트리 `78a9b891d25dad87f93db6876d38eccffdf8aef4`가 나왔다. 그 판의 `itr.py` UTF-8 출력과 Git의 바이트 보존 규칙을 반영했다.
- 기존 프로젝트 기록은 승인과 정규 기록의 버전 표지가 없는 RC.1 및 원래 RC.2 계약으로 검증한다. 새 기록은 승인·정규 기록 확장·개별 증거에서 버전 2.0을 맞춘다. 증거에서 `launch_argv`가 없다는 이유만으로 버전을 낮추지 않는다.
- 새 `launch_argv`에는 `Popen`에 건넨 실행 파일 절대 경로와 인수 배열을 넣는다. 프로세스를 부르기 전에 차단된 경우는 명시적 `null`이다. 호출을 시도한 경우에는 경로와 인수를 남기고 실제 결과는 종료 코드·관찰로 따로 확인한다. 승인 지문에는 실행 플랫폼과 외부 실행 경로의 해시도 들어간다. 새 실행 전 `inspect`가 필요하다.
- 기존 프로젝트 기록의 `verify`, 새 Markdown·인쇄 HTML·리플레이에서 실제 실행 인수 미기록을 표시한다. 기존 출력과 실행 기록은 새 보고서를 만들 때 그대로 남는다. 이 검증은 로컬 해시와 계약의 일관성을 확인한다.

## Linux에서 확인한 범위

| 검사 | 결과 |
|---|---|
| 일반 프로젝트·합성 회귀 | 11/11 그룹, 5/5 그룹. 정상 인수, 필수 키가 빠진 증거, 호출 전 차단을 각각 확인했다. CP949 부모 설정을 자식 환경에만 주고 `itr.py`의 UTF-8 출력을 읽었다. |
| 기존 기록과 재보고 | 동봉 기록 7/7. 원래 RC.2 후보 러너와 새 러너로 각각 새 저장소에 만든 실행(각 증거 2개)을 새 검증기로 읽었다. 두 기록을 다시 보고하고 원본 파일 해시를 모두 대조했다. 각 PDF 4쪽의 본문이 해당 인쇄 HTML과 같았고, 동봉 PDF 13쪽도 통과했다. |
| 진행·리플레이 | 9/9 반복에서 공유 오류 모의·종료 시 게시·지속 잠금 차단을 확인했다. DOM 모형에서 진행 11개 상태와 리플레이 32개 위치를 확인했다. |
| 릴리스 | 전체 매니페스트, ZIP 내용, Git 이력과 PDF의 추출 본문·속성·내장 첨부를 공식 릴리스 검사기로 점검했다. `core.autocrlf=true`로 새 체크아웃한 파일은 정본과 바이트가 일치했다. |

이번 후보의 Windows 네이티브 실행과 PowerShell 5.1 실행은 후속 검증 대상이다. 위 숫자는 Linux 결과이며, 실제 브라우저 픽셀과 모션은 측정하지 않았다.

## 재현

깨끗한 공개 MIT 기준에 누적 패치를 적용한다. Windows에서 기준 파일이 이미 CRLF로 체크아웃돼 있다면 패치 적용용으로 LF를 보존한 새 복제본을 사용한다. 후보의 `.gitattributes`는 이후 체크아웃에서 Git의 줄바꿈 변환을 끈다.

```powershell
git apply --check --index ITR-rc2-followup-reviewed.patch
git apply --index ITR-rc2-followup-reviewed.patch
py -3.11 -B qa/check_project.py
py -3.11 -B qa/check_progress.py
py -3.12 -B qa/check_project.py
py -3.12 -B qa/check_progress.py
```

Linux에서는 `python3`으로 같은 테스트를 실행한다. [Git 속성 문서](https://git-scm.com/docs/gitattributes)
