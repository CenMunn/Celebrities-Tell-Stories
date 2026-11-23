"""业务流程不依赖 Gradio；语音失败时生成的故事仍然存在。"""
from dataclasses import asdict
from text_utils import count_words


class StoryWorkflow:
    def __init__(self, generator, tts, store):
        self.generator, self.tts, self.store = generator, tts, store

    def generate(self, request, original='', operation='重新生成', instruction='', parent_id=None):
        result = self.generator.generate(request, original, operation, instruction)
        meta = asdict(result)
        meta.update(parent_id=parent_id, operation=operation)
        params = asdict(request)
        params.update(operation=operation, instruction=instruction)
        return self.store.save_story(result.text, params, meta)

    def ensure_text_version(self, rid, text):
        if not (text or '').strip() or count_words(text) == 0:
            raise ValueError('请先生成或输入故事。')
        if len(text) > 10000:
            raise ValueError('故事最多 10000 字符。')
        if rid:
            record = self.store.get(rid)
            if text == self.store.story(rid):
                return record
            return self.store.save_story(text, record['params'], {'parent_id':rid, 'operation':'手动编辑', 'model':'人工编辑'})
        return self.store.save_story(text, {}, {'operation':'手动输入', 'model':'人工输入'})

    def speak(self, rid, voice, speed=1.0, progress=None):
        result = self.tts.synthesize(self.store.story(rid), voice, speed, progress)
        try:
            return self.store.add_audio(rid, result.path, asdict(result))
        finally:
            result.path.unlink(missing_ok=True)
