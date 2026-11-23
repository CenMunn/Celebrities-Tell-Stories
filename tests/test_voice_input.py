import base64
from io import BytesIO
from shutil import which
import subprocess
from types import SimpleNamespace
import wave

import numpy as np
import pytest
import soundfile as sf

from asr_engine import asr_base_url, transcribe_theme
from audio_utils import prepare_reference_audio
from config import Settings


def test_long_audio_can_be_cropped_without_changing_source(tmp_path):
    rate = 16000
    path = tmp_path / 'long.wav'
    voice = np.full(12 * rate, 3000, dtype='int16')
    left = np.concatenate([np.zeros(3 * rate, dtype='int16'), voice, np.zeros(53 * rate, dtype='int16')])
    sf.write(path, np.column_stack([left, -left]), rate)
    original = path.read_bytes()
    with pytest.raises(ValueError, match='10—60'):
        prepare_reference_audio(path)

    content, info = prepare_reference_audio(path, start=3, duration=12)
    with wave.open(BytesIO(content)) as wav:
        assert (wav.getnchannels(), wav.getsampwidth(), wav.getframerate()) == (1, 2, rate)
        assert wav.readframes(wav.getnframes()) == voice.astype('<i2').tobytes()
    assert info['start_seconds'] == 3
    assert info['duration_seconds'] == 12
    assert path.read_bytes() == original
    with pytest.raises(ValueError, match='超出音频末尾'):
        prepare_reference_audio(path, start=60, duration=12)


@pytest.mark.skipif(not which('ffmpeg'), reason='视频取声需要 FFmpeg')
def test_video_extraction_uses_the_selected_audio_and_handles_no_track(tmp_path):
    video = tmp_path / '参考样本.mp4'
    raw_video = ['-f', 'lavfi', '-i', 'color=black:size=64x64:rate=4']
    subprocess.run(
        [which('ffmpeg'), '-loglevel', 'error', *raw_video,
         '-f', 'lavfi', '-i', 'sine=440:sample_rate=44100', '-t', '19',
         '-c:v', 'mpeg4', '-c:a', 'aac', str(video)],
        check=True, capture_output=True, timeout=30,
    )
    content, info = prepare_reference_audio(video, start=3.5, duration=12)
    with wave.open(BytesIO(content)) as wav:
        assert wav.getnchannels() == 1
        assert wav.getframerate() == 16000
        assert wav.getnframes() == 12 * 16000
    assert info['source_type'] == 'video'
    assert 18.9 <= prepare_reference_audio(video, duration=0)[1]['duration_seconds'] <= 19.1
    without_audio = tmp_path / 'muted.mov'
    subprocess.run(
        [which('ffmpeg'), '-loglevel', 'error', *raw_video, '-an', '-t', '1',
         '-c:v', 'mpeg4', str(without_audio)],
        check=True, capture_output=True, timeout=30,
    )
    with pytest.raises(ValueError, match='无法提取音轨'):
        prepare_reference_audio(without_audio)


def test_asr_uploads_wav_data_only_and_validates_text(tmp_path):
    path = tmp_path / 'theme.wav'
    sf.write(path, np.full(16000, 2400, dtype='int16'), 16000)
    response_message = SimpleNamespace(content='  森林里的机器人  ')
    calls = []

    def create(**request):
        calls.append(request)
        return SimpleNamespace(choices=[SimpleNamespace(message=response_message)])

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    settings = Settings(tts_key='test-key', llm_base_url='https://other-provider.example/v1')
    assert asr_base_url(settings) == 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    assert transcribe_theme(path, settings, client) == '森林里的机器人'
    request = calls[0]
    assert request['model'] == 'qwen3-asr-flash'
    assert request['stream'] is False
    audio = request['messages'][0]['content'][0]['input_audio']['data']
    prefix, payload = audio.split(',', 1)
    assert prefix == 'data:audio/wav;base64'
    with wave.open(BytesIO(base64.b64decode(payload))) as sent:
        assert sent.getnframes() == 16000
    response_message.content = '   '
    with pytest.raises(ValueError, match='没有识别到文字'):
        transcribe_theme(path, settings, client)
