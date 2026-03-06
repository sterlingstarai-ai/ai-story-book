# Acceptance Artifacts

이 디렉터리는 인수 검증 산출물의 보관 위치다.

운영 원칙:
- 기본 보관 매체는 CI/CD artifact 또는 외부 스토리지다.
- 저장소에는 템플릿/설명 파일만 유지한다.
- 타임스탬프별 실행 로그(`YYYYMMDD-HHMMSS/`)는 기본적으로 커밋하지 않는다.

권장 구조:
- `README.md`: 보관 정책
- `.gitkeep`: 빈 디렉터리 유지용
- `<timestamp>/`: 로컬 또는 CI에서 생성된 임시 검증 산출물
