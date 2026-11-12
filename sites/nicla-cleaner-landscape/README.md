# Nicla Cleaner mobile UI prototype

Static, buildless prototype for an iPhone 18 Pro landscape viewport. It runs
with simulated detections until the laptop bridge is connected to Nicla
Vision.

The hosted version is intentionally a UI prototype: it cannot connect to the
board's raw TCP stream. The future local bridge will serve the same `dist/`
folder and expose browser-friendly video, state, and command endpoints.

## Local preview

```powershell
python -m http.server 4173 --directory dist
```

Then open `http://127.0.0.1:4173` and use a landscape viewport close to
874 x 402 CSS pixels.
