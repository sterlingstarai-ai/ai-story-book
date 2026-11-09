"""Compare the approved offline samples with the app's Realtime adapter."""

import argparse
import asyncio
from hashlib import sha256
from html import escape
import io
import json
import os
from pathlib import Path
import re
import sys
import wave


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ('토리가 숲속에서 반짝이는 별을 발견했어요. “우와! 별이 내게 인사하잖아!” '
          '토리는 깜짝 놀랐지만, 곧 활짝 웃었어요.')
STYLES = {'natural': '이야기 성우', 'animated': '구연동화', 'bedtime': '잠자리'}
VOICES = {
    'warm': ('coral', 'Kore', '2026-11-02-google-tts-styles-final-rzi5cjkw', 'narration_preview_google'),
    'deep': ('cedar', 'Puck', '2026-11-02-gemini-male-narration', 'narration_preview_google_male'),
}


def approved_samples():
    samples = {}
    for variant, (_, voice, folder, prefix) in VOICES.items():
        archive = ROOT / 'docs' / 'acceptance' / folder
        metadata = json.loads((archive / 'result.json').read_text())
        if (metadata['voice'], metadata['synthetic_text']) != (voice, SCRIPT):
            raise ValueError('Approved voice or script differs')
        for style in STYLES:
            audio = (archive / f'{style}.mp3').read_bytes()
            bundled = ROOT / 'apps/mobile/assets/audio' / f'{prefix}_{style}.mp3'
            if not audio or audio != bundled.read_bytes():
                raise ValueError('Approved audio differs from the bundled sample')
            samples[variant, style] = audio
    return samples


async def generate(output, key, result):
    # Use the same adapter as the app and exclude all implicit local settings.
    os.environ['ASB_TEST_ISOLATED_SETTINGS'] = '1'
    os.environ['TESTING'] = 'true'
    sys.path.insert(0, str(ROOT / 'apps/api'))
    from src.core.config import settings
    from src.services.realtime_tts import MODEL, synthesize_realtime

    result['candidate_model'] = MODEL
    settings.openai_tts_api_key = key
    try:
        for clip in result['clips']:
            result['synthesis_attempts'] += 1
            audio = await synthesize_realtime(SCRIPT, VOICES[clip['voice']][0], style=clip['style'])
            with wave.open(io.BytesIO(audio), 'rb') as wav:
                if (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) != (1, 2, 24000):
                    raise ValueError('Candidate output is not mono PCM')
                duration = wav.getnframes() / wav.getframerate()
                if not 1 <= duration <= 60:
                    raise ValueError('Candidate audio duration is outside the review bounds')
            name = f'narration_preview_realtime_{clip["voice"]}_{clip["style"]}.wav'
            (output / name).write_bytes(audio)
            clip.update(candidate=name, candidate_sha256=sha256(audio).hexdigest(), duration_seconds=duration)
    finally:
        settings.openai_tts_api_key = None


def write_review(output, result):
    rows = []
    for clip in result['clips']:
        candidate = clip.get('candidate')
        preview = f'<audio controls preload="none" src="{candidate}"></audio>' if candidate else '합성 확인 전'
        voice = VOICES[clip['voice']][1]
        rows.append(f'<tr><th scope="row">{STYLES[clip["style"]]} · {voice}</th>'
                    f'<td><audio controls preload="none" src="{clip["baseline"]}"></audio></td><td>{preview}</td></tr>')
    html = ('<!doctype html><html lang="ko"><meta charset="utf-8"><meta name="robots" content="noindex,nofollow">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            '<title>한국어 AI 낭독 비교</title><style>body{font:1rem/1.6 system-ui;margin:2rem auto;max-width:60rem;padding:0 1rem}'
            'table{border-collapse:collapse;width:100%}th,td{border-bottom:1px solid #ccc;padding:.65rem;text-align:left}'
            'audio{width:100%;min-width:8rem}</style><main><h1>한국어 AI 낭독 비교</h1>'
            '<p>모든 음성은 AI 합성입니다. 발음과 대사 표현, 속도를 같은 대본에서 비교합니다.</p>'
            f'<blockquote>{escape(SCRIPT)}</blockquote><table><thead><tr><th>스타일과 기존 음색</th>'
            '<th>기존 Gemini</th><th>OpenAI Realtime 후보</th></tr></thead>'
            f'<tbody>{"".join(rows)}</tbody></table></main></html>')
    (output / 'index.html').write_text(html, encoding='utf-8')
    (output / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--execute', action='store_true', help='Allow up to six paid requests using OPENAI_API_KEY')
    args = parser.parse_args()
    key = os.environ.get('OPENAI_API_KEY', '') if args.execute else ''
    if args.execute and not re.fullmatch(r'sk-[A-Za-z0-9_-]{20,512}', key):
        parser.error('A verified OpenAI key in OPENAI_API_KEY is required for live requests')
    try:
        samples = approved_samples()
        args.output_dir.mkdir(mode=0o700)
        result = {'status': 'BASELINE_ONLY', 'synthetic_text': SCRIPT, 'synthesis_attempts': 0,
                  'human_reviewed': False, 'clips': []}
        for (variant, style), audio in samples.items():
            name = f'gemini-{variant}-{style}.mp3'
            (args.output_dir / name).write_bytes(audio)
            result['clips'].append({'voice': variant, 'style': style, 'baseline': name,
                                    'baseline_sha256': sha256(audio).hexdigest()})
        if args.execute:
            try:
                asyncio.run(generate(args.output_dir, key, result))
                result['status'] = 'CANDIDATE_AUDIO_READY_FOR_REVIEW'
            except (ValueError, wave.Error):
                result['status'] = 'CANDIDATE_SYNTHESIS_INCOMPLETE'
        write_review(args.output_dir, result)
    except (OSError, ValueError, KeyError):
        print(json.dumps({'status': 'REVIEW_PREPARATION_FAILED'}))
        return 1
    print(json.dumps({'status': result['status'], 'synthesis_attempts': result['synthesis_attempts']}))
    return int(result['status'] == 'CANDIDATE_SYNTHESIS_INCOMPLETE')


if __name__ == '__main__':
    raise SystemExit(main())
