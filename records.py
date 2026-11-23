"""每个正文版本独立存储，音频和评分保留对应关系。"""
from pathlib import Path
from datetime import datetime
from zoneinfo import ZoneInfo
import hashlib
import json
import re
import shutil
import uuid
import zipfile
from threading import RLock
from functools import wraps
from text_utils import count_words

# Gradio 单进程内的多个事件与 RecordStore 实例共享同一把锁。
# 锁覆盖读取、修改和写回；只有文件替换原子化不能避免丢失更新。
_record_lock = RLock()


def serialized(method):
    @wraps(method)
    def wrapped(*args, **kwargs):
        with _record_lock:
            return method(*args, **kwargs)
    return wrapped


def now():
    return datetime.now(ZoneInfo('Asia/Shanghai')).isoformat(timespec='seconds')


def text_hash(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def atomic_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    tmp.replace(path)


class RecordStore:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def folder(self, record_id):
        if not re.fullmatch(r'\d{8}_\d{6}_[a-f0-9]{12}', record_id or ''):
            raise ValueError('无效的作品编号。')
        path = (self.root / record_id).resolve()
        if path.parent != self.root:
            raise ValueError('无效的作品路径。')
        return path

    def save_story(self, text, params, metadata):
        rid = datetime.now(ZoneInfo('Asia/Shanghai')).strftime('%Y%m%d_%H%M%S_') + uuid.uuid4().hex[:12]
        folder = self.folder(rid)
        folder.mkdir()
        allowed_params = {'genre', 'theme', 'words', 'audience', 'style', 'operation', 'instruction'}
        allowed_meta = {'model', 'temperature', 'max_tokens', 'elapsed_seconds', 'usage', 'messages', 'corrections', 'length_ok', 'parent_id', 'operation'}
        record = {k: v for k, v in metadata.items() if k in allowed_meta}
        record.update(id=rid, created_at=now(), params={k: v for k, v in params.items() if k in allowed_params},
                      words=count_words(text), text_hash=text_hash(text), audios=[])
        (folder / 'story.txt').write_text(text, encoding='utf-8')
        atomic_json(folder / 'record.json', record)
        return record

    @serialized
    def get(self, rid):
        return json.loads((self.folder(rid) / 'record.json').read_text(encoding='utf-8'))

    def story(self, rid):
        return (self.folder(rid) / 'story.txt').read_text(encoding='utf-8')

    @serialized
    def add_audio(self, rid, source, metadata):
        record = self.get(rid)
        aid = uuid.uuid4().hex[:12]
        name = f'audio_{aid}.wav'
        shutil.copyfile(source, self.folder(rid) / name)
        allowed = {'voice_id', 'voice_name', 'model', 'speed', 'duration_seconds', 'sample_rate', 'chunks', 'elapsed_seconds'}
        entry = {k: v for k, v in metadata.items() if k in allowed}
        entry.update(id=aid, file=name, created_at=now(), text_hash=record['text_hash'])
        record['audios'].append(entry)
        atomic_json(self.folder(rid) / 'record.json', record)
        return entry

    @serialized
    def save_rating(self, rid, scores, comment, audio_id=None):
        record = self.get(rid)
        if audio_id and not any(a['id'] == audio_id for a in record['audios']):
            raise ValueError('评分对应的音频不存在。')
        if not scores or any(not isinstance(v, (int, float)) or not 1 <= v <= 5 for v in scores.values()):
            raise ValueError('评分范围为 1—5。')
        rating = {'scores': scores, 'comment': comment[:2000], 'audio_id': audio_id, 'time': now(), 'text_hash': record['text_hash']}
        record.setdefault('ratings', []).append(rating)
        record['rating'] = rating
        atomic_json(self.folder(rid) / 'record.json', record)

    def list_records(self):
        records = []
        for path in sorted(self.root.glob('*/record.json'), reverse=True):
            try:
                records.append(self.get(path.parent.name))
            except (ValueError, OSError, json.JSONDecodeError):
                continue
        return records

    def export(self, rid):
        record = self.get(rid)
        folder = self.folder(rid)
        dest = folder / '作品与测试记录.zip'
        temp = folder / f'.export_{uuid.uuid4().hex}.tmp'
        try:
            with zipfile.ZipFile(temp, 'w', zipfile.ZIP_DEFLATED) as z:
                z.writestr('record.json', json.dumps(record, ensure_ascii=False, indent=2))
                for name in ['story.txt'] + [a['file'] for a in record['audios']]:
                    if Path(name).name != name:
                        raise ValueError('无效的导出文件名。')
                    z.write(folder / name, name)
            temp.replace(dest)
        finally:
            temp.unlink(missing_ok=True)
        return dest
