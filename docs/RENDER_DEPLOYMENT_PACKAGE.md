# Render 실행 준비 패키지

> 2026-09-08: [운영·릴리스 배선 보완](DEPLOYMENT_WIRING_2026-09-08.md)을 함께 확인합니다. 아래는 최초 준비 시점의 기록이며, 신규 결제와 서비스 활성화는 계속 보류 중입니다. Apple 기본 공개 root CA는 앱에 번들되고 `APPLE_ROOT_CA_PATHS`는 선택 override입니다. override 인증서·Google 서비스 계정 파일을 쓰면 API와 worker 둘 모두에 읽기 전용으로 공급합니다.

2026-09-06. 현재 산출물은 **유료 서비스 활성화 전 검토용 구성**입니다. 개발용 무료 Render 작업공간만 준비했고 유료 서비스 활성화·commit/push·이미지 배포를 실행하지 않았습니다. 대상 저장소는 `https://github.com/sterlingstarai-ai/ai-story-book`이며 공개 저장소이므로 개인 자료·계정 정보·키를 제외한 출시 소스만 전송 대상으로 검토합니다.

## 파일과 초기 월 구성

- `infra/render.yaml.template`: 새 API·워커·Key Value 3개 서비스의 확정 가능한 구성. 미확정 이미지 자리표시자가 있어 그대로 배포할 파일이 아닙니다.
- `scripts/prepare_render_blueprint.py`: 명시한 CI/이미지 증거를 검사하고 새 `render.yaml`을 생성하는 오프라인 도구. `.env`·계정·레지스트리를 읽거나 서비스를 생성하지 않습니다.
- `infra/render-release.example.json`: 필요한 release manifest 형식. 실제 검증 전 예제 그대로는 차단됩니다.
- `apps/api/src/ops/render_entrypoint.py`: Render의 내부 Redis connectionString에서 기존 DB 0/1/2를 보존하고 TLS/CA 조건을 확인한 뒤 기존 API·Celery·Alembic 명령으로 프로세스를 교체합니다.

| 서비스 | Blueprint plan | 인스턴스 | 기본 월 추정 |
| --- | --- | ---: | ---: |
| API | `0.5c-512mb` | 1 | $7 |
| Celery 워커 | `1c-2g` | 1 | $25 |
| Key Value | `256mb` | 1 | $10 |
| 별도 Supabase 전용 Pro 프로젝트 | Blueprint에서 생성하지 않음 | 1 | $25 |
| 합계 | 초기 구성 | | **$67/월** |

금액은 [실계정·가격 검토](HOSTING_ACCOUNT_REVIEW_2026-09-06.md)의 기본 추정이며 세금·환율·AI 생성·초과 트래픽·별도 암호화 미디어 백업 비용을 포함하지 않습니다. 워커 메모리는 초기 선택값이며 처리 용량 측정 결과가 아닙니다. [공식 compute plan 식별자](https://render.com/docs/compute-plans), [가격](https://render.com/pricing)

## 설정 결정

API·워커는 `runtime: image`를 사용하고 CI가 만든 동일 commit SHA 태그 또는 명시적으로 확인한 digest만 받습니다. Dockerfile 원격 빌드나 `latest` 태그로 현재 미커밋 변경을 배포했다고 간주하지 않습니다. 비공개 GHCR 이미지는 Render Workspace의 읽기용 Registry Credential 이름으로 참조합니다. 키 자체는 YAML에 쓰지 않습니다. [공식 이미지 규격](https://render.com/docs/blueprint-spec#image), [GHCR 인증](https://render.com/docs/deploying-an-image#credentials-for-private-images)

기본 지역은 `singapore`이며 API·worker·Redis를 같은 지역에 둡니다. Supabase 지역과 실제 국외 처리 조건은 계정 구성 시 함께 확인합니다. 기존 다른 서비스를 같은 이름으로 인수하지 않습니다. 새 서비스에 한해 `numInstances: 1`, autoscaling 미설정, preview `off`로 생성합니다. 기존 서비스는 autoscaling 설정이 유지될 수 있어 이 템플릿의 대상에 포함하지 않습니다.

Key Value는 `ipAllowList: []`, `maxmemoryPolicy: noeviction`, `persistenceMode: journal-snapshot`입니다. API가 `fromService: connectionString`을 받고 worker가 같은 값을 참조합니다. entrypoint가 실제 URL의 사용자명·암호를 유지한 채 앱/브로커/결과 DB를 0/1/2로 분리합니다. 비밀값은 프로세스 argv나 로그에 넣지 않습니다. [Key Value 구성](https://render.com/docs/blueprint-spec#render-key-value), [서비스 값 참조](https://render.com/tutorials/advanced-blueprint-patterns/cross-service-wiring)

API의 `/health/ready`를 플랫폼 health check로 사용하고 원래 Uvicorn의 마스킹 없는 access log는 계속 비활성화합니다. 신규 구매·사진 처리·오디오·POD는 비활성 상태이며 그림 품질 검사와 IAP strict 조건을 유지합니다. 활성화는 각 공급자·스토어·사진 처리 조건을 확인한 뒤 별도 변경합니다.

## CA와 비밀값 공급

`DATABASE_URL`, S3/AI/admin 자격증명 등 최초 설정 값은 API `sync: false`로 받고 worker가 API의 같은 값을 참조합니다. 추후 `sync: false` 항목 추가는 Blueprint sync만으로 적용되지 않으므로 해당 서비스의 Environment에서 확인해야 합니다. [비밀값 규칙](https://render.com/docs/blueprint-spec#prompting-for-secret-values)

CA 파일은 공식 Blueprint 필드로 선언할 수 없습니다. API·worker 양쪽의 Environment → Secret Files에 `supabase-ca.crt`를 추가하거나, 같은 파일을 담은 사전 준비된 Environment Group을 양쪽에 연결합니다. Docker runtime 경로는 `/etc/secrets/supabase-ca.crt`입니다. 두 서비스가 이 경로를 사용할 수 있는지 확인한 뒤 수동 배포합니다. 첫 서비스 생성에서 파일 공급 전 시작 시도가 생기면 entrypoint가 실패하며, 인증서를 끄는 우회는 하지 않습니다. [Secret Files와 그룹](https://render.com/docs/configure-environment-variables#secret-files)

외부 DB는 direct/session 5432 + `verify-full`, S3는 해당 프로젝트 region + `path` + 미리 만든 private bucket입니다. 공통 조건은 [외부 호스팅 배포 준비](EXTERNAL_HOSTING_DEPLOYMENT.md)를 따릅니다.

## 배포 파일 생성

1. 현재 최종 소스를 검증하고 승인된 저장소에 commit/push한 뒤, 해당 commit의 CI와 API/worker 이미지 build·registry 접근을 확인합니다. 이 준비 작업은 commit/push하지 않았습니다.
2. 예제를 별도 release manifest로 복사해 실제 commit SHA, 두 이미지, 성공한 이 저장소의 Actions run URL을 기록합니다. 도구는 증거 형식을 검사하지만 CI·registry에 접속해 그 내용을 인증하지는 않으므로 운영자가 원본 실행 결과를 대조해야 합니다.
3. Render에 실제 등록된 GHCR credential 이름을 사용해 새 경로로 출력합니다. 기존 파일은 덮어쓰지 않습니다.

```bash
./apps/api/venv/bin/python scripts/prepare_render_blueprint.py \
  --release-manifest /private/verified-render-release.json \
  --registry-credential-name ai-story-book-ghcr-read \
  --output infra/render.yaml
```

이 명령은 월 비용을 승인하거나 결제하지 않습니다. 성공 상태도 `BLUEPRINT_PREPARED_NOT_DEPLOYED`입니다. 필요하면 `--service-prefix`와 `--region`을 지정합니다. Python `jsonschema`가 있는 검증 환경에서는 공식 스키마를 로컬 파일로 받아 `--schema-file`로 추가 검사할 수 있습니다.

현재 로컬에는 Render CLI가 없으므로 계정 기반 CLI 검증은 실행하지 않았습니다. 인증된 CLI v2.7 이상이 준비되면 `render blueprints validate infra/render.yaml`로 계정에 연결된 리소스 참조와 구성 오류를 다시 검사합니다. Registry의 이미지 접근과 실제 계정 권한은 별도로 확인합니다. 최종 `infra/render.yaml`이 원격 저장소에 있고 Blueprint Path를 그 경로로 지정한 이후에만 [이 저장소의 Blueprint 설정 화면](https://dashboard.render.com/blueprint/new?repo=https://github.com/sterlingstarai-ai/ai-story-book)을 사용합니다. 지금 템플릿/합성 증빙을 Apply하지 않습니다. [검증·Blueprint 경로 규격](https://render.com/docs/blueprint-spec#validating-blueprints)

## 과금 승인 후 실행 순서와 계정 확인

1. 전용 Supabase 프로젝트·private bucket, Render Workspace·읽기용 registry credential, CA·서버 비밀값을 준비합니다. 다른 서비스의 프로젝트나 데이터베이스를 재사용하지 않습니다.
2. 최초 운영 생성 전에 확정 이미지로 외부 DB를 Alembic head까지 마이그레이션합니다. 이후 API pre-deploy 명령도 같은 마이그레이션을 수행합니다. Blueprint는 worker와 API의 배포 완료 순서를 보장하는 별도 도구가 아니므로, 처음부터 빈 DB를 worker가 먼저 사용하게 두지 않습니다.
3. 새 서비스명·지역·세 요금제를 계산서와 대조하고 승인된 창에서만 Apply합니다. CA/비밀값·pre-deploy 성공 후 API health와 worker 연결을 확인합니다. 처음 CA 공급 전에 실패한 배포는 올바른 파일을 공급한 뒤 수동으로 재개합니다.
4. Blueprint Settings의 **Auto Sync = No**를 확인합니다. `autoDeployTrigger: off`는 YAML에 명시했지만 image-backed 서비스에서는 이 필드가 자동 배포를 제어하지 않습니다. image-backed 서비스는 새 tag 대상 변경을 자동 배포하지 않으며, Blueprint 자체의 기본 Auto Sync는 별도 계정 설정입니다. [Auto Sync](https://render.com/docs/infrastructure-as-code#disabling-automatic-sync), [이미지 배포 동작](https://render.com/docs/deploying-an-image#triggering-a-deploy)
5. 배포/업데이트 전 새 쓰기를 막고 queued/running 작업이 0개가 된 뒤 worker를 교체합니다. 현재 작업 SLA 기본 600초에 비해 Render의 graceful shutdown 최대는 300초이므로, 이 구성으로 처리 중인 긴 작업의 무중단 교체를 보장하지 않습니다. API·worker는 허용 최대 300초를 지정하고 원래 프로세스에 SIGTERM을 전달합니다. [종료 제한](https://render.com/docs/deploys#graceful-shutdown)
6. `/health/ready`, 같은 부모의 연속 생성 2건, 서명 다운로드/익명 차단, 소유권·동의 철회·삭제, DB/미디어 격리 복원을 실제 호스트에서 확인합니다. [백업 계약](BACKUP_RESTORE.md)을 충족하기 전 재해 복구 완료로 표시하지 않습니다.

## 현재 검증 증거

Render 관련 focused 테스트 23개와 공식 `https://render.com/schema/render.yaml.json`에 대한 로컬 JSON Schema 검사가 통과했습니다. 합성 SHA/CI URL을 사용한 구조 검증이며 서비스 활성화·실제 registry 이미지·계정 권한 검증이 아닙니다. 검사 기록은 `docs/acceptance/2026-09-06-render-preparation/schema-validation.json`에 있고, 같은 폴더의 `synthetic-render.yaml`은 배포 대상으로 사용하지 않습니다.
