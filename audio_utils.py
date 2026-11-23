"""WAV 写入以及语音识别、音色克隆共用的本地音频选段。"""
import base64
from io import BytesIO
import math
from pathlib import Path
from shutil import which
import subprocess
from tempfile import TemporaryDirectory
import wave
import numpy as np
import soundfile as sf


MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 100 * 1024 * 1024
VIDEO_EXTENSIONS = ('.mp4', '.mov')
REFERENCE_MIN_SECONDS = 10
REFERENCE_MAX_SECONDS = 60


def write_pcm_wav(chunks, path, sample_rate=22050):
    chunks = list(chunks)
    if not chunks or any(not x or len(x) % 2 for x in chunks):
        raise ValueError('语音接口返回了空音频或不完整的 PCM 样本。')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), 'wb') as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(sample_rate)
        for chunk in chunks:
            f.writeframes(chunk)
    frames = sum(len(x) // 2 for x in chunks)
    return {'duration_seconds': round(frames / sample_rate, 3), 'sample_rate': sample_rate, 'chunks': len(chunks)}


def _read_first_channel(path, start, duration, maximum, minimum_rate):
    try:
        with sf.SoundFile(path) as source:
            rate, channels = source.samplerate, source.channels
            if rate < minimum_rate:
                raise ValueError(f'参考音频采样率需要至少 {minimum_rate} Hz。')
            if start >= source.frames / rate:
                raise ValueError('选段起点已到达录音末尾，请提前起点。')
            frame = round(start * rate)
            source.seek(frame)
            count = round(duration * rate) if duration is not None else int(maximum * rate) + 1
            data = source.read(count, dtype='float32', always_2d=True)[:, 0].copy()
    except (sf.LibsndfileError, OSError):
        raise ValueError('无法解码音频，请上传可正常播放的 WAV 或 MP3。') from None
    return data, rate, channels


def _container_clip(path, start, duration, maximum):
    ffmpeg = which('ffmpeg')
    if not ffmpeg:
        raise ValueError('提取 MP4、MOV 或 M4A 需要安装 FFmpeg。也可以先导出 WAV 或 MP3 再上传。')
    with TemporaryDirectory(prefix='story_media_') as folder:
        dest = Path(folder) / 'excerpt.wav'
        # 多解码一秒用来判断未指定时长的原片是否超限。
        read_seconds = duration if duration is not None else maximum + 1
        command = [
            ffmpeg, '-nostdin', '-loglevel', 'error', '-protocol_whitelist', 'file',
            '-f', 'mov', '-ss', f'{start:.6f}', '-i', str(path),
            '-map', '0:a:0', '-t', f'{read_seconds:.6f}', '-vn',
            '-af', 'pan=mono|c0=c0', '-ar', '16000', '-c:a', 'pcm_s16le', str(dest),
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, timeout=45)
        except subprocess.TimeoutExpired:
            raise ValueError('提取音轨超时，请缩短视频或先导出音频。') from None
        except (subprocess.CalledProcessError, OSError):
            raise ValueError('无法提取音轨，请检查文件是否包含可播放的人声。') from None
        return _read_first_channel(dest, 0, duration, maximum, 16000)


def read_voice_clip(path, *, minimum, maximum, start=0, duration=None,
                    allow_video=False, minimum_rate=0):
    """读取指定区间，返回单声道 PCM16 和实际采样信息。"""
    start = float(start or 0)
    if not math.isfinite(start) or start < 0:
        raise ValueError('选段起点应为大于等于 0 的秒数。')
    if duration is not None:
        duration = float(duration)
        if not minimum <= duration <= maximum:
            raise ValueError(f'选段时长应为 {minimum:g}—{maximum:g} 秒。')

    source = Path(path).resolve() if path else None
    if source is None or not source.is_file():
        raise ValueError('请先上传文件或完成录音。')
    suffix = source.suffix.lower()
    is_video = suffix in VIDEO_EXTENSIONS
    if is_video and not allow_video:
        raise ValueError('请使用音频文件。')
    max_bytes = MAX_VIDEO_BYTES if is_video else MAX_AUDIO_BYTES
    if source.stat().st_size > max_bytes:
        raise ValueError(f'请选择不超过 {max_bytes // (1024 * 1024)} MB 的文件。')

    if is_video or suffix == '.m4a':
        samples, rate, channels = _container_clip(source, start, duration, maximum)
    else:
        samples, rate, channels = _read_first_channel(source, start, duration, maximum, minimum_rate)
    seconds = len(samples) / rate
    if duration is not None and seconds < duration - 1 / rate:
        raise ValueError('选段超出音频末尾，请缩短时长或提前起点。')
    if not minimum <= seconds <= maximum:
        raise ValueError(f'音频需为 {minimum:g}—{maximum:g} 秒，请调整片段或重新录制。')
    rms = float(np.sqrt(np.mean(samples ** 2)))
    if not math.isfinite(rms) or rms < 0.001:
        raise ValueError('音频接近静音，请检查录音。')
    pcm = (np.clip(samples, -1, 32767 / 32768) * 32768).astype('<i2')
    info = {'duration_seconds': round(seconds, 3), 'sample_rate': rate, 'channels': channels,
            'rms': round(rms, 5)}
    return pcm, info


def prepare_reference_audio(path, start=0, duration=None):
    """检查实际选段并导出单声道 PCM16 WAV，供试听与克隆使用。"""
    pcm, info = read_voice_clip(
        path, minimum=REFERENCE_MIN_SECONDS, maximum=REFERENCE_MAX_SECONDS,
        minimum_rate=16000, start=start, duration=duration or None, allow_video=True,
    )
    result = wav_bytes(pcm, info['sample_rate'])
    if len(result) > MAX_AUDIO_BYTES:
        raise ValueError('处理后的参考音频超过 10 MB，请缩短选段或降低采样率。')
    return result, {
        **info, 'channels': 1, 'start_seconds': float(start or 0),
        'source_type': 'video' if Path(path).suffix.lower() in VIDEO_EXTENSIONS else 'audio',
    }


def wav_bytes(pcm, sample_rate):
    buffer = BytesIO()
    with wave.open(buffer, 'wb') as output:
        output.setparams((1, 2, sample_rate, 0, 'NONE', 'not compressed'))
        output.writeframes(pcm.tobytes())
    return buffer.getvalue()


def wav_data_uri(content):
    return 'data:audio/wav;base64,' + base64.b64encode(content).decode('ascii')


def inspect_reference_audio(path):
    _, info = read_voice_clip(
        path, minimum=REFERENCE_MIN_SECONDS, maximum=REFERENCE_MAX_SECONDS, minimum_rate=16000,
    )
    return info


def reference_to_wav(path, dest):
    content, _ = prepare_reference_audio(path)
    dest = Path(dest)
    dest.write_bytes(content)
    return dest
