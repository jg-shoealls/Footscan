"""3D pressure distribution visualization for FootScan measurements.

The main FootScan application stores captured frames in measurements.db as
``measurement_frames.frame_data`` blobs. This module converts those frames into
pressure grids and writes a standalone HTML viewer with a rotatable 3D surface,
contour levels, and playback controls for dynamic gait measurements.
"""

from __future__ import annotations

import base64
import io
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np


DEFAULT_SENSOR_SHAPES = (
    (48, 48),
    (64, 64),
    (32, 64),
    (64, 32),
    (40, 60),
    (60, 40),
    (32, 32),
    (24, 48),
    (48, 24),
    (16, 32),
    (32, 16),
)


@dataclass(frozen=True)
class FrameDecodeOptions:
    rows: int | None = None
    cols: int | None = None
    dtype: str = "auto"
    max_frames: int = 240
    smooth: bool = True
    normalize: bool = False


def decode_frame_blob(blob: bytes | str | Sequence[float], options: FrameDecodeOptions) -> np.ndarray:
    """Decode one stored frame into a 2D pressure array.

    The production app has had more than one storage format during packaging,
    so the decoder accepts JSON arrays, NumPy ``.npy`` payloads, and common raw
    numeric blobs. ``rows``/``cols`` can be supplied when the sensor dimensions
    are known.
    """
    if isinstance(blob, str):
        return _decode_text_payload(blob, options)
    if isinstance(blob, (list, tuple)):
        return _reshape_numeric_array(np.asarray(blob, dtype=np.float32), options)
    if not blob:
        raise ValueError("empty frame blob")

    data = bytes(blob)
    if data[:6] == b"\x93NUMPY":
        with io.BytesIO(data) as buf:
            return _ensure_2d(np.load(buf, allow_pickle=False).astype(np.float32), options)

    text = _try_decode_text(data)
    if text is not None:
        try:
            return _decode_text_payload(text, options)
        except ValueError:
            pass

    return _decode_raw_numeric(data, options)


def build_pressure_frames(
    blobs: Iterable[bytes],
    options: FrameDecodeOptions | None = None,
) -> list[list[list[float]]]:
    options = options or FrameDecodeOptions()
    frames: list[np.ndarray] = []
    for blob in blobs:
        frame = decode_frame_blob(blob, options)
        if options.smooth:
            frame = _smooth_frame(frame)
        if options.normalize and frame.max(initial=0) > 0:
            frame = frame / frame.max()
        frames.append(frame.astype(np.float32))

    if not frames:
        raise ValueError("measurement has no frame data")

    if options.max_frames and len(frames) > options.max_frames:
        indexes = np.linspace(0, len(frames) - 1, options.max_frames).round().astype(int)
        frames = [frames[int(i)] for i in indexes]

    target_shape = _most_common_shape(frames)
    aligned = [_resize_nearest(frame, target_shape) for frame in frames]
    return [frame.round(4).tolist() for frame in aligned]


def write_pressure_3d_html(
    frames: Sequence[Sequence[Sequence[float]]],
    out_path: Path,
    *,
    title: str = "FootScan 3D Pressure Distribution",
    measurement: dict | None = None,
    measurement_type: str = "dynamic",
) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "title": title,
        "measurementType": measurement_type,
        "measurement": measurement or {},
        "frames": frames,
    }
    encoded = base64.b64encode(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")
    out_path.write_text(_html_template(encoded), encoding="utf-8")
    return out_path


def _decode_text_payload(text: str, options: FrameDecodeOptions) -> np.ndarray:
    text = text.strip()
    if not text:
        raise ValueError("empty text frame")
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("not a JSON frame") from exc

    if isinstance(payload, dict):
        for key in ("frame", "data", "pressure", "values", "matrix"):
            if key in payload:
                payload = payload[key]
                break
    return _ensure_2d(np.asarray(payload, dtype=np.float32), options)


def _try_decode_text(data: bytes) -> str | None:
    for encoding in ("utf-8", "cp949"):
        try:
            text = data.decode(encoding)
        except UnicodeDecodeError:
            continue
        if text.lstrip().startswith(("[", "{")):
            return text
    return None


def _decode_raw_numeric(data: bytes, options: FrameDecodeOptions) -> np.ndarray:
    dtypes: list[str]
    if options.dtype == "auto":
        dtypes = ["<f4", "<u2", "<i2", "<u1", "<f8"]
    else:
        dtypes = [options.dtype]

    errors: list[str] = []
    for dtype in dtypes:
        try:
            item_size = np.dtype(dtype).itemsize
            if len(data) % item_size != 0:
                errors.append(f"{dtype}: byte length mismatch")
                continue
            values = np.frombuffer(data, dtype=dtype).astype(np.float32)
            if values.size == 0:
                continue
            return _reshape_numeric_array(values, options)
        except (TypeError, ValueError) as exc:
            errors.append(f"{dtype}: {exc}")
    raise ValueError("unsupported frame blob format; " + "; ".join(errors))


def _reshape_numeric_array(values: np.ndarray, options: FrameDecodeOptions) -> np.ndarray:
    if options.rows and options.cols:
        expected = options.rows * options.cols
        if values.size != expected:
            raise ValueError(f"expected {expected} values, got {values.size}")
        return values.reshape((options.rows, options.cols))

    for rows, cols in DEFAULT_SENSOR_SHAPES:
        if rows * cols == values.size:
            return values.reshape((rows, cols))

    side = int(math.sqrt(values.size))
    if side * side == values.size:
        return values.reshape((side, side))

    factors = [(r, values.size // r) for r in range(2, int(math.sqrt(values.size)) + 1) if values.size % r == 0]
    if factors:
        rows, cols = min(factors, key=lambda pair: abs(pair[0] - pair[1]))
        return values.reshape((rows, cols))

    raise ValueError(f"cannot infer sensor grid shape from {values.size} values")


def _ensure_2d(array: np.ndarray, options: FrameDecodeOptions) -> np.ndarray:
    array = np.asarray(array, dtype=np.float32)
    if array.ndim == 2:
        return array
    if array.ndim == 1:
        return _reshape_numeric_array(array, options)
    if array.ndim == 3:
        return array.max(axis=0)
    raise ValueError(f"expected 1D/2D/3D frame data, got {array.ndim}D")


def _smooth_frame(frame: np.ndarray) -> np.ndarray:
    padded = np.pad(frame, 1, mode="edge")
    total = np.zeros_like(frame, dtype=np.float32)
    for y in range(3):
        for x in range(3):
            total += padded[y : y + frame.shape[0], x : x + frame.shape[1]]
    return total / 9.0


def _most_common_shape(frames: Sequence[np.ndarray]) -> tuple[int, int]:
    counts: dict[tuple[int, int], int] = {}
    for frame in frames:
        counts[frame.shape] = counts.get(frame.shape, 0) + 1
    return max(counts.items(), key=lambda item: item[1])[0]


def _resize_nearest(frame: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    if frame.shape == shape:
        return frame
    y_idx = np.linspace(0, frame.shape[0] - 1, shape[0]).round().astype(int)
    x_idx = np.linspace(0, frame.shape[1] - 1, shape[1]).round().astype(int)
    return frame[np.ix_(y_idx, x_idx)]


def _html_template(encoded_payload: str) -> str:
    return f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>FootScan 3D Pressure</title>
  <style>
    :root {{
      color-scheme: light;
      font-family: Arial, "Malgun Gothic", sans-serif;
      background: #eef2f7;
      color: #142033;
    }}
    body {{ margin: 0; min-height: 100vh; display: grid; grid-template-rows: auto 1fr auto; }}
    header {{ padding: 18px 22px; background: #ffffff; border-bottom: 1px solid #d8e0eb; }}
    h1 {{ margin: 0; font-size: 22px; letter-spacing: 0; }}
    .meta {{ margin-top: 8px; color: #526173; font-size: 14px; }}
    main {{ display: grid; grid-template-columns: 1fr 310px; min-height: 0; }}
    #view {{ width: 100%; height: calc(100vh - 156px); display: block; background: #f8fafc; }}
    aside {{ border-left: 1px solid #d8e0eb; background: #fff; padding: 18px; overflow: auto; }}
    label {{ display: block; margin: 14px 0 6px; font-weight: 700; font-size: 13px; color: #334155; }}
    input[type="range"] {{ width: 100%; }}
    button {{ border: 0; border-radius: 6px; padding: 10px 12px; background: #155eef; color: white; font-weight: 700; cursor: pointer; }}
    .row {{ display: flex; gap: 8px; align-items: center; }}
    .row button {{ flex: 1; }}
    .value {{ min-width: 52px; text-align: right; font-variant-numeric: tabular-nums; color: #475569; }}
    .stats {{ width: 100%; border-collapse: collapse; margin-top: 16px; font-size: 13px; }}
    .stats th, .stats td {{ border-bottom: 1px solid #e5ebf3; padding: 9px 0; text-align: left; }}
    .stats th {{ color: #64748b; font-weight: 700; }}
    footer {{ padding: 10px 18px; background: #142033; color: #dce6f2; font-size: 12px; }}
    @media (max-width: 820px) {{
      main {{ grid-template-columns: 1fr; }}
      aside {{ border-left: 0; border-top: 1px solid #d8e0eb; }}
      #view {{ height: 62vh; }}
    }}
  </style>
</head>
<body>
<header>
  <h1 id="title">FootScan 3D Pressure</h1>
  <div class="meta" id="meta"></div>
</header>
<main>
  <canvas id="view"></canvas>
  <aside>
    <div class="row">
      <button id="play">재생</button>
      <button id="reset">보기 초기화</button>
    </div>
    <label for="frame">프레임</label>
    <div class="row"><input id="frame" type="range" min="0" max="0" value="0"><span class="value" id="frameText">0</span></div>
    <label for="height">높이 강조</label>
    <div class="row"><input id="height" type="range" min="20" max="180" value="85"><span class="value" id="heightText">85%</span></div>
    <label for="contour">등고선 간격</label>
    <div class="row"><input id="contour" type="range" min="4" max="16" value="9"><span class="value" id="contourText">9</span></div>
    <table class="stats">
      <tr><th>측정 타입</th><td id="type"></td></tr>
      <tr><th>그리드</th><td id="grid"></td></tr>
      <tr><th>최대 압력</th><td id="max"></td></tr>
      <tr><th>평균 압력</th><td id="avg"></td></tr>
      <tr><th>프레임 수</th><td id="count"></td></tr>
    </table>
  </aside>
</main>
<footer>마우스 드래그로 회전, 휠로 확대/축소할 수 있습니다. 정적 측정은 단일 표면으로, 동적보행 측정은 프레임 재생으로 확인합니다.</footer>
<script>
const payload = JSON.parse(new TextDecoder().decode(Uint8Array.from(atob("{encoded_payload}"), c => c.charCodeAt(0))));
const frames = payload.frames;
const canvas = document.getElementById("view");
const ctx = canvas.getContext("2d");
const ui = {{
  title: document.getElementById("title"),
  meta: document.getElementById("meta"),
  play: document.getElementById("play"),
  reset: document.getElementById("reset"),
  frame: document.getElementById("frame"),
  frameText: document.getElementById("frameText"),
  height: document.getElementById("height"),
  heightText: document.getElementById("heightText"),
  contour: document.getElementById("contour"),
  contourText: document.getElementById("contourText"),
  type: document.getElementById("type"),
  grid: document.getElementById("grid"),
  max: document.getElementById("max"),
  avg: document.getElementById("avg"),
  count: document.getElementById("count")
}};
let frameIndex = 0, playing = false, angleX = -0.86, angleZ = 0.72, zoom = 1.0;
let dragging = false, lastX = 0, lastY = 0;

ui.title.textContent = payload.title;
ui.meta.textContent = Object.entries(payload.measurement || {{}})
  .filter(([_, v]) => v !== null && v !== "")
  .map(([k, v]) => `${{k}}: ${{v}}`).join(" · ");
ui.frame.max = Math.max(0, frames.length - 1);
ui.type.textContent = payload.measurementType === "static" ? "정적 측정" : "동적보행 측정";
ui.count.textContent = frames.length.toString();

function resize() {{
  const box = canvas.getBoundingClientRect();
  canvas.width = Math.max(320, Math.floor(box.width * devicePixelRatio));
  canvas.height = Math.max(280, Math.floor(box.height * devicePixelRatio));
  draw();
}}

function colorFor(t) {{
  t = Math.max(0, Math.min(1, t));
  const stops = [
    [30, 83, 164], [28, 145, 178], [34, 197, 94], [250, 204, 21], [249, 115, 22], [220, 38, 38]
  ];
  const p = t * (stops.length - 1);
  const i = Math.min(stops.length - 2, Math.floor(p));
  const f = p - i;
  const a = stops[i], b = stops[i + 1];
  return `rgb(${{Math.round(a[0] + (b[0] - a[0]) * f)}},${{Math.round(a[1] + (b[1] - a[1]) * f)}},${{Math.round(a[2] + (b[2] - a[2]) * f)}})`;
}}

function project(x, y, z, rows, cols, maxValue) {{
  const nx = (x / Math.max(1, cols - 1) - 0.5) * 2.2;
  const ny = (y / Math.max(1, rows - 1) - 0.5) * 2.2;
  const nz = (z / Math.max(1, maxValue)) * (Number(ui.height.value) / 100);
  const cz = Math.cos(angleZ), sz = Math.sin(angleZ);
  const cx = Math.cos(angleX), sx = Math.sin(angleX);
  const rx = nx * cz - ny * sz;
  const ry = nx * sz + ny * cz;
  const rz = nz;
  const py = ry * cx - rz * sx;
  const pz = ry * sx + rz * cx;
  const scale = Math.min(canvas.width, canvas.height) * 0.31 * zoom;
  return {{
    x: canvas.width * 0.5 + rx * scale,
    y: canvas.height * 0.58 + py * scale,
    z: pz
  }};
}}

function draw() {{
  const frame = frames[frameIndex] || frames[0];
  if (!frame) return;
  const rows = frame.length, cols = frame[0].length;
  const flat = frame.flat();
  const maxValue = Math.max(...flat, 1);
  const avg = flat.reduce((a, b) => a + b, 0) / flat.length;
  ui.frameText.textContent = `${{frameIndex + 1}}/${{frames.length}}`;
  ui.heightText.textContent = `${{ui.height.value}}%`;
  ui.contourText.textContent = ui.contour.value;
  ui.grid.textContent = `${{rows}} x ${{cols}}`;
  ui.max.textContent = maxValue.toFixed(2);
  ui.avg.textContent = avg.toFixed(2);

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  ctx.fillStyle = "#f8fafc";
  ctx.fillRect(0, 0, canvas.width, canvas.height);

  const cells = [];
  for (let y = 0; y < rows - 1; y++) {{
    for (let x = 0; x < cols - 1; x++) {{
      const vals = [frame[y][x], frame[y][x+1], frame[y+1][x+1], frame[y+1][x]];
      const pts = [
        project(x, y, vals[0], rows, cols, maxValue),
        project(x+1, y, vals[1], rows, cols, maxValue),
        project(x+1, y+1, vals[2], rows, cols, maxValue),
        project(x, y+1, vals[3], rows, cols, maxValue)
      ];
      cells.push({{ pts, value: vals.reduce((a,b)=>a+b,0)/4, depth: pts.reduce((a,p)=>a+p.z,0)/4 }});
    }}
  }}
  cells.sort((a, b) => a.depth - b.depth);
  for (const cell of cells) {{
    ctx.beginPath();
    ctx.moveTo(cell.pts[0].x, cell.pts[0].y);
    for (let i = 1; i < 4; i++) ctx.lineTo(cell.pts[i].x, cell.pts[i].y);
    ctx.closePath();
    ctx.fillStyle = colorFor(cell.value / maxValue);
    ctx.fill();
    ctx.strokeStyle = "rgba(15,23,42,.12)";
    ctx.lineWidth = 0.6 * devicePixelRatio;
    ctx.stroke();
  }}

  const contourCount = Number(ui.contour.value);
  ctx.lineWidth = 1.1 * devicePixelRatio;
  for (let level = 1; level <= contourCount; level++) {{
    const target = (maxValue * level) / (contourCount + 1);
    ctx.strokeStyle = level % 2 ? "rgba(15,23,42,.34)" : "rgba(255,255,255,.62)";
    ctx.beginPath();
    for (let y = 0; y < rows; y++) {{
      let open = false;
      for (let x = 0; x < cols; x++) {{
        const v = frame[y][x];
        if (Math.abs(v - target) < maxValue / contourCount * 0.42) {{
          const p = project(x, y, v, rows, cols, maxValue);
          if (!open) {{ ctx.moveTo(p.x, p.y); open = true; }} else ctx.lineTo(p.x, p.y);
        }} else {{
          open = false;
        }}
      }}
    }}
    ctx.stroke();
  }}
}}

function tick() {{
  if (playing) {{
    frameIndex = (frameIndex + 1) % frames.length;
    ui.frame.value = frameIndex;
    draw();
  }}
  requestAnimationFrame(tick);
}}

ui.play.onclick = () => {{ playing = !playing; ui.play.textContent = playing ? "정지" : "재생"; }};
ui.reset.onclick = () => {{ angleX = -0.86; angleZ = 0.72; zoom = 1.0; draw(); }};
ui.frame.oninput = () => {{ frameIndex = Number(ui.frame.value); draw(); }};
ui.height.oninput = draw;
ui.contour.oninput = draw;
canvas.addEventListener("pointerdown", e => {{ dragging = true; lastX = e.clientX; lastY = e.clientY; canvas.setPointerCapture(e.pointerId); }});
canvas.addEventListener("pointerup", () => dragging = false);
canvas.addEventListener("pointermove", e => {{
  if (!dragging) return;
  angleZ += (e.clientX - lastX) * 0.008;
  angleX += (e.clientY - lastY) * 0.008;
  lastX = e.clientX; lastY = e.clientY;
  draw();
}});
canvas.addEventListener("wheel", e => {{
  e.preventDefault();
  zoom = Math.max(0.45, Math.min(2.8, zoom * (e.deltaY > 0 ? 0.92 : 1.08)));
  draw();
}}, {{ passive: false }});
window.addEventListener("resize", resize);
resize();
tick();
</script>
</body>
</html>"""
