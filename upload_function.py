"""可选 OSS 适配器。普通播放和 Data URI 克隆无需 OSS。"""
from contextlib import contextmanager
from pathlib import Path
import uuid


@contextmanager
def temporary_audio_url(file_path, settings, expiry=600):
    """上传到私有 bucket，返回限时签名 URL，调用结束后清理本次对象。"""
    import oss2
    if not all([settings.oss_endpoint, settings.oss_bucket, settings.oss_key, settings.oss_secret]):
        raise ValueError('OSS 配置不完整。')
    path = Path(file_path)
    if not path.is_file() or path.stat().st_size > 10 * 1024 * 1024:
        raise ValueError('请选择不超过 10 MB 的音频文件。')
    auth = oss2.Auth(settings.oss_key, settings.oss_secret)
    endpoint = settings.oss_endpoint
    if not endpoint.startswith('https://'):
        endpoint = 'https://' + endpoint.removeprefix('http://')
    bucket = oss2.Bucket(auth, endpoint, settings.oss_bucket)
    key = f'story-reference/{uuid.uuid4().hex}{path.suffix.lower()}'
    bucket.put_object_from_file(key, str(path), headers={'Content-Type':'audio/wav'})
    try:
        yield bucket.sign_url('GET', key, expiry, slash_safe=True)
    finally:
        bucket.delete_object(key)
