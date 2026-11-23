from concurrent.futures import ThreadPoolExecutor
import time
import records
from records import RecordStore


def test_parallel_rating_updates_are_not_lost(tmp_path, monkeypatch):
    first = RecordStore(tmp_path)
    second = RecordStore(tmp_path)
    record = first.save_story('一个故事', {}, {})
    original = records.atomic_json
    def slow_disk(path, data):
        time.sleep(0.02)
        return original(path, data)
    monkeypatch.setattr(records, 'atomic_json', slow_disk)
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit((first if i%2 else second).save_rating, record['id'], {'完整性':4}, str(i)) for i in range(8)]
        for future in futures:
            future.result()
    assert len(first.get(record['id'])['ratings']) == 8


def test_export_contains_audio_files_listed_in_snapshot(tmp_path, monkeypatch):
    import json
    import zipfile

    store = RecordStore(tmp_path)
    rid = store.save_story('丛林冒险', {}, {})['id']
    source = tmp_path / 'recording.wav'
    source.write_bytes(b'test audio')
    first = store.add_audio(rid, source, {})
    original_write = zipfile.ZipFile.write

    def write_and_add_audio(archive, filename, arcname):
        if arcname == 'story.txt':
            store.add_audio(rid, source, {})
        return original_write(archive, filename, arcname)

    monkeypatch.setattr(zipfile.ZipFile, 'write', write_and_add_audio)
    with zipfile.ZipFile(store.export(rid)) as archive:
        record = json.loads(archive.read('record.json'))
        assert [a['file'] for a in record['audios']] == [first['file']]
        assert set(archive.namelist()) == {'story.txt', 'record.json', first['file']}
    assert len(store.get(rid)['audios']) == 2
