# BearStack motion logo: Signal trace

A 5-second loop of the Signal B lockup. A stroke sweeps in and lands as the signal dot. The six forms build out from it, the lockup glides left as the wordmark arrives, it holds, and then everything folds back into the dot. All easing slows down smoothly with no overshoot, because the brand book says the logo never bounces. Every end frame is the exact approved SVG.

## Files (`export/`)

Two cuts of the same motion:

- **loop**: 5 s, seamless, for repeating placements.
- **intro**: 3.4 s, plays once and ends on the full lockup (build-in plus a short hold). Use it for page loads, video openers and email.

Colours: **bone** for dark (espresso) grounds, **primary** (orange symbol, espresso wordmark) for light (bone) grounds, **espresso** for orange or amber planes.

| Folder | Files | Notes |
| --- | --- | --- |
| `lottie/` | `…-{loop,intro}-{bone,primary,espresso}.json` | Lottie JSON, 440 × 112 (master lockup plus 16px clear space), 60 fps, transparent |
| `dotlottie/` | `…-{loop,intro}-{bone,primary,espresso}.lottie` | Same animations as dotLottie, with loop/autoplay set in the manifest (Webflow, Framer, LottieFiles players) |
| `video/` | `…-{loop,intro}-1920x1080.mp4`, `…-1080x1080.mp4` | Bone on espresso, 60 fps, H.264 |
| `video/` | `…-{loop,intro}-transparent-1440x360.webm` | Bone with alpha (VP9), for placing over dark footage or imagery |
| `gif/` | `…-{loop,intro}-{bone,primary}-880x224.gif` | 25 fps. The loop GIF repeats; the intro GIF plays once and stops on the logo (email, docs, places without video) |

## Website embed

```html
<div id="bearstack-logo" role="img" aria-label="BearStack" style="width: 408px; aspect-ratio: 440 / 112"></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/lottie-web/5.12.2/lottie.min.js"></script>
<script>
  const reduce = matchMedia('(prefers-reduced-motion: reduce)').matches;
  const anim = lottie.loadAnimation({
    container: document.getElementById('bearstack-logo'),
    renderer: 'svg',
    path: '/assets/bearstack-signal-trace-loop-bone.json',
    loop: !reduce,
    autoplay: !reduce,
  });
  // With reduced motion, show the finished lockup (frame 150 is mid-hold)
  if (reduce) anim.addEventListener('DOMLoaded', () => anim.goToAndStop(150, true));
</script>
```

For a one-time intro, point `path` at `bearstack-signal-trace-intro-bone.json` and set `loop: false`; it stops on the full lockup. With reduced motion, use `anim.goToAndStop(203, true)` (its last frame).

dotLottie, with the official web component:

```html
<script src="https://unpkg.com/@lottiefiles/dotlottie-wc@0.6.2/dist/dotlottie-wc.js" type="module"></script>
<dotlottie-wc src="/assets/bearstack-signal-trace-intro-bone.lottie" autoplay style="width: 408px; aspect-ratio: 440 / 112"></dotlottie-wc>
```

## Rebuilding

- `src/signal-trace.html`: standalone CSS version of the animation. Query params `bg`, `sym`, `wm` (hex without `#`, or `bg=none`), `lw` (logo width in px) and `t` (loop seconds).
- `src/render.mjs`: renders that page frame by frame with Playwright, e.g. `node src/render.mjs frames/wide 1920 1080 60 "lw=1224"`, then `ffmpeg -framerate 60 -i frames/wide/f%04d.png -c:v libx264 -pix_fmt yuv420p -crf 16 out.mp4` (add `-frames:v 204` for the intro).
- `src/make_lottie.py`: writes every Lottie and dotLottie file from the logo's vector geometry using the same timeline: `python3 src/make_lottie.py export`.
