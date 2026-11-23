const root = element.querySelector(".reading");
if (root && !root.dataset.playerReady) {
  root.dataset.playerReady = "true";
  const audio = root.querySelector("audio");
  const controls = root.querySelector(".transport");
  const play = root.querySelector(".audition");
  const seek = root.querySelector("input");
  const time = root.querySelector("time");
  const bars = Array.from(root.querySelectorAll(".bars i"));
  const title = root.querySelector("h2").textContent;
  const message = root.querySelector(".play-error");
  const clock = t => Math.floor(t / 60) + ":" + String(Math.floor(t % 60)).padStart(2, "0");
  function sync() {
    const elapsed = audio.currentTime;
    const duration = Number.isFinite(audio.duration) ? audio.duration : Number(seek.max);
    const active = !audio.paused && !audio.ended;
    play.setAttribute("aria-pressed", String(active));
    play.setAttribute("aria-label", (active ? "暂停" : "播放") + title);
    time.textContent = clock(elapsed) + " / " + clock(duration);
    seek.max = String(duration);
    seek.value = String(elapsed);
    seek.setAttribute("aria-valuetext", clock(elapsed));
    bars.forEach((bar, i) => bar.classList.toggle("heard", i < elapsed / duration * bars.length));
  }
  play.addEventListener("click", async () => {
    if (!audio.paused) { audio.pause(); return; }
    try { await audio.play(); message.textContent = ""; }
    catch { message.textContent = "暂时无法播放，请刷新页面重试。"; }
  });
  seek.addEventListener("input", () => {
    if (Number.isFinite(audio.duration)) audio.currentTime = Number(seek.value);
  });
  for (const event of ["timeupdate", "loadedmetadata", "play", "pause", "ended"]) {
    audio.addEventListener(event, sync);
  }
  const tabPanel = root.closest('[role="tabpanel"]');
  if (tabPanel) {
    const observer = new MutationObserver(() => {
      if (!tabPanel.getClientRects().length) audio.pause();
      if (!root.isConnected) observer.disconnect();
    });
    observer.observe(tabPanel, { attributes: true });
  }
  controls.hidden = false;
  audio.controls = false;
  sync();
}