from dataclasses import asdict
from types import SimpleNamespace as NS
import numpy as np
import pytest

from config import Settings
from prompts import StoryRequest
from records import RecordStore
from story_generator import StoryGenerator, StoryResult
from tts_engine import TTSEngine
from voices import Voice
from workflow import StoryWorkflow


class ScriptedCompletions:
    """仅替代云端边界，返回预定响应，不用于应用演示或报告结果。"""
    def __init__(self, replies):
        self.replies = iter(replies)
        self.requests = []
        self.chat = NS(completions=self)

    def create(self, **kwargs):
        self.requests.append(kwargs)
        content, reason = next(self.replies)
        return NS(choices=[NS(message=NS(content=content), finish_reason=reason)], usage=None)


def test_generation_corrects_length_once_and_carries_api_parameters():
    client = ScriptedCompletions([('甲'*100, 'stop'), ('乙'*500, 'stop')])
    gen = StoryGenerator(Settings(llm_key='unit-test'), client=client)
    result = gen.generate(StoryRequest('童话故事', '森林'))
    assert result.words == 500 and result.length_ok
    assert result.corrections == 1 and len(client.requests) == 2
    assert client.requests[0]['temperature'] == 0.8
    assert client.requests[0]['max_tokens'] >= 1000
    assert client.requests[0]['messages'][0]['role'] == 'system'


@pytest.mark.parametrize('reply', [('', 'stop'), ('甲'*500, 'length')])
def test_empty_or_truncated_generation_is_not_success(reply):
    gen = StoryGenerator(Settings(llm_key='unit-test'), client=ScriptedCompletions([reply]))
    with pytest.raises(ValueError):
        gen.generate(StoryRequest('童话故事', '森林'))


def test_tts_preserves_order_without_network(tmp_path):
    pieces = []
    def synth(text, voice, speed):
        pieces.append(text)
        return (np.ones(2205, dtype='<i2') * len(pieces)).tobytes()
    engine = TTSEngine(Settings(tts_key='unit-test', chunk_size=100), synthesize_chunk=synth, temp_dir=tmp_path)
    voice = Voice('test', '测试', '故事讲述', 'cosyvoice-v2', 'cn-beijing', '中文')
    result = engine.synthesize('甲'*201, voice)
    assert ''.join(pieces) == '甲'*201
    assert result.chunks == 3 and result.duration_seconds == 0.3
    assert result.path.is_file()


def test_tts_failure_keeps_generated_story_and_reread_avoids_llm(tmp_path):
    client = ScriptedCompletions([('甲'*500, 'stop')])
    gen = StoryGenerator(Settings(llm_key='unit-test'), client=client)
    class BrokenTTS:
        def synthesize(self, *a, **kw):
            raise TimeoutError('must not expose internals')
    store = RecordStore(tmp_path)
    flow = StoryWorkflow(gen, BrokenTTS(), store)
    record = flow.generate(StoryRequest('童话故事', '森林'))
    voice = Voice('test', '测试', '故事讲述', 'cosyvoice-v2', 'cn-beijing', '中文')
    with pytest.raises(TimeoutError):
        flow.speak(record['id'], voice)
    assert store.story(record['id']) == '甲'*500
    assert len(client.requests) == 1
    with pytest.raises(TimeoutError):
        flow.speak(record['id'], voice)
    assert len(client.requests) == 1


def test_edit_creates_new_version_and_does_not_reuse_audio(tmp_path):
    store = RecordStore(tmp_path)
    a = store.save_story('甲'*500, {'theme':'森林'}, {'model':'test'})
    flow = StoryWorkflow(None, None, store)
    b = flow.ensure_text_version(a['id'], '乙'*500)
    assert b['parent_id'] == a['id']
    assert b['audios'] == [] and b['text_hash'] != a['text_hash']
