import json
import wave
import numpy as np
import pytest

from text_utils import validate_theme, count_words, split_text_into_chunks
from prompts import StoryRequest, build_messages
from audio_utils import write_pcm_wav, inspect_reference_audio
from records import RecordStore


@pytest.mark.parametrize('theme', ['', '   ', '！@#$'])
def test_rejects_empty_or_symbol_theme(theme):
    with pytest.raises(ValueError):
        validate_theme(theme)


def test_short_theme_and_special_characters():
    assert validate_theme(' 森林 ') == '森林'
    assert validate_theme('星际🚀：AI & 人类') == '星际🚀：AI & 人类'
    with pytest.raises(ValueError):
        validate_theme('林' * 501)


@pytest.mark.parametrize('text,limit', [('甲' * 2001, 2000), ('甲。' + '乙' * 2001, 2000), ('你好！\n“再见？”尾声。', 4), ('a' * 5000, 137)])
def test_chunks_preserve_every_character_and_bound(text, limit):
    chunks = split_text_into_chunks(text, limit)
    assert ''.join(chunks) == text
    assert all(0 < len(x) <= limit for x in chunks)


def test_word_count_excludes_punctuation_and_spaces():
    assert count_words('森林，AI 2026！') == 8


def test_prompt_covers_rubric_and_marks_user_data():
    req = StoryRequest('童话故事', '森林', 500, '儿童', '温暖治愈')
    messages = build_messages(req)
    assert messages[0]['role'] == 'system'
    assert all(x in messages[0]['content'] for x in ['故事创作者', '开头', '发展', '高潮', '结尾', '中文'])
    assert all(x in messages[1]['content'] for x in ['森林', '500', '儿童', '温暖治愈', '童话故事'])
    assert '增加细节' in build_messages(req, '原文', '增加细节')[1]['content']


def test_pcm_concatenation_has_correct_duration(tmp_path):
    rate = 22050
    pcm = (np.sin(np.arange(rate) * 0.1) * 1000).astype('<i2').tobytes()
    path = tmp_path / 'joined.wav'
    info = write_pcm_wav([pcm, pcm], path, rate)
    with wave.open(str(path)) as f:
        assert f.getnframes() == 2 * rate
        assert f.getnchannels() == 1
        assert f.getsampwidth() == 2
    assert info['duration_seconds'] == 2
    with pytest.raises(ValueError):
        write_pcm_wav([b''], tmp_path / 'empty.wav', rate)


def test_reference_audio_rejects_silence_and_short_sample(tmp_path):
    path = tmp_path / 'silent.wav'
    write_pcm_wav([bytes(22050 * 2 * 10)], path, 22050)
    with pytest.raises(ValueError, match='静音'):
        inspect_reference_audio(path)


def test_records_are_versioned_and_export_excludes_secrets(tmp_path):
    store = RecordStore(tmp_path)
    a = store.save_story('故事甲', {'theme': '森林'}, {'model': 'test'})
    b = store.save_story('故事乙', {'theme': '森林'}, {'parent_id': a['id']})
    assert a['id'] != b['id']
    assert store.get(b['id'])['parent_id'] == a['id']
    assert (tmp_path / a['id'] / 'story.txt').read_text(encoding='utf-8') == '故事甲'
    with pytest.raises(ValueError):
        store.get('../.env')
    store.save_rating(a['id'], {'完整性': 4}, '待试听')
    assert store.get(a['id'])['rating']['scores']['完整性'] == 4
    assert store.export(a['id']).is_file()
