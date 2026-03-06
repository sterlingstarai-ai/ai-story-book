# Golden Prompt Set

이 문서는 생성 품질 회귀 검증용 기준 프롬프트 세트를 정의한다.

운영 원칙:
- 릴리스 전 최소 1회 실행한다.
- 텍스트, 이미지, 학습 자산, 음성 자산이 모두 기대 방향을 유지하는지 비교한다.
- 회귀 비교는 이전 승인 결과와 나란히 검토한다.
- placeholder 이미지, 빈 학습 자산, 안전 필터 과잉 차단은 실패로 본다.

검증 축:
- 이야기 구조: 시작-전개-해결의 명확성
- 연령 적합성: 어휘/문장 길이/정서 강도
- 캐릭터 일관성: 외형/성격/호칭 유지
- 시각 품질: 표지와 본문 장면 연속성
- 학습 자산: vocab/comprehension/quiz 유효성
- 운영 품질: generation_warnings, asset_status, request_id 기록 여부

실행 소스:
- 구조화 데이터: `docs/qa/golden-prompts.json`
- 결과 보관: CI artifact 또는 외부 QA 저장소
