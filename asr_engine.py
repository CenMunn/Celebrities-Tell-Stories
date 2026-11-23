"""将简短录音转写为可编辑的故事主题。"""
import re

from openai import OpenAI

from audio_utils import read_voice_clip, wav_bytes, wav_data_uri
from text_utils import validate_theme


ASR_MODEL = 'qwen3-asr-flash'


def asr_base_url(settings):
    region = settings.region
    shared_gateways = {
        'cn-beijing': 'https://dashscope.aliyuncs.com',
        'ap-southeast-1': 'https://dashscope-intl.aliyuncs.com',
    }
    if region not in shared_gateways:
        raise ValueError('本应用的主题识别支持百炼北京或新加坡地域。')
    if not settings.workspace:
        return shared_gateways[region] + '/compatible-mode/v1'
    if not re.fullmatch(r'[a-zA-Z0-9-]+', settings.workspace):
        raise ValueError('DASHSCOPE_WORKSPACE_ID 格式无效。')
    return f'https://{settings.workspace}.{region}.maas.aliyuncs.com/compatible-mode/v1'


def _transcribe(client, content):
    response = client.chat.completions.create(
        model=ASR_MODEL,
        messages=[{
            'role': 'user',
            'content': [{
                'type': 'input_audio',
                'input_audio': {'data': wav_data_uri(content)},
            }],
        }],
        stream=False,
        extra_body={'asr_options': {'enable_itn': False}},
    )
    text = response.choices[0].message.content if response.choices else None
    if not text or not str(text).strip():
        raise ValueError('没有识别到文字，请靠近麦克风再试或手动输入。')
    return validate_theme(text)


def transcribe_theme(path, settings, client=None):
    pcm, info = read_voice_clip(path, minimum=0.5, maximum=30)
    content = wav_bytes(pcm, info['sample_rate'])
    if len(content) * 4 / 3 >= 10_000_000:
        raise ValueError('主题音频编码后过大，请缩短录音或降低采样率。')
    if not settings.tts_key:
        raise ValueError('语音识别需要配置 DASHSCOPE_API_KEY。')
    if client is not None:
        return _transcribe(client, content)
    with OpenAI(api_key=settings.tts_key, base_url=asr_base_url(settings),
                timeout=min(settings.timeout, 45), max_retries=0) as client:
        return _transcribe(client, content)
