from types import SimpleNamespace
import app
from app import build_app, create_story_audio_predict
from config import Settings
from records import RecordStore
from workflow import StoryWorkflow


def test_blocks_contains_required_inputs_and_actions():
    demo = build_app()
    config = demo.get_config_file()
    labels = str(config)
    for value in ['故事类型', '故事主题', '目标字数', '讲述声音', '生成故事并朗读', '故事正文', '故事音频', '运行状态', '我的声音', '作品与评价']:
        assert value in labels
    assert len(config['dependencies']) >= 10


def test_empty_theme_returns_friendly_error_without_network():
    events = list(create_story_audio_predict('童话故事', '', 500, '儿童', '温暖治愈', 'longxiaochun_v2', 1.0))
    assert '请输入' in events[-1][2]


def test_switching_audio_resets_listening_confirmation():
    config = build_app().get_config_file()
    find = lambda label: next(c['id'] for c in config['components'] if c.get('props', {}).get('label') == label)
    audio = find('音频 A')
    confirm = find('我已阅读故事并实际试听所选音频 A')
    changes = [d for d in config['dependencies'] if any(t[0] == audio and t[1] == 'input' for t in d['targets'])]
    assert any(confirm in d['outputs'] for d in changes)


def test_manual_save_keeps_one_version_and_refresh_keeps_selection(tmp_path, monkeypatch):
    store = RecordStore(tmp_path)
    first = store.save_story('森林里有一盏灯。', {}, {})
    flow = StoryWorkflow(None, None, store)
    monkeypatch.setattr(app, 'services', lambda: (Settings(), store, None, flow))
    _, _, status, rid, _, download, _ = app.save_draft_predict('森林里的灯亮了。', first['id'])
    assert '手稿已保存' in status
    assert store.get(rid)['parent_id'] == first['id']
    assert store.story(rid) == '森林里的灯亮了。'
    assert download.endswith('story.txt')
    assert app.save_draft_predict('森林里的灯亮了。', rid)[3] == rid
    assert len(store.list_records()) == 2
    assert app.refresh_history(rid)['value'] == rid
    assert '选择作品' in app.load_history(None)[7]


def test_failed_reread_keeps_previous_player_only_for_same_story(tmp_path, monkeypatch):
    store = RecordStore(tmp_path)
    first = store.save_story('森林里有一盏灯。', {}, {})
    wav = tmp_path / 'test.wav'
    wav.write_bytes(b'test audio')
    audio = store.add_audio(first['id'], wav, {})
    def broken(*args):
        raise TimeoutError
    flow = StoryWorkflow(None, SimpleNamespace(synthesize=broken), store)
    catalog = SimpleNamespace(get=lambda _: SimpleNamespace(name='测试音色'))
    monkeypatch.setattr(app, 'services', lambda: (Settings(), store, catalog, flow))
    last = list(app.synthesize_speech_predict(
        store.story(first['id']), 'voice', 1.0, first['id'], current_audio_id=audio['id'],
    ))[-1]
    assert last[1] == last[-1] == app.gr.skip()
    assert '保留上次朗读' in last[2]
    last = list(app.synthesize_speech_predict(
        '森林里的灯亮了。', 'voice', 1.0, first['id'], current_audio_id=audio['id'],
    ))[-1]
    assert last[1] is None and last[-1] is None


def test_asr_suggests_text_and_clip_changes_cancel_confirmation():
    config = build_app().get_config_file()
    def find(label):
        return next(c['id'] for c in config['components'] if c['props'].get('label') == label)

    recognition = next(d for d in config['dependencies'] if d['api_name'] == 'voice_theme_predict')
    assert find('识别结果') in recognition['outputs']
    assert find('故事主题') not in recognition['outputs']
    consent = find('我有权使用这段声音，并同意提交所选片段创建音色')
    for label in ('样本来源', '参考声音', '参考视频', '选段起点（秒）', '选段时长（秒）'):
        component_id = find(label)
        assert any(any(t[0] == component_id and t[1] == 'change' for t in d['targets']) and consent in d['outputs']
                   for d in config['dependencies'])
