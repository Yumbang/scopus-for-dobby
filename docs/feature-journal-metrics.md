# Feature: Journal (Serial Title) Metrics — CiteScore percentile / rank

> 상태: 제안(미구현). 2026-06-07 API 실험으로 가용성 확인됨.

## 한 줄 요약
ISSN으로 **저널 단위 지표**(CiteScore, 분야별 percentile·rank, SJR/SNIP)를 조회하는 명령을 추가한다. 현재 CLI는 article(논문) 중심이라 저널 지표 명령이 없다.

## 왜 (use case)
- "이 저널이 분야 내 **상위 N%**인가?" 판정 — 예: 연구실적 보고서의 **분야별 Top 10% 저널 논문 수** 산출.
- 보유 데이터의 Q등급(Q1~Q4)만으로는 Top 10%(상위 10%)를 가려낼 수 없음 → **percentile**이 필요.
- 논문 컬렉션의 저널 품질 요약(percentile/quartile/CiteScore 분포).

## 엔드포인트 (Scopus Serial Title API)
- 단건: `GET https://api.elsevier.com/content/serial/title/issn/{issn}?view=CITESCORE`
- 일괄: `GET https://api.elsevier.com/content/serial/title?issn=ISSN1,ISSN2,...&view=CITESCORE` (콤마 구분)
- `view`: `CITESCORE` = percentile·rank 포함 / 기본·`STANDARD` = SJR·SNIP 위주.
- Headers: `X-ELS-APIKey: {api_key}` · `X-ELS-Insttoken: {inst_token}` · `Accept: application/json`
  → 기존 `~/.scopus-for-dobby/config.json`(api_key·inst_token) 그대로 사용 가능.
- ISSN은 **하이픈 제거**(`0043-1354` → `00431354`). print-ISSN 실패 시 e-ISSN으로 재시도 권장.
- Throttle: `utils/api_client.py`의 `_THROTTLE`에 `"/content/serial/title": 0.12` 추가 권장(검색과 **별도 쿼터**로 보임).

## 응답에서 뽑을 값
경로: `serial-metadata-response.entry[0]`
- `dc:title` — 저널명
- `citeScoreYearInfoList.citeScoreCurrentMetric` — 현재 CiteScore
- `citeScoreYearInfoList.citeScoreYearInfo[]` → `citeScoreInformationList[0].citeScoreInfo[0]`:
  - `citeScore`
  - `citeScoreSubjectRank[]` → 분야마다 `{ subjectCode, rank, percentile }`
- (STANDARD view) `SJRList.SJR[]`, `SNIPList.SNIP[]`, `subject-area`
- **Top 10% 판정 규칙**: `max(percentile across subjectRanks) >= 90` (한 분야라도 상위 10%면 통상 인정). 특정 분야 기준이 필요하면 `subjectCode`로 필터.

## 예시 (실측, Water Research)
요청:
```
GET /content/serial/title/issn/00431354?view=CITESCORE
X-ELS-APIKey: ***   X-ELS-Insttoken: ***   Accept: application/json
```
응답(발췌):
```json
{"serial-metadata-response":{"entry":[{
  "dc:title":"Water Research",
  "citeScoreYearInfoList":{
    "citeScoreCurrentMetric":"21.6",
    "citeScoreYearInfo":[{"@year":"2026","@status":"In-Progress",
      "citeScoreInformationList":[{"citeScoreInfo":[{
        "citeScore":"17.1",
        "citeScoreSubjectRank":[
          {"subjectCode":"2205","rank":"4","percentile":"99"},
          {"subjectCode":"2302","rank":"1","percentile":"99"},
          {"subjectCode":"2312","rank":"4","percentile":"98"},
          {"subjectCode":"2305","rank":"5","percentile":"98"},
          {"subjectCode":"2310","rank":"6","percentile":"96"},
          {"subjectCode":"2311","rank":"6","percentile":"96"}
        ]}]}]}]}}]}}
```
→ max percentile 99 ⇒ **Top 10% ✓**

## 제안 CLI / 통합 (구현 시 참고)
- 명령: `serial <ISSN> [--view CITESCORE] [--json]` (또는 `journal metrics <ISSN>`) → CiteScore·best percentile·분야별 rank/percentile·(SJR/SNIP) 출력.
- 배치: `serial --collection <name>` → 컬렉션 논문들의 저널 ISSN을 모아 일괄 조회 → 저널별 best percentile / `is_top10` 플래그 표.
- DB enrich(선택): article 행에 `journal_citescore`·`journal_best_percentile`·`is_top10_journal` 추가 → `db list`/`export`에서 필터·집계.
- 아키텍처: 기존 패턴 따라 `core/serial.py`(API 래퍼) + `server/app.py` 엔드포인트 + `cli/serial.py` 명령.

## 주의
- **CiteScore percentile(Scopus/Elsevier) ≠ JCR JIF percentile(Clarivate).** "Top 10%"를 **JCR 기준**으로 보고해야 하는 경우 출처가 다름 → CiteScore는 **보완/참고 지표**로 명시할 것.
- 한 저널이 여러 subject category에 속하며 분야마다 percentile이 다름.
- `view=CITESCORE`는 institutional tier에서 검증함(standard 키 가용성은 별도 확인).
