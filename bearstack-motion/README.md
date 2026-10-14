# BearStack motion logo: Signal trace

A 5-second loop of the Signal B lockup. A stroke sweeps in and lands as the signal dot. The six forms build out from it, the lockup glides left as the wordmark arrives, it holds, and then everything folds back into the dot. All easing slows down smoothly with no overshoot, because the brand book says the logo never bounces. Every end frame is the exact approved SVG.

## Files (`export/`)

| File | Use |
| --- | --- |
| `bearstack-signal-trace-bone.json` | Lottie for dark (espresso) backgrounds: bone symbol and wordmark |
| `bearstack-signal-trace-primary.json` | Lottie for light (bone) backgrounds: orange symbol, espresso wordmark |
| `bearstack-signal-trace-espresso.json` | Lottie for orange or amber backgrounds |
| `bearstack-signal-trace-1920x1080.mp4` | 16:9 video, bone on espresso, 60 fps, H.264 |
| `bearstack-signal-trace-1080x1080.mp4` | Square video for social, bone on espresso |
| `bearstack-signal-trace-transparent-1440x360.webm` | VP9 with alpha, bone, for placing over dark video or imagery |

The Lottie files are 440 × 112. That is the 408.08 × 80 master lockup plus the 16px clear space on every side. Each one is a seamless 300-frame loop at 60 fps.

## Website embed

```html
<div id="bearstack-logo" role="img" aria-label="BearStack" style="width: 408px; aspect-ratio: 440 / 112"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/lottie-web/5.12.2/lottie.min.js"></script>
<script>
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const anim = lottie.loadAnimation({
    container: document.getElementById('bearstack-logo'),
    renderer: 'svg',
    path: '/assets/bearstack-signal-trace-bone.json',
    loop: !reduce,
    autoplay: !reduce,
  });
  // With reduced motion, show the finished lockup (frame 150 is mid-hold)
  if (reduce) anim.addEventListener('DOMLoaded', () => anim.goToAndStop(150, true));
</script>
```

To play the animation once as an intro and end on the full logo, set `loop: false` and stop at the hold with `anim.playSegments([0, 216], true)` (frame 216 is 72%, just before the exit begins).

## Rebuilding

- `src/signal-trace.html`: standalone CSS version of the animation. Query params `bg`, `sym`, `wm` (hex without `#`, or `bg=none`), `lw` (logo width in px) and `t` (loop seconds).
- `src/render.mjs`: renders that page frame by frame with Playwright, e.g. `node src/render.mjs frames/wide 1920 1080 60 "lw=1224"`, then `ffmpeg -framerate 60 -i frames/wide/f%04d.png -c:v libx264 -pix_fmt yuv420p -crf 16 out.mp4`.
- `src/make_lottie.py`: writes the three Lottie files from the logo's vector geometry using the same timeline: `python3 src/make_lottie.py export`.
