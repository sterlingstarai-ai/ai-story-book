"""M8 — 앱 버전은 코드가 정본이며 APP_VERSION env로 오버라이드되지 않는다.

로컬/배포 .env의 구값(APP_VERSION=0.2.0 잔재)이 런타임 info.version을 흔들어
계약 신선도 테스트(test_shared_openapi_contract_is_committed_and_current)를
소음화하던 결함을 회귀 방지한다.

주의: config 모듈을 importlib.reload 하지 않는다 — 전역 settings 싱글톤을 새로 만들어
다른 모듈(rate_limit 등)의 import된 참조와 어긋나 후속 테스트를 오염시킨다. app_version이
property가 되어 새 Settings() 인스턴스만으로 env 비의존을 검증할 수 있다.
"""

from src.core.config import APP_VERSION, Settings, settings


def test_app_version_not_overridable_by_env(monkeypatch):
    """APP_VERSION env를 어떤 값으로 설정해도 app_version은 코드 정본(1.0.0)."""
    monkeypatch.setenv("APP_VERSION", "9.9.9")

    # 새 인스턴스도 env·.env 잔재에 비의존(수정 전엔 필드라 9.9.9로 오버라이드됨).
    assert Settings().app_version == "1.0.0"
    # 전역 싱글톤도 동일.
    assert settings.app_version == "1.0.0"
    assert APP_VERSION == "1.0.0"
