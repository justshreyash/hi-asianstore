/**
 * Hindi-Asian Stream Player & Ingestion Widget
 * Version: 2.0.0
 * Embed snippet:
 *   <div id="hindi-dub-widget" data-tmdb="93405" data-title="Squid Game"></div>
 *   <script src="https://your-api.vercel.app/widget.js" async></script>
 */

(function () {
  'use strict';

  // Determine API Base URL
  const scriptTag = document.currentScript || document.querySelector('script[src*="widget.js"]');
  let API_BASE = window.HINDI_DUB_API_BASE;
  if (!API_BASE && scriptTag && scriptTag.src) {
    try {
      const parsed = new URL(scriptTag.src);
      API_BASE = parsed.origin;
    } catch (e) {
      API_BASE = 'http://127.0.0.1:8000';
    }
  }
  if (!API_BASE) API_BASE = 'http://127.0.0.1:8000';

  // Inject Widget Styles
  const style = document.createElement('style');
  style.textContent = `
    .hi-dub-container {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #0f172a;
      color: #f8fafc;
      border-radius: 12px;
      overflow: hidden;
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.4);
      border: 1px solid #1e293b;
      margin: 16px 0;
      max-width: 100%;
    }
    .hi-dub-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 12px 18px;
      background: #1e293b;
      border-bottom: 1px solid #334155;
    }
    .hi-dub-badge {
      display: inline-flex;
      align-items: center;
      gap: 6px;
      background: linear-gradient(135deg, #e11d48, #be123c);
      color: #fff;
      padding: 4px 10px;
      border-radius: 20px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.5px;
      text-transform: uppercase;
    }
    .hi-dub-video-wrap {
      position: relative;
      width: 100%;
      background: #000;
      aspect-ratio: 16 / 9;
      display: flex;
      align-items: center;
      justify-content: center;
    }
    .hi-dub-video-wrap video {
      width: 100%;
      height: 100%;
      object-fit: contain;
    }
    .hi-dub-controls {
      padding: 14px 18px;
      display: flex;
      flex-wrap: wrap;
      gap: 12px;
      align-items: center;
      justify-content: space-between;
      background: #0f172a;
    }
    .hi-dub-select {
      background: #1e293b;
      color: #f8fafc;
      border: 1px solid #334155;
      padding: 8px 12px;
      border-radius: 6px;
      font-size: 14px;
      outline: none;
      cursor: pointer;
    }
    .hi-dub-select:hover {
      border-color: #e11d48;
    }
    .hi-dub-btn {
      background: #e11d48;
      color: #fff;
      border: none;
      padding: 8px 16px;
      border-radius: 6px;
      font-weight: 600;
      cursor: pointer;
      display: inline-flex;
      align-items: center;
      gap: 6px;
      transition: all 0.2s;
    }
    .hi-dub-btn:hover {
      background: #f43f5e;
      transform: translateY(-1px);
    }
    .hi-dub-card {
      padding: 24px;
      text-align: center;
    }
    .hi-dub-card h4 {
      margin: 0 0 8px;
      font-size: 16px;
      color: #f8fafc;
    }
    .hi-dub-card p {
      margin: 0 0 16px;
      font-size: 13px;
      color: #94a3b8;
    }
    .hi-dub-progress {
      width: 100%;
      height: 6px;
      background: #1e293b;
      border-radius: 3px;
      overflow: hidden;
      margin-top: 14px;
    }
    .hi-dub-progress-bar {
      height: 100%;
      background: linear-gradient(90deg, #e11d48, #3b82f6);
      width: 0%;
      transition: width 0.3s ease;
      animation: hiDubPulse 2s infinite linear;
    }
    @keyframes hiDubPulse {
      0% { opacity: 0.8; }
      50% { opacity: 1; }
      100% { opacity: 0.8; }
    }
  `;
  document.head.appendChild(style);

  // Dynamic HLS.js Loader
  function ensureHls(callback) {
    if (window.Hls) {
      callback();
      return;
    }
    const s = document.createElement('script');
    s.src = 'https://cdnjs.cloudflare.com/ajax/libs/hls.js/1.5.7/hls.min.js';
    s.onload = callback;
    document.head.appendChild(s);
  }

  // Initialize Widgets
  function initWidgets() {
    const targets = document.querySelectorAll('#hindi-dub-widget, .hindi-dub-player');
    targets.forEach(renderWidget);
  }

  async function renderWidget(container) {
    const tmdbId = container.getAttribute('data-tmdb');
    const title = container.getAttribute('data-title') || '';

    if (!tmdbId && !title) {
      container.innerHTML = '<div style="color:red; font-size:12px;">Missing data-tmdb or data-title attribute.</div>';
      return;
    }

    container.innerHTML = `
      <div class="hi-dub-container">
        <div class="hi-dub-card">
          <p>🔍 Checking Hindi Dub availability...</p>
        </div>
      </div>
    `;

    try {
      const res = await fetch(`${API_BASE}/v1/hi-asian/check?tmdb_id=${tmdbId || ''}&title=${encodeURIComponent(title)}`);
      const data = await res.json();

      if (data.status === 'available') {
        renderPlayer(container, data);
      } else if (data.status === 'in_queue') {
        renderInQueue(container, data);
      } else {
        renderUnavailable(container, title);
      }
    } catch (e) {
      container.innerHTML = `
        <div class="hi-dub-container">
          <div class="hi-dub-card">
            <p>⚠️ Unable to connect to streaming engine. (${e.message})</p>
          </div>
        </div>
      `;
    }
  }

  // STATE 1: Ready to Stream
  function renderPlayer(container, drama) {
    const episodes = drama.episodes || [];
    const episodeOptions = episodes.map(ep => `<option value="${ep.episode_number}">Episode ${ep.episode_number}: ${ep.title}</option>`).join('');

    container.innerHTML = `
      <div class="hi-dub-container">
        <div class="hi-dub-header">
          <span class="hi-dub-badge">🔊 Hindi Dubbed • ${drama.quality || '1080p'} FHD</span>
          <span style="font-size: 12px; color: #94a3b8;">${episodes.length} Episodes Ready</span>
        </div>
        <div class="hi-dub-video-wrap">
          <video id="hi-dub-video-${drama.tmdb_id}" controls playsinline poster=""></video>
        </div>
        <div class="hi-dub-controls">
          <div style="display: flex; gap: 8px; align-items: center;">
            <label style="font-size: 13px; color: #94a3b8;">Select Episode:</label>
            <select class="hi-dub-select" id="hi-dub-ep-select-${drama.tmdb_id}">
              ${episodeOptions}
            </select>
          </div>
          <div style="display: flex; gap: 8px; align-items: center;">
            <select class="hi-dub-select" id="hi-dub-host-select-${drama.tmdb_id}">
              <option value="auto">CDN: Auto Fast</option>
              <option value="playmate">Mirror 1: Playmate</option>
              <option value="vidara">Mirror 2: Vidara</option>
              <option value="savefiles">Mirror 3: SaveFiles</option>
            </select>
            <button class="hi-dub-btn" id="hi-dub-play-btn-${drama.tmdb_id}">▶ Stream</button>
          </div>
        </div>
      </div>
    `;

    const video = container.querySelector(`#hi-dub-video-${drama.tmdb_id}`);
    const epSelect = container.querySelector(`#hi-dub-ep-select-${drama.tmdb_id}`);
    const hostSelect = container.querySelector(`#hi-dub-host-select-${drama.tmdb_id}`);
    const playBtn = container.querySelector(`#hi-dub-play-btn-${drama.tmdb_id}`);

    let hlsInstance = null;

    async function loadEpisode(epNum) {
      playBtn.textContent = '⏳ Resolving...';
      playBtn.disabled = true;

      try {
        const streamRes = await fetch(`${API_BASE}/v1/hi-asian/${drama.tmdb_id}/resolve-m3u8?ep=${epNum}`);
        const streamData = await streamRes.json();
        const hosts = streamData.hosts || {};

        let streamUrl = null;
        const preferredHost = hostSelect.value;
        if (preferredHost !== 'auto' && hosts[preferredHost] && hosts[preferredHost].m3u8) {
          streamUrl = hosts[preferredHost].m3u8;
        } else {
          // Auto fallback
          streamUrl = (hosts.playmate && hosts.playmate.m3u8) ||
                      (hosts.vidara && hosts.vidara.m3u8) ||
                      (hosts.savefiles && hosts.savefiles.m3u8);
        }

        if (!streamUrl) {
          alert('Stream mirror is currently encoding or undergoing sync. Please choose another mirror.');
          playBtn.textContent = '▶ Stream';
          playBtn.disabled = false;
          return;
        }

        ensureHls(() => {
          if (Hls.isSupported()) {
            if (hlsInstance) hlsInstance.destroy();
            hlsInstance = new Hls({ maxBufferLength: 30 });
            hlsInstance.loadSource(streamUrl);
            hlsInstance.attachMedia(video);
            hlsInstance.on(Hls.Events.MANIFEST_PARSED, () => {
              video.play().catch(() => {});
            });
          } else if (video.canPlayType('application/vnd.apple.mpegurl')) {
            video.src = streamUrl;
            video.play().catch(() => {});
          }
          playBtn.textContent = '✓ Playing';
          playBtn.disabled = false;
        });
      } catch (err) {
        alert('Failed to resolve stream: ' + err.message);
        playBtn.textContent = '▶ Stream';
        playBtn.disabled = false;
      }
    }

    epSelect.addEventListener('change', () => loadEpisode(epSelect.value));
    playBtn.addEventListener('click', () => loadEpisode(epSelect.value));

    // Auto-load episode 1
    if (episodes.length > 0) {
      loadEpisode(episodes[0].episode_number);
    }
  }

  // STATE 2: In Queue / Request Ingest
  function renderInQueue(container, data) {
    container.innerHTML = `
      <div class="hi-dub-container">
        <div class="hi-dub-header">
          <span class="hi-dub-badge" style="background:#f59e0b;">⚡ Ingestion Queue</span>
        </div>
        <div class="hi-dub-card">
          <h4>Hindi Dub Available on Source</h4>
          <p>This drama has been discovered on KDramaLover and is queued for cloud transcoding.</p>
          <button class="hi-dub-btn" id="hi-dub-req-btn">⚡ Request Instant Upload (~2-3 min)</button>
          <div class="hi-dub-progress" style="display:none;" id="hi-dub-progress-wrap">
            <div class="hi-dub-progress-bar" id="hi-dub-bar"></div>
          </div>
          <p id="hi-dub-eta-msg" style="margin-top: 10px; display:none;"></p>
        </div>
      </div>
    `;

    const reqBtn = container.querySelector('#hi-dub-req-btn');
    const pWrap = container.querySelector('#hi-dub-progress-wrap');
    const pBar = container.querySelector('#hi-dub-bar');
    const pMsg = container.querySelector('#hi-dub-eta-msg');

    reqBtn.addEventListener('click', async () => {
      reqBtn.disabled = true;
      reqBtn.textContent = '⏳ Request Dispatched...';
      pWrap.style.display = 'block';
      pMsg.style.display = 'block';
      pMsg.textContent = 'Estimated time remaining: ~180 seconds. Checking status...';

      try {
        await fetch(`${API_BASE}/v1/hi-asian/request-ingest`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ tmdb_id: data.tmdb_id, title: data.title })
        });
      } catch (e) {}

      let elapsed = 0;
      const totalEta = 180;
      const timer = setInterval(async () => {
        elapsed += 5;
        const pct = Math.min(Math.round((elapsed / totalEta) * 100), 95);
        pBar.style.width = pct + '%';
        pMsg.textContent = `Processing upload mirrors... ETA: ~${Math.max(totalEta - elapsed, 10)}s`;

        // Poll check
        if (elapsed % 15 === 0) {
          try {
            const check = await fetch(`${API_BASE}/v1/hi-asian/check?tmdb_id=${data.tmdb_id}`);
            const checkData = await check.json();
            if (checkData.status === 'available') {
              clearInterval(timer);
              pBar.style.width = '100%';
              pMsg.textContent = '✓ Ready! Loading stream player...';
              setTimeout(() => renderWidget(container), 1000);
            }
          } catch (e) {}
        }
      }, 5000);
    });
  }

  // STATE 3: Unavailable
  function renderUnavailable(container, title) {
    container.innerHTML = `
      <div class="hi-dub-container" style="background: transparent; border: 1px dashed #334155;">
        <div style="padding: 12px 18px; display: flex; align-items: center; justify-content: space-between;">
          <span style="font-size: 13px; color: #94a3b8;">ℹ️ Hindi Dub not yet released for <b>${title || 'this drama'}</b>. Available in Original Audio.</span>
          <span style="font-size: 11px; color: #64748b;">Korean / Chinese Audio</span>
        </div>
      </div>
    `;
  }

  // Self-initialize on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', initWidgets);
  } else {
    initWidgets();
  }
})();
