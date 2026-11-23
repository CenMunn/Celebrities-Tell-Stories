"""固定从项目 .env 或指定配置路径读取；密钥不出现在 repr 或运行记录中。"""
import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent


@dataclass(frozen=True)
class Settings:
    llm_key: str = field(default='', repr=False)
    llm_base_url: str = 'https://dashscope.aliyuncs.com/compatible-mode/v1'
    llm_model: str = 'qwen-plus'
    temperature: float = 0.8
    timeout: float = 90
    tts_key: str = field(default='', repr=False)
    workspace: str = ''
    region: str = 'cn-beijing'
    chunk_size: int = 800
    results_dir: Path = ROOT / 'results'
    oss_endpoint: str = ''
    oss_bucket: str = ''
    oss_key: str = field(default='', repr=False)
    oss_secret: str = field(default='', repr=False)

    @classmethod
    def from_env(cls, env_file=None):
        load_dotenv(env_file or os.getenv('STORY_ENV_FILE') or ROOT / '.env', override=False)
        workspace = os.getenv('DASHSCOPE_WORKSPACE_ID', '').strip()
        region = os.getenv('DASHSCOPE_REGION', 'cn-beijing').strip()
        endpoint = (f'https://{workspace}.{region}.maas.aliyuncs.com/compatible-mode/v1'
                    if workspace else 'https://dashscope.aliyuncs.com/compatible-mode/v1')
        return cls(
            llm_key=os.getenv('LLM_API_KEY') or os.getenv('DASHSCOPE_API_KEY', ''),
            llm_base_url=os.getenv('LLM_BASE_URL', endpoint).strip(),
            llm_model=os.getenv('LLM_MODEL', 'qwen-plus').strip(),
            temperature=float(os.getenv('LLM_TEMPERATURE', '0.8')),
            timeout=float(os.getenv('API_TIMEOUT', '90')),
            tts_key=os.getenv('DASHSCOPE_API_KEY', ''), workspace=workspace, region=region,
            chunk_size=int(os.getenv('TTS_CHUNK_SIZE', '800')),
            results_dir=Path(os.getenv('STORY_RESULTS_DIR', str(ROOT / 'results'))).resolve(),
            oss_endpoint=os.getenv('OSS_ENDPOINT', ''), oss_bucket=os.getenv('OSS_BUCKET', ''),
            oss_key=os.getenv('OSS_ACCESS_KEY_ID', ''), oss_secret=os.getenv('OSS_ACCESS_KEY_SECRET', ''),
        )

    def require_llm(self):
        if not self.llm_key:
            raise ValueError('尚未配置 LLM_API_KEY（百炼也可使用 DASHSCOPE_API_KEY）。')
        if not self.llm_base_url.startswith('https://'):
            raise ValueError('LLM_BASE_URL 需要使用 HTTPS 地址。')
        if not self.llm_model or not 0 <= self.temperature <= 2:
            raise ValueError('请检查 LLM_MODEL 和 LLM_TEMPERATURE。')

    def require_tts(self):
        if not self.tts_key:
            raise ValueError('尚未配置 DASHSCOPE_API_KEY。')
        if not 100 <= self.chunk_size <= 20000:
            raise ValueError('TTS_CHUNK_SIZE 需要在 100—20000 之间。')

    def summary(self):
        return (f'文本接口：{"已配置" if self.llm_key else "待配置"}；模型：{self.llm_model}；'
                f'语音接口：{"已配置" if self.tts_key else "待配置"}；地域：{self.region}。')
