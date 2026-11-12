# Nicla Cleaner mobile UI prototype

Static, buildless prototype for an iPhone 18 Pro landscape viewport. It runs
with simulated detections until the laptop bridge is connected to Nicla
Vision.

The planning view demonstrates:

- a robot/roller origin and an approach path to the active target;
- automatic priority hand-off between multiple stool detections;
- a separate multi-lane, overlapping coverage pattern for a wide urine area;
- target-specific turn, travel, and roller actions in a compact side panel.

Urine remains explicitly marked as an untrained candidate. Its coverage route
is a UI/behavior concept, not a validated urine-model output.

The hosted version is intentionally a UI prototype: it cannot connect to the
board's raw TCP stream. The future local bridge will serve the same `dist/`
folder and expose browser-friendly video, state, and command endpoints.

## Local preview

```powershell
python -m http.server 4173 --directory dist
```

Then open `http://127.0.0.1:4173` and use a landscape viewport close to
874 x 402 CSS pixels.
