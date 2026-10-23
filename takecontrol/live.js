// Take Control's live view of the screen, shared by the window's panel (takecontrol.js) and the overlay's card
// (control.js). It is the operating system's own screen capture (hardware-accelerated, with the real pointer in it),
// asked for through main.js's display-media handler: it never waits on the engine or the AI, so it keeps moving
// however long a decision takes. The overlay is left out of every capture (content protection), so it never films
// itself.
(function () {
  const FPS = 15;
  const MAX_WIDTH = 1280;   // the view is small: capturing more only costs the GPU

  // Starts (once) the live picture in `video`; false when the screen can't be captured here (then the engine's own
  // still pictures are shown instead).
  async function start(video) {
    if (video.srcObject) return true;
    if (!navigator.mediaDevices?.getDisplayMedia) return false;
    try {
      const stream = await navigator.mediaDevices.getDisplayMedia({
        video: { frameRate: { ideal: FPS, max: FPS }, width: { max: MAX_WIDTH } }, audio: false,
      });
      video.muted = true;
      video.srcObject = stream;
      await video.play().catch(() => {});
      return true;
    } catch (error) {
      console.warn('Take Control: no live view of the screen:', error?.message || error);
      return false;
    }
  }

  function stop(video) {
    video.srcObject?.getTracks().forEach((track) => track.stop());
    video.srcObject = null;
  }

  // The box around what Jarvis is acting on, over the live picture. `target` is the engine's
  // {rect: [x, y, w, h], screen: [w, h]} in screen pixels; the picture is drawn letterboxed (object-fit: contain).
  function placeTarget(box, video, target) {
    const rect = target?.rect;
    const screenSize = target?.screen;
    const vw = video.videoWidth;
    const vh = video.videoHeight;
    if (!rect || !screenSize?.[0] || !vw || !vh) { box.hidden = true; return; }
    const scale = Math.min(video.clientWidth / vw, video.clientHeight / vh);
    const left = video.offsetLeft + (video.clientWidth - vw * scale) / 2;
    const top = video.offsetTop + (video.clientHeight - vh * scale) / 2;
    const k = (vw * scale) / screenSize[0];
    box.style.left = `${left + rect[0] * k - 3}px`;
    box.style.top = `${top + rect[1] * k - 3}px`;
    box.style.width = `${Math.max(6, rect[2] * k) + 6}px`;
    box.style.height = `${Math.max(6, rect[3] * k) + 6}px`;
    box.hidden = false;
  }

  window.LiveScreen = { start, stop, placeTarget };
})();
