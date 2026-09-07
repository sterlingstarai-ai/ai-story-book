# 아동 사진 처리와 AI 제공자 대안

확인일: 2026-09-07. 공식 문서를 실제 열어 비교한 사전 조사다. 새로운 계정 신청·외부 문의 전송·약관 수락·결제·제공자 전환은 하지 않았다. 기존 OpenAI 상담 전송과 회신 확인은 별도 진행 중이다. 이 문서는 법률상 허가나 개별 계정의 승인 증거가 아니다.

검토한 제품은 **부모가 자녀 사진을 올림 → 동화풍 대표 캐릭터 한 장 → 부모 최초 승인 → 이후 책에 고정 재사용**이다. 아이가 같은 앱에서 완성된 책을 읽는 경험도 포함한다. 책마다 대표 캐릭터를 다시 만드는 설계로 바꾸지 않는다.

## 판단

**Claude와 Gemini에도 ZDR이 있다. 그러나 단순 제공자 교체만으로 현재 사진 기능의 조건이 해결됐다고 볼 수 없다.** Claude는 글·사진 분석·검수의 대안이고, Gemini는 그림 생성의 기술적 대안이지만 별도의 서비스 연령 제한이 있다. OpenAI는 기존 상담과 별도로 공식 영업 문의 경로를 확보했다.

| 경로 | ZDR | 우리 흐름에서의 의미 |
|---|---|---|
| OpenAI 직접 API | 사전 승인 후 조직·프로젝트 적용 | 사진 이해와 그림 편집을 같은 제공자로 처리할 수 있다. 아동 개인정보 조건·계정 승인·모델/엔드포인트 적용 확인이 남는다. |
| Anthropic Claude API | 영업팀을 통한 조직별 약정·활성화 | 본문·사진 분석·검수 후보. Claude 자체는 사진을 동화풍 그림으로 생성하거나 편집하지 못한다. 이미지 제공자가 추가로 필요하다. |
| Gemini Developer API / AI Studio | 프로젝트별 ZDR 요청 승인 제도 있음 | 이미지 생성·편집 가능. 다만 18세 미만 대상 또는 접근 가능성이 높은 앱 제한이 별도로 있어 우리 앱 허용 여부를 먼저 확인해야 한다. |
| Google Cloud Vertex 계열 | abuse logging 예외 신청 등 구성별 조건 | 문서상 신청 경로가 있으나 Cloud 약관에도 연령 제한이 있다. Vertex로 이동하면 자동 해결된다고 가정하지 않는다. |

## OpenAI: 지원 채팅 외에 준비한 경로

- [데이터 관리 문서](https://developers.openai.com/api/docs/guides/your-data)는 ZDR 자격 문의 대상으로 [영업팀 신청 양식](https://openai.com/contact-sales/)을 직접 연결한다. 기존 Help Center 채팅은 담당자 접수번호·실질 답변이 아직 확인되지 않았다. 새 영업 문의는 준비만 했으며 전송하지 않았다.
- [영업 문의 안내](https://help.openai.com/en/articles/9047878-how-can-i-contact-sales)는 모든 문의에 답하지 못할 수 있고 지원팀도 영업 회신을 앞당기거나 진행 상태를 제공하지 못한다고 안내한다. API Enterprise 설명에는 월 약 $10,000 이상 사용 고객의 문의를 안내하지만, **이 금액을 ZDR의 공개된 절대 최소 비용이라고 단정할 근거는 없다.** 개인·소규모 베타의 자격과 별도 계약 필요 여부를 직접 확인해야 한다.
- [미성년자 지침](https://developers.openai.com/api/docs/guides/safety-checks/under-18-api-guidance)은 13세 미만 또는 해당 디지털 동의 연령 아동의 개인정보 처리 전 ZDR 구현을 안내한다. 부모가 조작하거나 출력이 동화풍인 경우의 명시적 면제는 찾지 못했다. 우리 흐름에 이 조건을 적용하는 것은 문구에 근거한 판단이며 서비스별 답변을 요청했다.
- GPT Image 계열의 ZDR 호환성과 계정에 ZDR이 실제 적용된 상태는 다르다. 이미지 안전 검사에서 잠재적 CSAM으로 분류된 경우에는 ZDR에서도 검토용 보관 예외가 있다. 단순 학습 미사용이나 `store=false`를 전체 보관 제외로 설명하지 않는다. [데이터 관리 문서](https://developers.openai.com/api/docs/guides/your-data)

## Claude: 글·검수 대안으로 확보

- [미성년자용 제품 지침](https://support.claude.com/en/articles/9307344-responsible-use-of-anthropic-s-models-guidelines-for-organizations-serving-minors)과 [개발자 아동 안전 안내](https://support.claude.com/en/articles/15591275-child-safety-guidance-for-developers)는 보호조치·관련 법 준수·AI 사용 고지와 직접 상호작용하는 미성년자 제품의 추가 요구를 설명한다. **확인한 문서에는 OpenAI처럼 모든 under-13 개인정보 처리 전에 ZDR을 요구하는 동일 문장은 없다.** 부모용 서비스의 무조건 허용이나 면제로 확대하지 않는다.
- [상용 데이터 보관](https://privacy.claude.com/en/articles/7996866-how-long-do-you-store-my-organization-s-data)은 일반 API 입력·출력의 기본 30일 이내 삭제와 Files·법률·정책 위반 관련 예외를 설명한다. [상용 학습 정책](https://privacy.claude.com/en/articles/7996868-is-my-data-used-for-model-training)은 기본 학습 미사용이다. 두 조건 모두 ZDR과는 구분한다.
- [API ZDR 문서](https://platform.claude.com/docs/en/manage-claude/api-and-data-retention)는 조직별 활성화 및 [영업팀 신청](https://claude.com/contact-sales)을 안내한다. 일반 Messages API는 대상이며 Files·Batch 등에는 별도 보관 정책이 적용된다. 최신 일부 모델은 특별 승인 없이는 30일 보관이 요구되므로 전환 시 정확한 모델까지 확인한다. 소규모 계정의 승인 일정·최소 지출은 미확인이다.
- [Vision 문서](https://platform.claude.com/docs/en/build-with-claude/vision)는 이미지 이해만 가능하며 이미지 생성·편집은 불가하다고 명시한다. 같은 문서의 요청 후 이미지 자동 삭제 설명을 프롬프트·출력·안전 로그 전체에 대한 보관 면제로 확대하지 않는다.

## Gemini / Google Cloud: 그림 대안이지만 연령 조건 우선

- [Gemini API 약관](https://ai.google.dev/gemini-api/terms)의 Age Requirements는 18세 미만 대상 또는 접근 가능성이 높은 앱에 API를 넣지 못하도록 한다. 무료 서비스에는 개인정보 제출 제한과 학습·사람 검토 가능성이 있고, 유료 서비스는 학습 개선에서 제외해도 안전 로그 보관이 남는다. 유료 연결만으로 연령 제한이나 ZDR이 해결되지 않는다.
- [Gemini Developer API ZDR](https://ai.google.dev/gemini-api/docs/zdr)은 프로젝트별 요청 승인 후 로그에서 콘텐츠·식별 메타데이터를 제거한다고 명시한다. Search/Maps grounding, Files, 명시적 캐시 등은 따로 고려해야 한다. 문서에서 소규모 고객의 자격·처리 기간·직접 신청 양식까지는 확인하지 못했다.
- [Google Cloud 서비스별 약관](https://cloud.google.com/terms/service-terms)의 Generative AI Services §20(d)에도 같은 연령 제한이 있다. **부모가 생성하고 아이가 책을 읽는 현 제품을 부모 계정이라는 이유만으로 예외라고 확정할 수 없다.** ZDR 승인만 받아도 이 연령 제한이 자동 해제되는 것은 아니다.
- [Cloud 보관 안내](https://docs.cloud.google.com/gemini-enterprise-agent-platform/resources/zero-data-retention)와 [abuse monitoring](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/abuse-monitoring)의 Customer opt-out에 공식 예외 신청 링크가 있다. 일반 GCP 약관 고객의 의심 프롬프트 로그는 최대 90일일 수 있으며, 예외 승인 시 처리 조건이 달라진다. Master Agreement 고객의 기본 면제를 현재 일반 API 계정에 적용했다고 추정하지 않는다. 신청 양식 링크는 확인했으나 양식 내용은 열람 오류로 확인하지 못했고 제출하지 않았다.
- [Gemini 이미지 편집](https://docs.cloud.google.com/gemini-enterprise-agent-platform/models/capabilities/gemini-edit-images)은 사진을 카툰으로 바꾸는 기술 경로를 설명한다. 기술 지원이 아동 사진 처리나 앱 약관 허용의 증거는 아니다. 기존 Vertex 문서 일부는 현재 Gemini Enterprise Agent Platform 경로로 이동하며, 이를 기존 프로젝트의 계약·설정 변경으로 해석하지 않는다.

## 다음에 확인할 질문과 전환 기준

1. **OpenAI:** 개인·소규모 부모용 베타의 ZDR 자격, 신청 담당 부서, 원본 사진·식별 가능한 파생 캐릭터, 정확한 모델·엔드포인트, 비용·계약·보관 예외를 함께 문의한다. 영업 양식용 초안은 비공개 acceptance 폴더에 준비했다. 매출·예상 사용액·법인 여부를 임의로 만들어 기재하지 않는다.
2. **Google:** 성인 부모가 계정·업로드·생성·승인을 하고 아이가 완성된 책을 읽는 구체적 흐름이 연령 조항에 허용되는지를 먼저 묻는다. 허용된다면 이미지 편집 모델과 Developer API/Cloud 중 적용 경로, ZDR 신청·승인 범위를 확인한다.
3. **Anthropic:** 부모용 사진 분석·본문·검수 용도의 조건과 일반 모델 ZDR을 확인한다. 별도의 이미지 생성사 문제가 남으므로 Claude만으로 대체 완료라고 판단하지 않는다.
4. **전환 판단:** 용도 허용 → 보관 조건과 모델 범위 확인 → 실제 사진 변환·닮음 및 한 권 전체 품질 검증 → 비용·지연 비교 순으로 판단한다. 기존 모의 테스트나 가상 이미지 결과를 실사진 승인·품질 증거로 대체하지 않는다.

원본을 먼저 그림이나 외모 설명문으로 바꾸더라도 식별 가능한 파생 정보가 자동으로 익명화되는 것은 아니다. 승인 대기를 피한다는 이유만으로 이런 중간 변환을 우회책으로 확정하지 않는다. 현재 제공자 설정과 사진 기능 비활성 상태는 유지하며, 책 전체의 자동 삽화 품질 검증은 별도의 남은 개발 작업이다.
