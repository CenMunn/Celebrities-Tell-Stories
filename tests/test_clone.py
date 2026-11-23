import base64
from io import BytesIO
from types import SimpleNamespace as NS
import wave
import numpy as np
import soundfile as sf
import pytest
from config import Settings
from audio_utils import prepare_reference_audio
from voices import VoiceCatalog
from voice_clone import VoiceEnrollment


def test_clone_only_registers_voice_after_ready(tmp_path):
    sample = tmp_path / 'sample.wav'
    sf.write(sample, np.sin(np.arange(160000)*0.2)*0.1, 16000, subtype='PCM_16')
    class Voices:
        status = 'DEPLOYING'
        def create(self, **kw):
            assert kw['audio'].startswith('data:audio/wav;base64,')
            return NS(voice_id='myvoice-id')
        def get(self, **kw):
            return NS(status=self.status)
    remote = Voices()
    catalog = VoiceCatalog(tmp_path / 'custom.json')
    enrollment = VoiceEnrollment(Settings(tts_key='unit-test'), catalog, tmp_path / 'jobs.json', client=NS(audio=NS(voices=remote)))
    with pytest.raises(ValueError):
        enrollment.create(sample, '我的声音', confirmed=False)
    job = enrollment.create(sample, '我的声音', confirmed=True)
    assert job['status'] == 'DEPLOYING'
    assert all(v.id != 'myvoice-id' for v in catalog.all())
    remote.status = 'OK'
    job = enrollment.query(job['id'])
    assert job['status'] == 'OK'
    assert catalog.get('myvoice-id').category == '自定义音色'


def test_create_sends_only_the_same_excerpt_used_for_preview(tmp_path):
    source = tmp_path / 'long.wav'
    sample_rate = 16000
    signal = np.concatenate([np.zeros(4 * sample_rate), np.full(13 * sample_rate, 0.08)])
    sf.write(source, signal, sample_rate)
    expected, _ = prepare_reference_audio(source, start=4, duration=12)

    def create(**request):
        payload = base64.b64decode(request['audio'].split(',', 1)[1])
        assert payload == expected
        with wave.open(BytesIO(payload)) as wav:
            assert wav.getnframes() == 12 * sample_rate
        return NS(voice_id='excerpt-test')

    client = NS(audio=NS(voices=NS(create=create, get=lambda **_: NS(status='OK'))))
    catalog = VoiceCatalog(tmp_path / 'custom.json')
    enrollment = VoiceEnrollment(Settings(tts_key='unit-test'), catalog, tmp_path / 'jobs.json', client=client)
    job = enrollment.create(source, '选段测试', confirmed=True, start=4, duration=12)
    assert job['sample_info']['start_seconds'] == 4
    assert job['sample_info']['duration_seconds'] == 12
    assert catalog.get(job['id']).category == '自定义音色'
