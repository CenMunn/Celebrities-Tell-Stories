"""参考音频通过 Data URI 提交；仅就绪的音色进入选择列表。"""
from pathlib import Path
import uuid
import json
from audio_utils import prepare_reference_audio, wav_data_uri
from voices import Voice
from records import atomic_json, now


class VoiceEnrollment:
    def __init__(self, settings, catalog, jobs_path, client=None):
        self.settings, self.catalog = settings, catalog
        self.jobs_path = Path(jobs_path)
        self.client = client

    def _client(self):
        if self.client is not None:
            return self.client
        import dashscope
        kwargs = {'api_key':self.settings.tts_key, 'region':self.settings.region,
                  'timeout':self.settings.timeout, 'max_retries':0}
        if self.settings.workspace:
            kwargs['workspace'] = self.settings.workspace
        return dashscope.Client(**kwargs)

    def jobs(self):
        return json.loads(self.jobs_path.read_text(encoding='utf-8')) if self.jobs_path.exists() else []

    def _save(self, job):
        jobs = [x for x in self.jobs() if x['id'] != job['id']] + [job]
        atomic_json(self.jobs_path, jobs)

    def create(self, sample_path, name, confirmed=False, model='cosyvoice-v2', *, start=0, duration=None):
        if not confirmed:
            raise ValueError('请确认这是本人或已经获得授权使用的声音。')
        if not (name or '').strip() or len(name) > 30:
            raise ValueError('请填写 1—30 字的音色名称。')
        if model not in ['cosyvoice-v2', 'cosyvoice-v3-flash']:
            raise ValueError('请选择支持的克隆目标模型。')
        wav, info = prepare_reference_audio(sample_path, start, duration)
        self.settings.require_tts()
        client = self._client()
        try:
            result = client.audio.voices.create(
                target_model=model, prefix='story' + uuid.uuid4().hex[:5], audio=wav_data_uri(wav),
            )
            if not result.voice_id:
                raise ValueError('服务未返回音色 ID，请在控制台检查创建结果，避免重复创建。')
            job = {'id':result.voice_id, 'name':name.strip(), 'model':model, 'region':self.settings.region,
                   'status':'DEPLOYING', 'created_at':now(), 'sample_info':info}
            self._save(job)
        finally:
            if self.client is None:
                client.close()
        return self.query(job['id'])

    def query(self, voice_id):
        job = next((j for j in self.jobs() if j['id'] == voice_id), None)
        if not job:
            raise ValueError('请选择已有的音色创建任务。')
        self.settings.require_tts()
        client = self._client()
        try:
            result = client.audio.voices.get(voice_id=voice_id)
            job['status'] = str(result.status or 'UNKNOWN')
            self._save(job)
            if job['status'] == 'OK':
                self.catalog.add(Voice(job['id'], job['name'], '自定义音色', job['model'], job['region'], '中文普通话'))
            return job
        finally:
            if self.client is None:
                client.close()
