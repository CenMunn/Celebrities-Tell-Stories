"""创作界面的排版、图标，以及可以离线试听的课堂作品。"""
from html import escape
import json
from urllib.parse import quote

from config import ROOT


UI = ROOT / "ui"
ASSETS = UI / "assets"


def asset_url(filename):
    path = quote((ASSETS / filename).resolve().as_posix(), safe="/:")
    return f"./gradio_api/file={path}"


def stylesheet():
    css = (UI / "studio.css").read_text("utf-8")
    return css.replace("__FONT_URL__", asset_url("InstrumentSans.ttf")).replace(
        "__SERIF_URL__", asset_url("NotoSerifSC-Story.woff2")
    )


ICONS = {
    "book": '<path d="M2 8c4-1 7.5.3 10 3 2.5-2.7 6-4 10-3v12c-4-1-7.5.3-10 3-2.5-2.7-6-4-10-3z"/><path d="M12 11v12M6.5 2.5v3M10 0v5M13.5 1v5M17 3v2"/>',
    "headphones": '<path d="M3 15v-3a9 9 0 0 1 18 0v3M3 14a2 2 0 0 1 2-2h2v8H5a2 2 0 0 1-2-2zm18 0a2 2 0 0 0-2-2h-2v8h2a2 2 0 0 0 2-2z"/>',
    "pen": '<path d="m5 16-1 4 4-1L20 7l-3-3zM14 7l3 3"/>',
    "page": '<path d="M5 3h10l4 4v14H5zM14 3v5h5M8 12h8M8 16h6"/>',
}


def icon(name):
    return f'<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">{ICONS[name]}</svg>'


BRAND = f'<div class="wordmark">{icon("book")}<span>名人讲故事</span></div>'


def page_title(title, text):
    return f'<header class="page-title"><h1>{escape(title)}</h1><p>{escape(text)}</p></header>'


def section_title(title, symbol):
    return f'<h2 class="section-title">{icon(symbol)}{escape(title)}</h2>'


def featured_reading():
    reading = json.loads((ASSETS / "reading.json").read_text("utf-8"))
    duration = int(reading["duration"])
    peak = max(reading["wave"]) or 1
    bars = "".join(f'<i style="height:{max(8, int(100 * level / peak))}%"></i>' for level in reading["wave"])
    title, excerpt, genre, voice = (escape(reading[k]) for k in ("title", "excerpt", "genre", "voice"))
    paragraphs = "".join(f"<p>{escape(text)}</p>" for text in reading["paragraphs"])
    return f'''<article class="reading">
      <img class="cover" src="{asset_url("starlight-forest.webp")}" alt="童话插画，小狐狸在三颗星下抬头望向枝上的小鸟">
      <div class="jacket">
        <div class="reading-kind"><span>{icon("headphones")} 作品试听</span><span>{genre} · {reading["words"]} 字</span></div>
        <h2>{title}</h2><p class="quote">{excerpt}</p>
        <div class="byline">{voice} 朗读</div>
        <audio controls preload="metadata" aria-label="试听{title}" src="{asset_url("starlight-reading.mp3")}"></audio>
        <div class="transport" hidden>
          <button type="button" class="audition" aria-label="播放{title}" aria-pressed="false">
            <svg aria-hidden="true" viewBox="0 0 20 20"><path class="start" fill="currentColor" d="M6 3.5v13l10-6.5z"/><path class="pause" fill="currentColor" d="M5 4h3v12H5zm7 0h3v12h-3z"/></svg>
          </button>
          <div class="seek"><div class="bars" aria-hidden="true">{bars}</div>
            <input aria-label="试听播放位置" type="range" min="0" max="{reading["duration"]}" step="0.1" value="0">
          </div>
          <time>0:00 / {duration//60}:{duration%60:02}</time>
        </div>
        <p class="play-error" role="status"></p>
        <details class="liner"><summary>阅读这篇故事</summary><div class="liner-text" tabindex="0" aria-label="小狐狸的星光地图全文">{paragraphs}</div></details>
      </div></article>'''


PLAYER_JS = (UI / "reading.js").read_text("utf-8")
