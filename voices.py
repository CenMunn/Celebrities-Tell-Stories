"""按具体音色绑定模型和地域，不从声音名称猜测模型。"""
from dataclasses import dataclass, asdict
import json
from pathlib import Path
from records import atomic_json


@dataclass(frozen=True)
class Voice:
    id: str
    name: str
    category: str
    model: str
    region: str
    language: str


class VoiceCatalog:
    def __init__(self, custom_path):
        self.custom_path = Path(custom_path)

    def all(self):
        base = json.loads(Path(__file__).with_name('voices.json').read_text(encoding='utf-8'))
        custom = json.loads(self.custom_path.read_text(encoding='utf-8')) if self.custom_path.exists() else []
        return [Voice(**v) for v in base + custom]

    def get(self, voice_id):
        for v in self.all():
            if v.id == voice_id:
                return v
        raise ValueError('请选择可用的声音。')

    def choices(self, category='全部'):
        return [(v.name, v.id) for v in self.all() if category == '全部' or v.category == category]

    def add(self, voice):
        entries = json.loads(self.custom_path.read_text(encoding='utf-8')) if self.custom_path.exists() else []
        entries = [x for x in entries if x['id'] != voice.id] + [asdict(voice)]
        atomic_json(self.custom_path, entries)
