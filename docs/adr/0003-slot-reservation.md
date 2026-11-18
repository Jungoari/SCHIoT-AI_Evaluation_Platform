# 0003. 제출 횟수: 좌석 예약 방식 + 행 잠금

- 날짜: 2026-11-19 · 상태: 채택

## 맥락
RFP p.5: 성공 1회 차감, 형식·시스템 오류 미차감, 부적합은 차감 유지. 단순히 "남은 횟수 확인 → 채점 후 차감"으로 만들면 남은 1회에서 동시에 여러 번 제출할 때 모두 통과한다 (TOCTOU 경쟁조건).

## 결정
- 업로드 시작 시 사용자 Membership 행을 `SELECT … FOR UPDATE` 로 잠그고 슬롯을 `RESERVED`
- 채점 성공 `USED` / 오류 `RELEASED` / 부적합 판정은 `USED` 유지
- 업로드가 유예 시간 안에 끝나지 않은 티켓은 자동 만료 → 슬롯 반환

## 결과
- `test_C04_concurrent_submissions_respect_limit`: 동시 10건 중 정확히 1건
- 집계 쿼리가 단순 (`slot in (RESERVED, USED)`)
