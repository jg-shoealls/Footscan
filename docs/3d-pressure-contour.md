# 3D Pressure Contour Visualization

`footscan_qr_watcher.py visualize3d` reads `measurements.db` frame data and creates a standalone HTML viewer for 3D pressure distribution contours.

The viewer supports:

- Static measurement results as a single averaged 3D pressure surface.
- Dynamic gait measurement results as frame playback with a timeline slider.
- Mouse rotation, wheel zoom, pressure height scaling, and contour interval control.

## Usage

```powershell
python footscan_qr_watcher.py list
python footscan_qr_watcher.py visualize3d --id 3 --type auto
```

The HTML file is written to `%USERPROFILE%\Documents\FootScan_QR\3d\` by default.

## Static Measurement

```powershell
python footscan_qr_watcher.py visualize3d --id 3 --type static
```

When multiple frames are present, static mode averages them into one pressure surface.

## Dynamic Gait Measurement

```powershell
python footscan_qr_watcher.py visualize3d --id 3 --type dynamic
```

Dynamic mode embeds the measurement frames and enables playback in the generated HTML.

## Sensor Format Overrides

If the stored frame blob cannot be decoded automatically, specify the sensor grid and numeric dtype.

```powershell
python footscan_qr_watcher.py visualize3d --id 3 --type dynamic --rows 32 --cols 48 --dtype "<f4"
python footscan_qr_watcher.py visualize3d --id 3 --type dynamic --rows 64 --cols 64 --dtype "<u2"
```

Useful options:

- `--rows`, `--cols`: fixed sensor matrix dimensions.
- `--dtype`: raw frame value type such as `auto`, `<u2`, `<i2`, `<u1`, `<f4`, or `<f8`.
- `--max-frames`: cap dynamic frames embedded in HTML.
- `--no-smooth`: disable 3x3 smoothing.
- `--normalize`: normalize each frame to `0..1`.
- `--output`: choose the generated HTML path.
