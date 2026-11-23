"""DashScope 2.x 合成适配器：文本 -> PCM 字节 -> 本地 WAV 路径。"""
from dataclasses import dataclass
from pathlib import Path
import tempfile
import time
import uuid
from audio_utils import write_pcm_wav
from text_utils import split_text_into_chunks


@dataclass
class AudioResult:
    path: Path
    voice_id: str
    voice_name: str
    model: str
    speed: float
    duration_seconds: float
    sample_rate: int
    chunks: int
    elapsed_seconds: float


class TTSEngine:
    def __init__(self, settings, synthesize_chunk=None, temp_dir=None):
        self.settings = settings
        self._chunk = synthesize_chunk
        self.temp_dir = Path(temp_dir or tempfile.gettempdir()) / 'story_tts'
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def _synthesize_chunk(self, text, voice, speed):
        import dashscope
        kwargs = {'api_key': self.settings.tts_key, 'region': self.settings.region,
                  'timeout': self.settings.timeout, 'max_retries': 0}
        if self.settings.workspace:
            kwargs['workspace'] = self.settings.workspace
        client = dashscope.Client(**kwargs)
        try:
            # 这里明确传入文本、具体音色 ID、所属模型、PCM 格式和统一采样率。
            return client.audio.tts.synthesize(text, model=voice.model, voice=voice.id,
                                               format='pcm', sample_rate=22050, rate=speed, timeout=self.settings.timeout)
        finally:
            close = getattr(client, 'close', None)
            if close:
                close()

    def synthesize(self, text, voice, speed=1.0, progress=None):
        if not (text or '').strip():
            raise ValueError('请先生成或输入故事。')
        if len(text) > 10000:
            raise ValueError('待朗读文本最多 10000 字符。')
        if not 0.5 <= speed <= 2:
            raise ValueError('语速需要在 0.5—2.0 之间。')
        self.settings.require_tts()
        if voice.region != self.settings.region:
            raise ValueError('该声音与当前语音服务地域不匹配，请选择对应地域的声音。')
        started = time.monotonic()
        chunks = [s for s in split_text_into_chunks(text, self.settings.chunk_size) if s.strip()]
        data = []
        for i, chunk in enumerate(chunks):
            if progress:
                progress(i, len(chunks))
            audio = (self._chunk or self._synthesize_chunk)(chunk, voice, speed)
            if not isinstance(audio, bytes) or not audio:
                raise ValueError(f'第 {i+1} 段没有返回音频。')
            data.append(audio)
        path = self.temp_dir / f'{uuid.uuid4().hex}.wav'
        info = write_pcm_wav(data, path)
        return AudioResult(path, voice.id, voice.name, voice.model, speed,
                           info['duration_seconds'], info['sample_rate'], len(chunks), round(time.monotonic()-started, 3))
