"""名人讲故事：python app.py；界面事件与业务函数分离。"""
import argparse
from dataclasses import asdict
from pathlib import Path
import os
import re

os.environ.setdefault('GRADIO_ANALYTICS_ENABLED', 'False')
import gradio as gr
from config import ROOT, Settings
from prompts import GENRES, AUDIENCES, STYLES, OPERATIONS, StoryRequest
from story_generator import StoryGenerator
from tts_engine import TTSEngine
from records import RecordStore
from voices import VoiceCatalog
from voice_clone import VoiceEnrollment
from workflow import StoryWorkflow
from text_utils import count_words
from asr_engine import transcribe_theme
from audio_utils import MAX_VIDEO_BYTES, VIDEO_EXTENSIONS, prepare_reference_audio
from studio_design import ASSETS, BRAND, PLAYER_JS, featured_reading, page_title, section_title, stylesheet


def services():
    settings = Settings.from_env()
    store = RecordStore(settings.results_dir)
    catalog = VoiceCatalog(ROOT / 'data' / 'custom_voices.json')
    flow = StoryWorkflow(StoryGenerator(settings), TTSEngine(settings), store)
    return settings, store, catalog, flow


def public_error(exc, settings=None):
    """状态只含可操作的错误说明，不回显第三方请求、密钥或响应正文。"""
    status = getattr(exc, 'status_code', None)
    if status in (401, 403):
        message = '接口鉴权失败，请检查密钥、模型权限及服务地域。'
    elif status == 429:
        message = '接口限流或额度不足，请检查控制台，稍后重试。'
    elif isinstance(exc, (TimeoutError, ConnectionError)) or type(exc).__name__ == 'APIConnectionError' or 'timeout' in type(exc).__name__.lower():
        message = '接口连接超时，请检查网络后重试。'
    elif isinstance(exc, ValueError):
        message = str(exc)
    elif isinstance(exc, OSError):
        message = '文件读取或保存失败，请检查项目目录权限和磁盘空间。'
    else:
        message = '接口调用失败，请检查服务配置、模型和音色可用性后重试。'
    if settings:
        for secret in [settings.llm_key, settings.tts_key, settings.oss_key, settings.oss_secret]:
            if secret:
                message = message.replace(secret, '[已隐藏]')
    message = re.sub(r'sk-[A-Za-z0-9_-]+', '[已隐藏]', message)
    return message[:240]


def output_for(store, record, status, audio=None, *, keep_audio=False):
    path = str(store.folder(record['id']) / audio['file']) if audio else None
    audio_id = audio['id'] if audio else None
    return (store.story(record['id']), gr.skip() if keep_audio else path, status, record['id'],
            f'实际字数：{record["words"]}',
            str(store.folder(record['id']) / 'story.txt'), gr.skip() if keep_audio else audio_id)


def create_story_audio_predict(genre, theme, words, audience, style, voice_id, speed,
                               record_id=None, current_story='', operation='重新生成', instruction='',
                               with_audio=True, progress=gr.Progress()):
    """组件输入顺序对应函数参数，yield 的七个位置对应七个输出组件。"""
    settings = None
    try:
        settings, store, catalog, flow = services()
        request = StoryRequest(genre, theme, words, audience, style).validate()
        yield (gr.skip(), gr.skip(), '正在构思并生成故事…', gr.skip(), gr.skip(), gr.skip(), gr.skip())
        record = flow.generate(request, current_story, operation, instruction, record_id)
    except Exception as exc:
        yield (gr.skip(), gr.skip(), public_error(exc, settings), gr.skip(), gr.skip(), gr.skip(), gr.skip())
        return
    warning = '' if record.get('length_ok') else ' 字数经一次校正后仍超出 ±10% 目标，可调整后再生成。'
    yield output_for(store, record, '故事已保存。' + ('正在合成语音…' if with_audio else '可以编辑文本或选择声音朗读。') + warning)
    if not with_audio:
        return
    try:
        def update(i, total):
            progress((i, total), desc=f'正在合成语音 {i+1}/{total}')
        audio = flow.speak(record['id'], catalog.get(voice_id), speed, update)
        yield output_for(store, record, f'完成：{record["words"]} 字，音频 {audio["duration_seconds"]:.1f} 秒。' + warning, audio)
    except Exception as exc:
        yield output_for(store, record, '故事已保存，语音未完成：' + public_error(exc, settings) + ' 可点击“只重新合成语音”。')


def generate_story_predict(genre, theme, words, audience, style, voice_id, speed,
                           record_id=None, current_story='', operation='重新生成', instruction='', progress=gr.Progress()):
    yield from create_story_audio_predict(genre, theme, words, audience, style, voice_id, speed,
                                          record_id, current_story, operation, instruction, False, progress)


def save_draft_predict(text, record_id):
    settings = None
    try:
        settings, store, _, flow = services()
        record = flow.ensure_text_version(record_id, text)
        return output_for(store, record, '手稿已保存，可以在作品书架查看。', keep_audio=record['id'] == record_id)
    except Exception as exc:
        return (gr.skip(), gr.skip(), public_error(exc, settings), gr.skip(), gr.skip(), gr.skip(), gr.skip())


def synthesize_speech_predict(text, voice_id, speed, record_id=None, progress=gr.Progress(), current_audio_id=None):
    settings = None
    record = None
    keep_audio = False
    try:
        settings, store, catalog, flow = services()
        record = flow.ensure_text_version(record_id, text)
        keep_audio = record['id'] == record_id and any(
            a['id'] == current_audio_id and (store.folder(record_id) / a['file']).is_file()
            for a in record['audios']
        )
        voice = catalog.get(voice_id)
        yield output_for(store, record, f'正在用「{voice.name}」朗读…', keep_audio=keep_audio)
        audio = flow.speak(record['id'], voice, speed,
                           lambda i, n: progress((i, n), desc=f'正在合成语音 {i+1}/{n}'))
        yield output_for(store, record, f'朗读完成 · {voice.name} · {audio["duration_seconds"]:.1f} 秒。', audio)
    except Exception as exc:
        msg = public_error(exc, settings)
        if record:
            message = ('本次朗读失败，播放器保留上次朗读。' if keep_audio else '故事已保存，语音未完成。') + msg
            yield output_for(store, record, message, keep_audio=keep_audio)
        else:
            yield (gr.skip(), gr.skip(), msg, gr.skip(), gr.skip(), gr.skip(), gr.skip())


def history_choices():
    _, store, _, _ = services()
    return [(f'{r["created_at"]}｜{r["params"].get("genre", "编辑故事")}｜{r["params"].get("theme", "")[:20]}｜{r["words"]}字', r['id'])
            for r in store.list_records()]


def refresh_history(selected):
    choices = history_choices()
    return gr.update(choices=choices, value=selected if any(rid == selected for _, rid in choices) else None)


def load_history(rid):
    message = '选择作品后可查看正文和朗读版本。'
    if rid:
        try:
            _, store, _, _ = services()
            record = store.get(rid)
            folder = store.folder(rid)
            audios = [a for a in record['audios'] if (folder / a['file']).is_file()]
            choices = [(f'{a["voice_name"]}｜{a["speed"]}倍｜{a["duration_seconds"]}秒｜{a["id"]}', a['id']) for a in audios]
            first = audios[0] if audios else None
            second = audios[-1] if len(audios) > 1 else None
            message = {
                0: '已加载手稿，可继续检查正文或下载文本。',
                1: '已加载 1 个朗读版本，可以先试听 A。',
            }.get(len(audios), f'已加载 {len(audios)} 个朗读版本，可选择 A 和 B 对照试听。')
            return (store.story(rid), record,
                    gr.update(choices=choices, value=first['id'] if first else None),
                    gr.update(choices=choices, value=second['id'] if second else None),
                    str(folder / first['file']) if first else None,
                    str(folder / second['file']) if second else None,
                    str(folder / 'story.txt'), message, rid)
        except Exception as exc:
            message = public_error(exc)
    return '', {}, gr.update(choices=[], value=None), gr.update(choices=[], value=None), None, None, None, message, None


def history_audio(rid, aid):
    if not rid or not aid:
        return None
    _, store, _, _ = services()
    audio = next((a for a in store.get(rid)['audios'] if a['id'] == aid), None)
    path = store.folder(rid) / audio['file'] if audio else None
    return str(path) if path and path.is_file() else None


def save_rating(rid, aid, confirmed, *values):
    try:
        if not rid or not aid:
            raise ValueError('请先加载作品并选择已经试听的音频 A。')
        if not confirmed:
            raise ValueError('请阅读故事并实际试听音频后，再确认保存评价。')
        _, store, _, _ = services()
        labels = ['情节完整性', '语言生动性', '主题契合度', '可朗读性', '语音自然度', '用户满意度']
        store.save_rating(rid, dict(zip(labels, values[:6])), values[6], aid)
        return '评价已保存，绑定到该正文版本和音频 A。', store.get(rid)
    except Exception as exc:
        return public_error(exc), gr.skip()


def clone_service():
    settings, _, catalog, _ = services()
    return settings, catalog, VoiceEnrollment(settings, catalog, ROOT / 'data' / 'clone_jobs.json')


def voice_theme_predict(sample):
    settings = None
    try:
        if not sample:
            raise ValueError('请先录音或上传一段主题音频。')
        settings = Settings.from_env()
        yield '', '正在识别录音…', gr.update(interactive=False)
        yield transcribe_theme(sample, settings), '识别完成，请确认结果。', gr.update(interactive=True)
    except Exception as exc:
        yield '', public_error(exc, settings), gr.update(interactive=False)


def selected_sample(source, audio, video):
    if source == 'video':
        if not video or Path(video).suffix.lower() not in VIDEO_EXTENSIONS:
            raise ValueError('请上传 MP4 或 MOV 参考视频。')
        return video
    if not audio:
        raise ValueError('请先上传或录制参考音频。')
    return audio


def preview_sample(source, audio, video, start, duration):
    try:
        path = selected_sample(source, audio, video)
        wav, info = prepare_reference_audio(path, start, duration)
        end = info['start_seconds'] + info['duration_seconds']
        message = (f'选段 {info["start_seconds"]:g}—{end:g} 秒，共 {info["duration_seconds"]:g} 秒，'
                   f'{info["sample_rate"]} Hz，单声道。')
        return gr.update(value=wav, visible=True), message
    except Exception as exc:
        return gr.update(value=None, visible=False), public_error(exc)


def clone_status_text(job):
    name = job['name']
    if job['status'] == 'OK':
        return f'「{name}」已就绪，可在故事创作台选择这个声音。'
    if job['status'] in {'UNDEPLOYED', 'FAILED'}:
        return f'「{name}」未能创建。请选择一段清晰的单人朗读后再提交。'
    return f'「{name}」尚未就绪（{job["status"]}），请稍后查询音色状态。'


def ready_voice_updates(catalog, job):
    if job['status'] != 'OK':
        return gr.skip(), gr.skip()
    return gr.update(choices=catalog.choices('自定义音色'), value=job['id']), '自定义音色'


def clone_predict(sample, name, confirmed, model, source='audio', video=None, start=0, duration=None):
    settings = None
    enrollment = None
    try:
        path = selected_sample(source, sample, video)
        settings, catalog, enrollment = clone_service()
        yield '正在处理选段并创建音色…', gr.skip(), gr.skip(), gr.skip()
        job = enrollment.create(path, name, confirmed, model, start=start, duration=duration)
        jobs = gr.update(choices=[(j['name'], j['id']) for j in enrollment.jobs()], value=job['id'])
        yield clone_status_text(job), jobs, *ready_voice_updates(catalog, job)
    except Exception as exc:
        message = public_error(exc, settings)
        update = gr.skip()
        if enrollment:
            # 即使本次状态查询失败，已经保存的创建任务也可继续查询。
            jobs = enrollment.jobs()
            if jobs:
                message += ' 若已有创建任务，可先查询状态。'
                update = gr.update(choices=[(j['name'], j['id']) for j in jobs], value=jobs[-1]['id'])
        yield message, update, gr.skip(), gr.skip()


def query_clone(voice_id):
    settings = None
    try:
        settings, catalog, enrollment = clone_service()
        job = enrollment.query(voice_id)
        return clone_status_text(job), *ready_voice_updates(catalog, job)
    except Exception as exc:
        return public_error(exc, settings), gr.skip(), gr.skip()


def recent_shelf(store):
    entries = []
    for record in store.list_records()[:3]:
        try:
            line = next((s for s in store.story(record['id']).splitlines() if s.strip()), '')
        except OSError:
            line = ''
        line = line or record['params'].get('theme') or '未命名故事'
        title = re.sub(r'^标题[：:]\s*', '', line.strip(' #*')).strip('《》')[:26]
        entries.append((title, record['id']))
    return entries


def refresh_shelf():
    entries = recent_shelf(services()[1])
    slots = entries + [('', None)] * (3 - len(entries))
    return ([gr.Markdown(visible=bool(entries))] +
            [gr.Button(value=title, visible=bool(rid)) for title, rid in slots] +
            [rid for _, rid in slots])


def build_app():
    settings, store, catalog, _ = services()
    shelf = recent_shelf(store)
    with gr.Blocks(title='名人讲故事 · 有声创作台', analytics_enabled=False, delete_cache=(3600, 86400)) as demo:
        gr.HTML(BRAND, elem_id='brand')
        rid, aid = gr.State(None), gr.State(None)
        asr_open = gr.State(False)
        blank, reset_op = gr.State(''), gr.State('重新生成')
        with gr.Column(elem_id='recent-works', min_width=0):
            shelf_heading = gr.Markdown('### 最近作品', visible=bool(shelf))
            recent_buttons, recent_ids = [], []
            for title, record_id in shelf + [('', None)] * (3-len(shelf)):
                recent_buttons.append(gr.Button(title, visible=bool(record_id), size='sm', elem_classes='recent-work'))
                recent_ids.append(gr.State(record_id))
        with gr.Tabs(selected='write', elem_id='studio-tabs', overflow_behavior='wrap') as tabs:
            with gr.Tab('故事创作', id='write', elem_id='write-tab'):
                gr.HTML(page_title('故事创作台', '从一个念头，写到一段可以听见的故事。'))
                with gr.Row(elem_id='writing-desk'):
                    with gr.Column(scale=7, min_width=0, elem_id='composer', elem_classes='studio-panel'):
                        gr.HTML(section_title('故事设定', 'pen'))
                        theme = gr.Textbox(label='故事主题', placeholder='今天想讲什么故事？写下一个主题或几个关键词…', lines=2, max_lines=4, max_length=500, elem_id='story-idea')
                        presets = [
                            ('魔法森林', '童话故事', '森林', 500, '儿童', '温暖治愈'),
                            ('机器人伙伴', '科幻故事', '一个会遗忘的机器人伙伴', 1000, '大学生', '生动冒险'),
                            ('校园小店', '商业传奇', '一家校园小店的转型', 800, '商业演讲听众', '简洁有力'),
                        ]
                        with gr.Row(elem_id='prompt-ideas'):
                            gr.HTML('<span class="idea-label">试试</span>')
                            preset_buttons = [gr.Button(p[0], size='sm', min_width=0) for p in presets]
                            topic_toggle = gr.Button('说出主题', size='sm', min_width=0, elem_id='topic-toggle')
                        with gr.Column(visible=False, min_width=0, elem_id='spoken-theme') as spoken_theme:
                            topic_audio = gr.Audio(
                                sources=['microphone', 'upload'], type='filepath', editable=False, label='主题录音',
                            )
                            gr.Markdown('录制或上传 0.5—30 秒音频。点击识别后，音频将提交给百炼。')
                            topic_submit = gr.Button('识别录音', size='sm')
                            topic_result = gr.Textbox(label='识别结果', interactive=False, lines=2, max_lines=4)
                            use_topic = gr.Button('用作故事主题', size='sm', interactive=False)
                            topic_status = gr.Textbox(label='识别状态', value='等待录音', interactive=False,
                                                      elem_classes='status-line')
                        with gr.Row(elem_classes='fields'):
                            genre = gr.Dropdown(GENRES, value='童话故事', label='故事类型', min_width=0)
                            audience = gr.Dropdown(AUDIENCES, value='一般读者', label='目标听众', min_width=0)
                        words = gr.Slider(200, 2000, value=500, step=50, label='目标字数', elem_id='word-target')
                        voice = gr.Dropdown(catalog.choices(), value='longxiaochun_v2', label='讲述声音')
                        with gr.Accordion('故事风格与声音设置', open=False, elem_classes='fold'):
                            with gr.Row(elem_classes='fields'):
                                style = gr.Dropdown(STYLES, value='温暖治愈', label='故事风格', min_width=0)
                                category = gr.Dropdown(['全部','男声','女声','儿童风格','新闻播报','故事讲述','方言风格','自定义音色'], value='全部', label='声音分类', min_width=0)
                            speed = gr.Slider(0.5, 2.0, value=1.0, step=0.1, label='朗读语速')
                        with gr.Row(elem_classes='actions'):
                            generate = gr.Button('生成故事并朗读', variant='primary', elem_id='generate-story', min_width=0)
                            text_only = gr.Button('只生成故事', min_width=0)
                        status = gr.Textbox(label='运行状态', value='准备就绪', interactive=False, lines=1, max_lines=3, elem_classes='status-line')
                        for button, preset in zip(preset_buttons, presets):
                            button.click(lambda values=preset[1:]: values, inputs=[], outputs=[genre,theme,words,audience,style], queue=False, api_visibility='private')
                    with gr.Column(scale=5, min_width=0, elem_id='listening-shelf'):
                        gr.HTML(featured_reading(), js_on_load=PLAYER_JS, elem_id='featured-reading')
                with gr.Column(min_width=0, elem_classes='studio-panel', elem_id='manuscript'):
                    gr.HTML(section_title('故事手稿', 'page'))
                    story = gr.Textbox(label='故事正文', placeholder='生成的故事会出现在这里。也可以直接写下正文，再选择声音朗读。', lines=5, max_lines=18, interactive=True)
                    count = gr.Markdown('实际字数：0', elem_classes='word-count')
                    with gr.Row(elem_classes='output-tools'):
                        with gr.Column(min_width=0, scale=3):
                            audio = gr.Audio(label='故事音频', elem_id='current-reading', type='filepath', interactive=False, autoplay=True)
                        with gr.Column(min_width=0, scale=2):
                            with gr.Row(elem_classes='actions'):
                                save_draft = gr.Button('保存手稿', size='sm', min_width=0)
                                reread = gr.Button('只重新合成语音', size='sm', min_width=0)
                            download = gr.File(label='下载故事文本', elem_id='story-file', interactive=False, height=75)
                    with gr.Accordion('重新生成与改写', open=False, elem_classes='fold'):
                        operation = gr.Dropdown(OPERATIONS, value='自由改写', label='修改方式')
                        instruction = gr.Textbox(label='补充改写要求', placeholder='例如：保留主角，让结尾更有余味', max_length=1000)
                        gr.Markdown('缩短或扩写前可调整目标字数，每次改写都会保存为新版本。')
                        rewrite = gr.Button('按所选方式生成新版本')
                outputs = [story, audio, status, rid, count, download, aid]
                base_inputs = [genre,theme,words,audience,style,voice,speed,rid,story]
                group = {'concurrency_id':'story_work', 'concurrency_limit':1, 'trigger_mode':'once'}
                jobs = [
                    (generate, create_story_audio_predict, base_inputs + [reset_op, blank]),
                    (text_only, generate_story_predict, base_inputs + [reset_op, blank]),
                    (reread, synthesize_speech_predict, [story, voice, speed, rid, aid]),
                    (rewrite, create_story_audio_predict, base_inputs + [operation, instruction]),
                    (save_draft, save_draft_predict, [story, rid]),
                ]
                story_controls = [story] + [button for button, _, _ in jobs]

                def story_controls_enabled(enabled):
                    return [gr.update(interactive=enabled) for _ in story_controls]

                for button, action, inputs in jobs:
                    button.click(lambda: story_controls_enabled(False), outputs=story_controls,
                                 queue=False, api_visibility='private').then(
                        action, inputs, outputs, show_progress='minimal', **group,
                    ).then(lambda: story_controls_enabled(True), outputs=story_controls,
                           queue=False, api_visibility='private')
                def toggle_voice_theme(opened):
                    return not opened, gr.update(visible=not opened), '说出主题' if opened else '收起录音'
                topic_toggle.click(toggle_voice_theme, asr_open, [asr_open, spoken_theme, topic_toggle],
                                   queue=False, api_visibility='private')
                topic_submit.click(voice_theme_predict, topic_audio, [topic_result, topic_status, use_topic],
                                   concurrency_limit=1, trigger_mode='once', api_visibility='private')
                use_topic.click(lambda text: (text, '已填入故事主题，可以继续编辑。'),
                                topic_result, [theme, topic_status], queue=False, api_visibility='private')
                def filter_voices(category_name, selected):
                    choices = services()[2].choices(category_name)
                    ids = [option[1] for option in choices]
                    return gr.Dropdown(choices=choices, value=selected if selected in ids else next(iter(ids), None))
                category.input(filter_voices, [category,voice], voice, queue=False)
                story.input(lambda t: (None, None, None, f'实际字数：{count_words(t)}（已编辑）', '正文已编辑，可保存手稿或重新朗读。'), story, [audio,aid,download,count,status], queue=False)
            with gr.Tab('我的声音', id='voices', elem_id='voices-tab'):
                gr.HTML(page_title('我的声音', '录一小段自己的声音，为故事留下一位专属讲述者。'))
                with gr.Row(elem_classes='settings-layout'):
                    with gr.Column(min_width=0, scale=5, elem_classes='note-panel'):
                        gr.HTML(section_title('参考录音', 'headphones'))
                        gr.Markdown('用平时讲故事的语速朗读。建议选 10—20 秒清晰的单人片段，支持 10—60 秒。')
                        gr.Markdown('**可以读这一段**\n\n傍晚的风掠过树梢，小狐狸停下脚步，听见远处传来一声轻轻的呼唤。它深吸一口气，决定再往前走一步。', elem_classes='sample-script')
                    with gr.Column(min_width=0, scale=7, elem_classes='studio-panel'):
                        clone_source = gr.Radio(
                            [('上传或录制音频', 'audio'), ('从视频取声', 'video')],
                            value='audio', label='样本来源',
                        )
                        sample = gr.Audio(sources=['upload','microphone'], type='filepath',
                                          editable=False, label='参考声音')
                        video = gr.File(file_types=list(VIDEO_EXTENSIONS), type='filepath', label='参考视频',
                                        height=125, visible=False)
                        with gr.Accordion('裁剪与试听选段', open=False, elem_classes='fold') as clip_options:
                            gr.Markdown('视频支持 MP4、MOV，最大 100 MB。音频最大 10 MB。时长填 0 表示读到末尾。')
                            with gr.Row(elem_classes='fields'):
                                clip_start = gr.Number(value=0, label='选段起点（秒）', minimum=0, min_width=0)
                                clip_length = gr.Number(value=0, label='选段时长（秒）',
                                                        minimum=0, maximum=60, min_width=0)
                            preview = gr.Button('试听参考片段', size='sm')
                            preview_audio = gr.Audio(label='处理后的参考片段', interactive=False, visible=False, buttons=[])
                            preview_status = gr.Textbox(label='样本检查', value='等待选择片段',
                                                        interactive=False, elem_classes='status-line')
                        with gr.Row(elem_classes='fields'):
                            clone_name = gr.Textbox(label='专属音色名称', max_length=30, placeholder='例如：我的故事声音', min_width=0)
                            clone_model = gr.Dropdown(['cosyvoice-v2','cosyvoice-v3-flash'], value='cosyvoice-v2', label='克隆目标模型', min_width=0)
                        consent = gr.Checkbox(label='我有权使用这段声音，并同意提交所选片段创建音色')
                        clone_btn = gr.Button('创建专属音色', variant='primary')
                        clone_status = gr.Textbox(label='音色创建状态', value='等待参考录音', interactive=False, lines=1, max_lines=3, elem_classes='status-line')
                with gr.Column(min_width=0, elem_classes='studio-panel'):
                    gr.HTML(section_title('音色创建记录', 'page'))
                    _, _, enrollment = clone_service()
                    jobs = enrollment.jobs()
                    clone_jobs = gr.Dropdown([(j['name'],j['id']) for j in jobs], label='已有创建任务', value=jobs[-1]['id'] if jobs else None)
                    query = gr.Button('查询音色状态', size='sm')
                preview_event = preview.click(
                    preview_sample, [clone_source,sample,video,clip_start,clip_length], [preview_audio,preview_status],
                    concurrency_limit=1, api_visibility='private',
                )
                def change_sample_source(source):
                    from_video = source == 'video'
                    return gr.update(visible=not from_video), gr.update(visible=from_video), gr.update(open=from_video)
                clone_source.change(change_sample_source, clone_source, [sample,video,clip_options],
                                    queue=False, api_visibility='private')
                gr.on([clone_source.change, sample.change, video.change, clip_start.change, clip_length.change],
                      lambda: (gr.update(value=None, visible=False), '请重新试听选段。', False),
                      outputs=[preview_audio,preview_status,consent], queue=False,
                      cancels=[preview_event], api_visibility='private')
                clone_btn.click(clone_predict, [sample,clone_name,consent,clone_model,clone_source,video,clip_start,clip_length],
                                [clone_status,clone_jobs,voice,category], concurrency_limit=1, concurrency_id='clone')
                query.click(query_clone, clone_jobs, [clone_status,voice,category], concurrency_limit=1, concurrency_id='clone')
            with gr.Tab('作品与评价', id='library', elem_id='library-tab'):
                loaded_work = gr.State(None)
                gr.HTML(page_title('作品与评价', '翻阅保存的手稿，试听同一篇故事的不同声音。'))
                with gr.Column(min_width=0, elem_classes='studio-panel'):
                    gr.HTML(section_title('作品书架', 'page'))
                    history = gr.Dropdown(history_choices(), label='选择已保存的作品', value=None)
                    with gr.Row(elem_classes='actions'):
                        load = gr.Button('加载作品', size='sm')
                        refresh = gr.Button('刷新作品列表', size='sm')
                    history_status = gr.Textbox(label='记录状态', value='选择作品后可查看正文和朗读版本', interactive=False, elem_classes='status-line')
                    saved_text = gr.Textbox(label='保存的故事', lines=6, max_lines=15, interactive=False)
                with gr.Column(min_width=0, elem_classes='studio-panel'):
                    gr.HTML(section_title('对照试听', 'headphones'))
                    with gr.Row(elem_classes='duet'):
                        with gr.Column(min_width=0):
                            select_a = gr.Dropdown(label='音频 A')
                            player_a = gr.Audio(label='试听 A', interactive=False)
                        with gr.Column(min_width=0):
                            select_b = gr.Dropdown(label='音频 B')
                            player_b = gr.Audio(label='试听 B', interactive=False)
                    with gr.Accordion('评价这次创作', open=False, elem_classes='fold'):
                        score_labels = ['情节完整性','语言生动性','主题契合度','可朗读性','语音自然度','用户满意度']
                        scores = []
                        for start in (0, 3):
                            with gr.Row(elem_classes='score-row'):
                                scores.extend(gr.Slider(1,5,value=3,step=1,label=x, min_width=0) for x in score_labels[start:start+3])
                        comment = gr.Textbox(label='评价与问题记录', lines=3, placeholder='记录情节、读音或停顿上的具体感受')
                        rated = gr.Checkbox(label='我已阅读故事并实际试听所选音频 A')
                        rate_btn = gr.Button('保存评价')
                with gr.Accordion('下载与测试记录', open=False, elem_classes='fold'):
                    text_file = gr.File(label='故事文本文件', interactive=False)
                    export_btn = gr.Button('导出该作品的文本、音频与测试记录')
                    export_file = gr.File(label='作品测试包', interactive=False)
                    details = gr.JSON(label='作品记录')
                refresh.click(refresh_history, history, history, queue=False, api_visibility='private')
                rid.change(refresh_history, history, history, queue=False, api_visibility='private')
                evaluation_outputs = scores + [comment,rated]
                def clear_evaluation():
                    return [3]*6 + ['',False]
                load_outputs = [saved_text,details,select_a,select_b,player_a,player_b,text_file,history_status,loaded_work]
                def show_work(selected):
                    return [*load_history(selected), *clear_evaluation(), None]
                gr.on([load.click, history.change], show_work, history,
                      load_outputs + evaluation_outputs + [export_file], queue=False, api_visibility='private')
                def switch_audio_a(r, a):
                    return [history_audio(r, a)] + clear_evaluation()
                select_a.input(switch_audio_a, [loaded_work,select_a], [player_a]+evaluation_outputs, queue=False)
                select_b.input(history_audio, [loaded_work,select_b], player_b, queue=False)
                rate_btn.click(save_rating, [loaded_work,select_a,rated]+scores+[comment], [history_status,details])
                def export(r):
                    try:
                        return str(services()[1].export(r)), '作品测试包已生成。'
                    except Exception as exc:
                        return None, public_error(exc)
                export_btn.click(export, loaded_work, [export_file,history_status])
        def open_work(selected):
            return gr.Tabs(selected='library'), gr.Dropdown(choices=history_choices(), value=selected)
        for button, record_id in zip(recent_buttons, recent_ids):
            button.click(open_work, inputs=record_id, outputs=[tabs, history], queue=False, api_visibility='private')
        shelf_outputs = [shelf_heading] + recent_buttons + recent_ids
        rid.change(refresh_shelf, outputs=shelf_outputs, queue=False, api_visibility='private')
        refresh.click(refresh_shelf, outputs=shelf_outputs, queue=False, api_visibility='private')
        demo.load(refresh_shelf, outputs=shelf_outputs, queue=False, api_visibility='private')
        with gr.Accordion('使用与配置说明', open=False, elem_id='setup-notes', elem_classes='fold'):
            gr.Markdown('生成后可在手稿中直接修改正文。换声音后点击“只重新合成语音”。准备好本人音色后，可在“讲述声音”中选择。\n\n'+settings.summary()+' 详细配置见 README.md，修改 .env 后请重启应用。')
    return demo


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=7860)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    settings = Settings.from_env()
    print(settings.summary())
    build_app().queue(default_concurrency_limit=1, max_size=16).launch(
        server_name='127.0.0.1', server_port=args.port, share=False,
        inbrowser=not args.no_browser, show_error=False, max_file_size=MAX_VIDEO_BYTES,
        allowed_paths=[str(settings.results_dir), str(ASSETS)], blocked_paths=[str(ROOT / '.env'), str(ROOT / 'data')],
        theme=gr.themes.Base(font=['Instrument Sans','Microsoft YaHei','sans-serif']), css=stylesheet(),
        footer_links=[],
    )
