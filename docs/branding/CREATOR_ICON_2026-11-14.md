# 내가 만드는 동화 — 앱 아이콘

## 전달 목표

아이콘만 보고 **아이가 자기 동화를 만들고, 그 동화의 주인공이 된다**는 점을 알아볼 수 있어야 한다. 아이가 열린 책에서 나와 큰 연필로 이야기를 쓰는 하나의 실루엣을 사용한다. 짙은 청록 배경, 따뜻한 종이, 금색 연필과 코랄색 옷으로 작은 크기에서도 얼굴·연필·책을 구별한다.

## 원본과 재생성

- `apps/mobile/assets/icons/app_icon.png`: 불투명 1254×1254 마스터.
- `apps/mobile/assets/icons/app_icon_foreground.png`: Android 적응형 아이콘의 투명 전경. 배경 `#102E32`, 전경 inset 16.
- `apps/mobile/assets/icons/play_store_icon.png`: Google Play 등록용 불투명 512×512 PNG.
- `apps/mobile/pubspec.yaml`의 `flutter_launcher_icons` 설정과 기존 도구로 iOS·Android 아이콘을 생성한다. Flutter 패키지 의존성과 Dart 기능 코드는 변경하지 않았다.

```bash
cd apps/mobile
dart run flutter_launcher_icons
sips -z 512 512 assets/icons/app_icon.png --out assets/icons/play_store_icon.png
```

내장 이미지 생성 도구로 새 원본과 투명 전경을 제작했다. 앱 운영의 제공자 키나 실제 아이 사진을 사용하지 않았다. 스토어용 크기 변환은 생성 원본을 그대로 축소한 것이다. iOS 카탈로그의 25개 항목·서로 다른 PNG 21개와 Android 밀도 5종의 일반/적응형 자산을 대조했다. [자산 검사](../acceptance/2026-11-14-creator-icon/native-source-verification.json)

## 사용한 생성 프롬프트

### 마스터

Design ONE finished square app icon for a Korean app where a child or parent CREATES A PERSONALIZED STORY with the child as the hero. The central message must be unmistakably 'I make my own story', not merely reading books or bedtime. Original new icon, no reference reuse. Main visual: a charming gender-neutral young East Asian child author with simple dark hair, bright expressive eyes and a warm confident smile, emerging waist-up from the central fold of an open cream storybook, as though the child has become the story's own hero. The child actively holds an oversized honey-gold pencil in one hand with its tip touching the book page, clearly MAKING the story rather than just holding or reading the book. Make the child face, the pencil, and the open book ONE strong unified compact silhouette. Child upper body and face dominate the upper center, book forms the lower third, pencil is a bold clear diagonal on the side and must read at small size. A very small curved golden creative stroke from the pencil tip can imply a story coming alive, but avoid extra decorations. Refined contemporary children's editorial illustration with beautiful tactile sculpted-paper depth, soft rounded shapes, tasteful subtle lighting, premium warmth, not a generic emoji, not plastic toy rendering. Forest teal full-bleed background inspired by #102E32, warm ivory pages, honey gold pencil, muted coral clothing; clear warm/cool contrast. App uses teal and cream. Bold simplified forms and generous breathing room; meaningful artwork within the central 75 percent of the square so it survives iOS rounded and Android circular masking. Crisp and recognizable at 48 pixels. No text, no letters, no wordmark, no border or circular badge, no pre-rounded outer corners, no white frame, no phone mockup, no extra characters, no scattered stars, no separate moon. The child MAKING their own fairytale must be the first thing the viewer notices.

### Android 전경 분리

Technical production cutout for the SAME app icon. Remove ONLY the deep teal BACKGROUND and replace it with genuine transparency. Preserve the child hero, every facial feature, hair, coral cape/clothing, both hands, oversized gold pencil, the cream open storybook, and the curved gold drawing stroke exactly as in the input. Keep the exact square canvas, framing, colors, proportions, pose, and all foreground placement unchanged. Do not redraw, restyle, add objects, add a halo, or add a new shadow outside the figure. Keep crisp natural antialiased edges and all original foreground detail. Output one transparent PNG foreground layer for Android adaptive app icons.
