"""OpenAI 风格文本生成；有限字数校正，不截断故事结尾。"""
from dataclasses import dataclass
import time
from openai import OpenAI
from prompts import StoryRequest, build_messages
from text_utils import count_words


@dataclass
class StoryResult:
    text: str
    words: int
    length_ok: bool
    corrections: int
    model: str
    temperature: float
    max_tokens: int
    elapsed_seconds: float
    usage: list
    messages: list


class StoryGenerator:
    def __init__(self, settings, client=None):
        self.settings = settings
        self.client = client

    def generate(self, req: StoryRequest, original='', operation='重新生成', instruction=''):
        messages = build_messages(req, original, operation, instruction)
        self.settings.require_llm()
        client = self.client or OpenAI(api_key=self.settings.llm_key, base_url=self.settings.llm_base_url,
                                       timeout=self.settings.timeout, max_retries=0)
        budget = min(8000, max(1200, int(req.words * 3)))
        usage = []
        started = time.monotonic()
        for attempt in range(2):
            response = client.chat.completions.create(
                model=self.settings.llm_model, messages=messages,
                temperature=self.settings.temperature, max_tokens=budget,
            )
            if not response.choices:
                raise ValueError('文本接口没有返回故事，请重试。')
            choice = response.choices[0]
            text = (choice.message.content or '').strip()
            if not text:
                raise ValueError('文本接口返回空内容，请检查模型或主题。')
            if choice.finish_reason != 'stop':
                raise ValueError('模型输出未完整结束，未送入语音合成。请检查模型输出额度或更换模型。')
            n = count_words(text)
            length_ok = abs(n - req.words) <= req.words * 0.1
            if response.usage:
                usage.append(response.usage.model_dump())
            if length_ok or attempt == 1:
                break
            messages = messages + [
                {'role':'assistant', 'content':text},
                {'role':'user', 'content':f'当前为{n}字，请在保留完整开头、发展、高潮和结尾的前提下，调整为约{req.words}字（±10%）。只输出标题和完整正文。'},
            ]
        return StoryResult(text, n, length_ok, attempt, self.settings.llm_model,
                           self.settings.temperature, budget, round(time.monotonic()-started, 3), usage, messages)
