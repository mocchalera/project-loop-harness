# Recording guide

## Recommended terminal setup

- 1280×720 or larger capture area
- dark terminal, 18–20 px monospace font
- hide notifications and unrelated tabs
- start in `examples/v0.5.0-adoption-demo`

Run the paced version and keep the final dashboard:

```bash
./run-demo.sh --paced --keep
```

Narrate from the table in [README.md](README.md). At the end, open the printed
`DASHBOARD=...` path and point out the closed Goal, Evidence, completion packet,
and lack of pending work. Do not use the HTML as agent context; it is the
human-review surface.

## Reproducible terminal transcript

macOS includes `script`, so a dependency-free transcript can be captured with:

```bash
script -q /tmp/pcl-v0.5.0-demo.typescript ./run-demo.sh --paced --keep
```

Replay or inspect the transcript locally:

```bash
less -R /tmp/pcl-v0.5.0-demo.typescript
```

If `asciinema` is already installed, record a portable terminal session:

```bash
asciinema rec /tmp/pcl-v0.5.0-demo.cast \
  --command './run-demo.sh --paced --keep' \
  --title 'Project Loop Harness v0.5.0 adoption demo'
```

No recorder is installed by the demo. Use the operating system's screen
recorder (Shift-Command-5 on macOS) to include the final browser handoff.

## Visual artifact status

The checked-in `docs/assets/v0.5.0-demo/dashboard-ja.png` is an actual browser
capture from a successful clean-PyPI run. GIF/WebM is intentionally not
checked in: the terminal transcript and the commands above are the reproducible
recording source without adding a media dependency.
