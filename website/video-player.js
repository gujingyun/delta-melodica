(() => {
  'use strict';

  const video = document.getElementById('demo-video');
  const start = document.getElementById('video-start');
  const status = document.getElementById('video-status');
  if (!video || !start || !status) return;

  let hls;
  let initialized = false;
  let loading = false;
  start.hidden = false;

  const showError = () => {
    loading = false;
    initialized = false;
    if (hls) {
      hls.destroy();
      hls = null;
    }
    start.disabled = false;
    start.hidden = false;
    status.textContent = '流媒体暂时无法加载，请点击重试，或使用上方 MP4 兼容播放。';
  };

  // 仅在用户点击时加载本站固定版本的播放器，不依赖访客访问第三方 CDN。
  const loadPlayer = () => new Promise((resolve, reject) => {
    if (window.Hls) return resolve();
    const script = document.createElement('script');
    script.src = 'vendor/hls.light-1.7.2.min.js';
    script.onload = resolve;
    script.onerror = () => {
      script.remove();
      reject(new Error('播放器加载失败'));
    };
    document.head.appendChild(script);
  });

  start.addEventListener('click', async () => {
    if (loading || initialized) return;
    loading = true;
    start.disabled = true;
    status.textContent = '正在连接流媒体，视频将按片段加载…';
    try {
      if (video.canPlayType('application/vnd.apple.mpegurl')) {
        // Safari 等原生支持 HLS 的浏览器直接使用分片清单。
        video.src = video.dataset.stream;
      } else {
        await loadPlayer();
        if (!window.Hls || !window.Hls.isSupported()) {
          showError();
          return;
        }
        hls = new window.Hls({ maxBufferLength: 16, maxMaxBufferLength: 24, backBufferLength: 8 });
        hls.on(window.Hls.Events.ERROR, (_, data) => {
          if (data.fatal) showError();
        });
        hls.loadSource(video.dataset.stream);
        hls.attachMedia(video);
      }
      initialized = true;
      loading = false;
      start.hidden = true;
      video.focus({ preventScroll: true });
      try {
        await video.play();
      } catch (error) {
        if (error.name === 'NotAllowedError') {
          status.textContent = '流媒体已就绪，请点击播放器的播放按钮。';
        } else if (error.name !== 'AbortError') {
          showError();
        }
      }
    } catch (_) {
      showError();
    }
  });

  video.addEventListener('playing', () => {
    status.textContent = '正在播放 · HLS 分片流媒体，可拖动进度或切换全屏。';
  });
  video.addEventListener('waiting', () => {
    if (initialized) status.textContent = '正在缓冲接下来的视频片段…';
  });
  video.addEventListener('ended', () => {
    status.textContent = '视频播放完成，可通过播放器重新观看。';
  });
  video.addEventListener('pause', () => {
    if (initialized && !video.ended) status.textContent = '已暂停 · 点击播放按钮继续观看。';
  });
  video.addEventListener('error', () => {
    if (initialized) showError();
  });
})();
