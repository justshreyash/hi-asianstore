/**
 * HindiStream.js - Standalone Client SDK & Button Widget
 * =====================================================
 * Drop-in library for any drama streaming website.
 * Allows checking Hindi dub availability in database & resolving on-the-fly M3U8.
 *
 * Usage:
 *   <script src="hindi_stream.js"></script>
 *   <script>
 *     HindiStream.mountButton({
 *       container: "#hindi-btn-container",
 *       tmdbId: 297640,
 *       season: 1,
 *       episode: 1,
 *       videoElement: "#player",
 *       onStreamReady: (data) => console.log("M3U8:", data.m3u8_url)
 *     });
 *   </script>
 */

(function(window) {
  const DEFAULT_API_BASE = "http://127.0.0.1:8080";

  const HindiStream = {
    apiBase: DEFAULT_API_BASE,

    setApiBase(url) {
      this.apiBase = url.replace(/\/$/, "");
    },

    /**
     * Fast check whether Hindi is available in the database for a given TMDB ID and episode.
     */
    async checkAvailability(tmdbId, season = 1, episode = 1) {
      const url = `${this.apiBase}/api/hindi/check?tmdb_id=${encodeURIComponent(tmdbId)}&season=${season}&episode=${episode}`;
      const res = await fetch(url);
      return await res.json();
    },

    /**
     * Resolve on-the-fly active Master M3U8 stream directly.
     */
    async resolveStream(tmdbId, season = 1, episode = 1) {
      const url = `${this.apiBase}/api/hindi/stream?tmdb_id=${encodeURIComponent(tmdbId)}&season=${season}&episode=${episode}`;
      const res = await fetch(url);
      return await res.json();
    },

    /**
     * List all Hindi-dubbed dramas available in the database.
     */
    async listDramas() {
      const url = `${this.apiBase}/api/hindi/list`;
      const res = await fetch(url);
      return await res.json();
    },

    /**
     * Ensure Hls.js is loaded into the browser document.
     */
    loadHlsJs() {
      return new Promise((resolve, reject) => {
        if (window.Hls) return resolve(window.Hls);
        const script = document.createElement("script");
        script.src = "https://cdn.jsdelivr.net/npm/hls.js@latest";
        script.onload = () => resolve(window.Hls);
        script.onerror = reject;
        document.head.appendChild(script);
      });
    },

    /**
     * Play an M3U8 URL directly in an HTML5 video tag using Hls.js.
     */
    async playInVideo(videoEl, m3u8Url) {
      if (typeof videoEl === "string") {
        videoEl = document.querySelector(videoEl);
      }
      if (!videoEl) {
        console.error("[HindiStream] Video element not found:", videoEl);
        return;
      }

      await this.loadHlsJs();

      if (window.Hls && window.Hls.isSupported()) {
        if (window._currentHlsInstance) {
          window._currentHlsInstance.destroy();
        }
        const hls = new window.Hls({
          enableWorker: true,
          lowLatencyMode: true
        });
        window._currentHlsInstance = hls;
        hls.loadSource(m3u8Url);
        hls.attachMedia(videoEl);
        hls.on(window.Hls.Events.MANIFEST_PARSED, () => {
          videoEl.play().catch(e => console.log("Autoplay prevented:", e));
        });
      } else if (videoEl.canPlayType("application/vnd.apple.mpegurl")) {
        // Native Safari / iOS support
        videoEl.src = m3u8Url;
        videoEl.play().catch(e => console.log("Autoplay prevented:", e));
      } else {
        alert("HLS playback is not supported in this browser.");
      }
    },

    /**
     * Play an embed URL (e.g. Byse) by replacing or wrapping the video element with a responsive iframe.
     */
    playInIframe(videoEl, embedUrl) {
      if (typeof videoEl === "string") {
        videoEl = document.querySelector(videoEl);
      }
      if (!videoEl) {
        console.error("[HindiStream] Video container not found:", videoEl);
        return;
      }

      const parent = videoEl.parentElement || videoEl;
      let iframe = parent.querySelector("iframe.hs-stream-iframe");
      if (!iframe) {
        iframe = document.createElement("iframe");
        iframe.className = "hs-stream-iframe";
        iframe.style.width = "100%";
        iframe.style.height = videoEl.clientHeight && videoEl.clientHeight > 200 ? `${videoEl.clientHeight}px` : "100%";
        iframe.style.minHeight = "480px";
        iframe.style.border = "none";
        iframe.style.borderRadius = "8px";
        iframe.setAttribute("allowfullscreen", "true");
        iframe.setAttribute("webkitallowfullscreen", "true");
        iframe.setAttribute("mozallowfullscreen", "true");
        iframe.setAttribute("allow", "autoplay; fullscreen; encrypted-media; picture-in-picture");
        videoEl.style.display = "none";
        parent.insertBefore(iframe, videoEl);
      }
      iframe.src = embedUrl;
    },

    /**
     * Mount the plug-and-play 'Check Hindi Dub & Stream' button into any DOM element.
     */
    mountButton(options) {
      const {
        container,
        tmdbId,
        season = 1,
        episode = 1,
        videoElement = null,
        apiBase = null,
        onStreamReady = null,
        onNotAvailable = null
      } = options;

      if (apiBase) this.setApiBase(apiBase);

      const targetEl = typeof container === "string" ? document.querySelector(container) : container;
      if (!targetEl) {
        console.error("[HindiStream] Mount container not found:", container);
        return;
      }

      // Inject minimal scoped styles if not already injected
      if (!document.getElementById("hindi-stream-btn-styles")) {
        const style = document.createElement("style");
        style.id = "hindi-stream-btn-styles";
        style.textContent = `
          .hs-btn-wrapper { display: inline-flex; align-items: center; gap: 8px; font-family: system-ui, -apple-system, sans-serif; }
          .hs-btn {
            background: linear-gradient(135deg, #ea580c, #f97316);
            color: #fff;
            border: none;
            padding: 8px 16px;
            font-size: 13px;
            font-weight: 600;
            border-radius: 6px;
            cursor: pointer;
            display: inline-flex;
            align-items: center;
            gap: 6px;
            box-shadow: 0 2px 8px rgba(234, 88, 12, 0.3);
            transition: all 0.2s ease;
          }
          .hs-btn:hover { opacity: 0.92; transform: translateY(-1px); }
          .hs-btn:disabled { opacity: 0.6; cursor: not-allowed; transform: none; }
          .hs-spinner {
            width: 13px;
            height: 13px;
            border: 2px solid rgba(255, 255, 255, 0.3);
            border-top-color: #fff;
            border-radius: 50%;
            animation: hs-spin 0.6s linear infinite;
            display: inline-block;
          }
          @keyframes hs-spin { to { transform: rotate(360deg); } }
          .hs-badge-success { background: rgba(34, 197, 94, 0.15); color: #22c55e; border: 1px solid rgba(34, 197, 94, 0.3); padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
          .hs-badge-fail { background: rgba(239, 68, 68, 0.15); color: #ef4444; border: 1px solid rgba(239, 68, 68, 0.3); padding: 4px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
        `;
        document.head.appendChild(style);
      }

      const wrapper = document.createElement("div");
      wrapper.className = "hs-btn-wrapper";

      const btn = document.createElement("button");
      btn.className = "hs-btn";
      btn.innerHTML = `<span>⚡</span> Check Hindi Dubbed`;

      const statusSpan = document.createElement("span");

      btn.onclick = async () => {
        btn.disabled = true;
        btn.innerHTML = `<span class="hs-spinner"></span> Checking Database...`;
        statusSpan.innerHTML = "";

        try {
          // 1. First fast check in database
          const check = await HindiStream.checkAvailability(tmdbId, season, episode);

          if (!check.available) {
            btn.innerHTML = `<span>✕</span> Not in Hindi`;
            statusSpan.className = "hs-badge-fail";
            statusSpan.textContent = "Hindi Dub Not Available";
            if (onNotAvailable) onNotAvailable(check);
            setTimeout(() => {
              btn.disabled = false;
              btn.innerHTML = `<span>⚡</span> Check Hindi Dubbed`;
            }, 3500);
            return;
          }

          // 2. Hindi is available! Now resolve live stream
          btn.innerHTML = `<span class="hs-spinner"></span> Resolving Live Stream...`;
          const stream = await HindiStream.resolveStream(tmdbId, season, episode);

          if (stream.success && (stream.m3u8_url || stream.embed_url)) {
            const isHls = stream.type === "hls" && stream.m3u8_url;
            const hostLabel = stream.active_host === "byse" ? "Byse" : "Vidara";
            btn.innerHTML = `<span>▶</span> Playing in Hindi`;
            btn.style.background = "#16a34a";
            statusSpan.className = "hs-badge-success";
            statusSpan.textContent = `✓ Hindi Available (${hostLabel})`;

            // Direct HLS player hook or Byse Iframe hook
            if (videoElement) {
              if (isHls) {
                // Restore video element if previously hidden by iframe
                const el = typeof videoElement === "string" ? document.querySelector(videoElement) : videoElement;
                if (el) {
                  el.style.display = "";
                  const existingIframe = el.parentElement ? el.parentElement.querySelector("iframe.hs-stream-iframe") : null;
                  if (existingIframe) existingIframe.remove();
                }
                await HindiStream.playInVideo(videoElement, stream.m3u8_url);
              } else if (stream.embed_url) {
                HindiStream.playInIframe(videoElement, stream.embed_url);
              }
            }

            if (onStreamReady) onStreamReady(stream);
          } else {
            btn.innerHTML = `<span>⏳</span> Encoding in Progress`;
            statusSpan.className = "hs-badge-fail";
            statusSpan.textContent = stream.message || "Encoding in progress on host";
            setTimeout(() => {
              btn.disabled = false;
              btn.innerHTML = `<span>⚡</span> Check Hindi Dubbed`;
            }, 4000);
          }
        } catch (err) {
          console.error("[HindiStream] Error:", err);
          btn.innerHTML = `<span>!</span> Error`;
          statusSpan.className = "hs-badge-fail";
          statusSpan.textContent = "API Connection Error";
          setTimeout(() => {
            btn.disabled = false;
            btn.innerHTML = `<span>⚡</span> Check Hindi Dubbed`;
          }, 3000);
        }
      };

      wrapper.appendChild(btn);
      wrapper.appendChild(statusSpan);
      targetEl.innerHTML = "";
      targetEl.appendChild(wrapper);

      return {
        update(newTmdbId, newSeason, newEpisode) {
          HindiStream.mountButton({
            ...options,
            tmdbId: newTmdbId,
            season: newSeason,
            episode: newEpisode
          });
        }
      };
    }
  };

  window.HindiStream = HindiStream;
})(window);
