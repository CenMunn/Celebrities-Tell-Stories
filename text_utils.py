"""输入校验和无损文本分段；不依赖网络。"""
import unicodedata


def count_words(text: str) -> int:
    """项目字数口径：统计字母、汉字和数字，忽略标点、空格、表情。"""
    return sum(ch.isalnum() for ch in text)


def validate_theme(theme: str) -> str:
    theme = (theme or '').strip()
    if not theme or not any(ch.isalnum() for ch in theme):
        raise ValueError('请输入含文字或数字的故事主题。')
    if len(theme) > 500:
        raise ValueError('主题最多 500 字符，请提炼关键词。')
    if any(unicodedata.category(ch) == 'Cc' and ch not in '\n\t\r' for ch in theme):
        raise ValueError('主题含不可见控制字符，请清理后重试。')
    return theme


def split_text_into_chunks(text: str, max_chunk_size: int = 800) -> list[str]:
    """优先在标点或换行处分段；超长单句强制切分，不产生空段，不丢字符。"""
    if max_chunk_size < 1:
        raise ValueError('分段长度必须大于零。')
    chunks = []
    start = 0
    boundaries = '。！？!?；;\n'
    while start < len(text):
        end = min(start + max_chunk_size, len(text))
        if end < len(text):
            points = [i + 1 for i in range(start, end) if text[i] in boundaries]
            if points:
                end = points[-1]
        chunks.append(text[start:end])
        start = end
    return chunks
