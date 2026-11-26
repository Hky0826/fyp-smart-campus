"""Native Python Kiosk Session & Companion Mobile Wayfinding Service.

Replaces mapping_and_notification/backend/services/kioskSessionService.js and
kioskController.js's renderMobileRoutePage.
"""

from __future__ import annotations

import base64
import datetime
import html
import io
import json
import logging
import os
import re
import secrets
from pathlib import Path
from typing import Any

import qrcode
from fastapi import Request
from sqlalchemy.orm import Session

from app.models.models import KioskSession
from app.services.mapping.route_visualizer import get_floorplan_storage_dir

logger = logging.getLogger("smart-campus.mapping.kiosk")

_TOKEN_RE = re.compile(r"^[a-f0-9]{48,64}$", re.IGNORECASE)


def get_qr_codes_dir() -> Path:
    d = get_floorplan_storage_dir() / "qr_codes"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_mobile_base_url(request: Request | None = None) -> str:
    env_url = os.getenv("MOBILE_BASE_URL", "").strip()
    if env_url:
        return env_url.rstrip("/")

    if request is not None:
        proto = request.headers.get("x-forwarded-proto") or request.url.scheme or "http"
        host = request.headers.get("x-forwarded-host") or request.headers.get("host")
        if host:
            return f"{proto}://{host}"

    port = os.getenv("PORT", "8000")
    return f"http://127.0.0.1:{port}"


def _generate_qr_assets(mobile_url: str, token: str) -> tuple[str, Path, str]:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
    )
    qr.add_data(mobile_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0f172a", back_color="#ffffff")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    png_bytes = buf.getvalue()
    data_url = "data:image/png;base64," + base64.b64encode(png_bytes).decode("ascii")

    qr_filename = f"qr_{token}.png"
    qr_path = get_qr_codes_dir() / qr_filename
    try:
        qr_path.write_bytes(png_bytes)
    except OSError as exc:
        logger.warning("Could not write QR PNG file: %s", exc)

    return data_url, qr_path, qr_filename


def create_kiosk_session(
    db: Session,
    *,
    nav_result: dict,
    map_context: dict,
    start_id: int | str,
    end_id: int | str,
    role_id: int | str,
    walking_speed: float = 1.2,
    request: Request | None = None,
) -> dict[str, Any]:
    token = secrets.token_hex(24)  # 48 hex chars
    ttl_minutes = int(os.getenv("KIOSK_SESSION_TTL_MINUTES", "15"))
    now = datetime.datetime.utcnow()
    expires_at = now + datetime.timedelta(minutes=ttl_minutes)

    base_url = get_mobile_base_url(request)
    mobile_url = f"{base_url}/mobile-route/{token}"

    qr_data_url, qr_path, qr_filename = _generate_qr_assets(mobile_url, token)

    def _safe_int(val: Any) -> int:
        try:
            return int(val)
        except (TypeError, ValueError):
            return 0

    record = KioskSession(
        session_token=token,
        current_location=_safe_int(start_id),
        destination_node=_safe_int(end_id),
        rbac_role=str(role_id or "visitor")[:32],
        walking_speed=float(walking_speed or 1.2),
        navigation_data=json.dumps(nav_result),
        map_context=json.dumps(map_context),
        created_at=now,
        expires_at=expires_at,
    )
    db.add(record)
    db.commit()

    port = os.getenv("PORT", "8000")
    return {
        "session_token": token,
        "mobile_url": mobile_url,
        "qr_code_data_url": qr_data_url,
        "qr_code_url": f"{base_url}/uploads/qr_codes/{qr_filename}",
        "qr_code_local_url": f"http://127.0.0.1:{port}/uploads/qr_codes/{qr_filename}",
        "qr_code_file_url": f"file:///{str(qr_path).replace(os.sep, '/')}",
        "expires_at": expires_at.isoformat() + "Z",
        "expires_in_minutes": ttl_minutes,
    }


def get_kiosk_session(db: Session, token: str) -> dict[str, Any] | None:
    if not token or not isinstance(token, str):
        return None
    clean = token.strip()
    if not _TOKEN_RE.match(clean):
        return None

    now = datetime.datetime.utcnow()
    row = (
        db.query(KioskSession)
        .filter(KioskSession.session_token == clean, KioskSession.expires_at > now)
        .first()
    )
    if not row:
        return None

    try:
        nav_data = json.loads(row.navigation_data) if isinstance(row.navigation_data, str) else row.navigation_data
    except Exception:
        nav_data = None
    try:
        map_data = json.loads(row.map_context) if isinstance(row.map_context, str) else row.map_context
    except Exception:
        map_data = None

    return {
        "session_token": row.session_token,
        "current_location": row.current_location,
        "destination_node": row.destination_node,
        "rbac_role": row.rbac_role,
        "walking_speed": row.walking_speed,
        "navigation": nav_data,
        "map_context": map_data,
        "created_at": row.created_at.isoformat() + "Z" if row.created_at else None,
        "expires_at": row.expires_at.isoformat() + "Z" if row.expires_at else None,
    }


def cleanup_expired_sessions(db: Session) -> int:
    now = datetime.datetime.utcnow()
    deleted = db.query(KioskSession).filter(KioskSession.expires_at < now).delete(synchronize_session=False)
    if deleted:
        db.commit()
    return int(deleted or 0)


def render_mobile_route_html(session: dict | None, token: str) -> tuple[int, str]:
    """Render the responsive companion mobile walking guide HTML page."""
    if not session:
        safe_tok = html.escape((token or "")[:12])
        return (
            404,
            f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Session Expired · Smart Campus Navigation</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-slate-100 text-slate-800 flex items-center justify-center min-h-screen p-4">
  <div class="bg-white p-6 rounded-2xl shadow-md border border-slate-200 max-w-sm w-full text-center">
    <div class="w-12 h-12 rounded-full bg-amber-100 text-amber-600 flex items-center justify-center mx-auto mb-3 text-xl font-bold">!</div>
    <h2 class="text-lg font-bold text-slate-900 mb-1">Session Expired</h2>
    <p class="text-xs text-slate-600 mb-4">This navigation QR code has expired. Please request directions again at the campus kiosk.</p>
    <div class="text-[11px] text-slate-400 font-mono bg-slate-50 p-2 rounded border border-slate-200">Session: {safe_tok}...</div>
  </div>
</body>
</html>""",
        )

    nav = session.get("navigation") or {}
    summary = nav.get("route_summary") or {}
    instructions = nav.get("instructions") or []
    map_context = session.get("map_context") or {}
    visualisations = nav.get("visualisations") or []

    floorplan_order: list[int] = []
    for node in nav.get("path") or []:
        fp_id = int(node.get("floorplan_id") or 0)
        if fp_id and fp_id not in floorplan_order and (str(fp_id) in map_context or fp_id in map_context):
            floorplan_order.append(fp_id)
    for k in map_context.keys():
        fp_id = int(k)
        if fp_id not in floorplan_order:
            floorplan_order.append(fp_id)

    active_fp_id = floorplan_order[0] if floorplan_order else None

    vis_by_floor: dict[str, str] = {}
    for v in visualisations:
        fn = v.get("filename")
        vis_by_floor[str(v.get("floorplan_id"))] = f"/uploads/visualisations/{fn}" if fn else (v.get("image_url") or "")

    dest_label = html.escape(str(summary.get("destination_label") or "Destination"))
    start_label = html.escape(str(summary.get("start_label") or "Current Location"))
    total_dist = html.escape(str(summary.get("total_distance_m") or 0))
    est_time = html.escape(str(summary.get("estimated_time_label") or "1 min"))

    floor_buttons_html = ""
    if len(floorplan_order) > 1:
        btns = []
        for idx, fp_id in enumerate(floorplan_order):
            fp = map_context.get(str(fp_id)) or map_context.get(fp_id) or {}
            bldg = html.escape(str(fp.get("building_name") or "Building"))
            lvl = html.escape(str(fp.get("floor_level") or "1"))
            suffix = " (Start)" if idx == 0 else (" (Dest)" if idx == len(floorplan_order) - 1 else "")
            active_cls = "bg-teal-600 text-white shadow-xs" if idx == 0 else "bg-slate-50 text-slate-600 hover:bg-slate-100"
            btns.append(
                f'<button onclick="switchFloor(\'{fp_id}\')" id="btn-fp-{fp_id}" '
                f'class="floor-btn flex-1 py-1.5 px-2.5 rounded-lg text-center text-xs font-semibold whitespace-nowrap transition-all {active_cls}">'
                f'{idx + 1}. {bldg} · L{lvl}{suffix}</button>'
            )
        floor_buttons_html = (
            '<div class="bg-white p-1.5 rounded-xl border border-slate-200 shadow-sm flex gap-1.5 overflow-x-auto">'
            + "".join(btns)
            + "</div>"
        )

    imgs_html = "".join(
        f'<img id="floor-img-{fp_id}" src="{html.escape(vis_by_floor.get(str(fp_id), ""))}" '
        f'alt="Floor Plan Level {fp_id}" '
        f'class="floor-img absolute max-w-[96%] max-h-[96%] object-contain select-none transition-opacity duration-150 '
        f'{"opacity-100 z-10" if fp_id == active_fp_id else "opacity-0 z-0 pointer-events-none"}" draggable="false" />'
        for fp_id in floorplan_order
    )

    step_rows = []
    for idx, step in enumerate(instructions):
        step_desc = html.escape(str(step.get("instruction") or step.get("description") or "Proceed"))
        dist_m = step.get("distance_m")
        dist_badge = f'<span class="text-[10px] text-slate-500 font-mono shrink-0">{dist_m}m</span>' if dist_m else ""
        bldg_name = step.get("building_name")
        flr_lvl = step.get("floor_level")
        loc_badge = (
            f'<div class="text-[10px] text-teal-700 font-medium mt-0.5">{html.escape(str(bldg_name))} Floor {html.escape(str(flr_lvl))}</div>'
            if bldg_name
            else ""
        )
        fp_arg = step.get("floorplan_id") or "null"
        step_rows.append(
            f'<div onclick="toggleStep({idx}, {fp_arg})" '
            f'class="step-item flex items-start gap-3 p-3 rounded-xl bg-slate-50 border border-slate-200 cursor-pointer hover:border-slate-300 transition-all">'
            f'<input type="checkbox" id="chk-{idx}" class="mt-0.5 rounded accent-teal-600 pointer-events-none">'
            f'<div class="flex-1 min-w-0">'
            f'<div class="flex items-center justify-between gap-1">'
            f'<span class="text-xs font-bold text-slate-900">{idx + 1}. {step_desc}</span>'
            f"{dist_badge}"
            f"</div>{loc_badge}</div></div>"
        )
    steps_html = "".join(step_rows)

    page_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=3.0, user-scalable=yes">
  <title>Walking Guide · {dest_label}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>.touch-none {{ touch-action: none; }}</style>
</head>
<body class="bg-slate-100 text-slate-800 font-sans antialiased p-3 min-h-screen pb-10">
  <div class="max-w-md mx-auto flex flex-col gap-3">
    <div class="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm">
      <div class="flex items-center justify-between mb-2">
        <span class="text-[10px] font-bold text-teal-700 bg-teal-50 border border-teal-200 px-2 py-0.5 rounded-full uppercase tracking-wider">Smart Campus Walking Guide</span>
        <span class="text-[10px] text-slate-500 font-mono">Active Session</span>
      </div>
      <h1 class="text-base font-bold text-slate-900 leading-tight">{dest_label}</h1>
      <p class="text-xs text-slate-500 mt-0.5">From: <span class="font-medium text-slate-700">{start_label}</span></p>
      <div class="grid grid-cols-3 gap-2 mt-3 pt-3 border-t border-slate-100 text-center">
        <div class="bg-slate-50 p-2 rounded-xl border border-slate-200/80"><div class="text-[9px] text-slate-500 uppercase font-semibold">Distance</div><div class="text-sm font-bold text-teal-700 mt-0.5">{total_dist}m</div></div>
        <div class="bg-slate-50 p-2 rounded-xl border border-slate-200/80"><div class="text-[9px] text-slate-500 uppercase font-semibold">Est. Time</div><div class="text-sm font-bold text-indigo-700 mt-0.5">{est_time}</div></div>
        <div class="bg-slate-50 p-2 rounded-xl border border-slate-200/80"><div class="text-[9px] text-slate-500 uppercase font-semibold">Steps</div><div class="text-sm font-bold text-slate-800 mt-0.5">{len(instructions)}</div></div>
      </div>
    </div>
    {floor_buttons_html}
    <div class="bg-white rounded-2xl border border-slate-200 overflow-hidden shadow-sm flex flex-col">
      <div class="px-3.5 py-2.5 border-b border-slate-200 flex items-center justify-between text-xs bg-slate-50">
        <span class="font-bold text-slate-800">Floor Plan Walking Route</span>
        <span id="current-floor-badge" class="text-[10px] font-bold text-teal-700 bg-teal-50 border border-teal-200 px-2 py-0.5 rounded-full">Loading...</span>
      </div>
      <div id="map-viewport" class="relative w-full h-[360px] bg-slate-50 overflow-hidden select-none flex items-center justify-center cursor-grab active:cursor-grabbing touch-none">
        <div id="map-canvas" class="relative w-full h-full flex items-center justify-center origin-center transition-transform duration-75" style="transform: translate(0px, 0px) scale(1);">{imgs_html}</div>
        <div class="absolute bottom-3 right-3 flex flex-col gap-1 bg-white/95 backdrop-blur-sm p-1 rounded-xl border border-slate-200 shadow-md z-20">
          <button onclick="zoom(1.25)" class="w-8 h-8 flex items-center justify-center rounded-lg bg-slate-50 hover:bg-slate-100 text-slate-700 font-bold text-base border border-slate-200">+</button>
          <button onclick="resetZoom()" class="w-8 h-8 flex items-center justify-center rounded-lg bg-slate-50 hover:bg-slate-100 text-teal-600 font-bold text-xs border border-slate-200">Fit</button>
          <button onclick="zoom(0.8)" class="w-8 h-8 flex items-center justify-center rounded-lg bg-slate-50 hover:bg-slate-100 text-slate-700 font-bold text-base border border-slate-200">−</button>
        </div>
      </div>
    </div>
    <div class="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm flex flex-col gap-2.5">
      <div class="flex items-center justify-between">
        <h2 class="text-xs font-bold text-slate-900 uppercase tracking-wider">Step-by-Step Directions</h2>
        <span id="step-progress" class="text-[9px] text-teal-700 font-semibold bg-teal-50 px-2 py-0.5 rounded border border-teal-100">0 of {len(instructions)} Done</span>
      </div>
      <div class="flex flex-col gap-2 mt-1">{steps_html}</div>
    </div>
    <div class="text-center text-[10px] text-slate-400 py-3">Smart Campus Navigation · Companion Mobile View</div>
  </div>
  <script>
    const totalSteps = {len(instructions)};
    const mapContext = {json.dumps(map_context)};
    const navResult = {json.dumps(nav)};
    let activeFloorId = {json.dumps(str(active_fp_id) if active_fp_id else None)};
    let scale = 1.0, panX = 0, panY = 0, isDragging = false, startX = 0, startY = 0, initDist = 0, initScale = 1.0;
    const canvas = document.getElementById('map-canvas');
    const viewport = document.getElementById('map-viewport');
    function updateTransform() {{ if (canvas) canvas.style.transform = 'translate(' + panX + 'px, ' + panY + 'px) scale(' + scale + ')'; }}
    function zoom(f) {{ scale = Math.min(Math.max(0.85, scale * f), 5.0); if (scale <= 1.0) {{ panX = 0; panY = 0; }} updateTransform(); }}
    function resetZoom() {{ scale = 1.0; panX = 0; panY = 0; updateTransform(); }}
    function updateBadge() {{
      const badge = document.getElementById('current-floor-badge');
      if (!badge || !activeFloorId) return;
      const fp = mapContext[activeFloorId] || mapContext[Number(activeFloorId)];
      if (!fp) return;
      badge.innerText = (fp.building_name || 'Building') + ' · Level ' + fp.floor_level;
    }}
    function switchFloor(fpId) {{
      activeFloorId = String(fpId);
      document.querySelectorAll('.floor-btn').forEach(b => {{ b.classList.remove('bg-teal-600','text-white'); b.classList.add('bg-slate-50','text-slate-600'); }});
      const a = document.getElementById('btn-fp-' + fpId);
      if (a) {{ a.classList.add('bg-teal-600','text-white'); a.classList.remove('bg-slate-50','text-slate-600'); }}
      document.querySelectorAll('.floor-img').forEach(i => {{ i.classList.remove('opacity-100','z-10'); i.classList.add('opacity-0','z-0','pointer-events-none'); }});
      const t = document.getElementById('floor-img-' + fpId);
      if (t) {{ t.classList.remove('opacity-0','z-0','pointer-events-none'); t.classList.add('opacity-100','z-10'); }}
      resetZoom(); updateBadge();
    }}
    if (viewport) {{
      viewport.addEventListener('mousedown', e => {{ e.preventDefault(); isDragging = true; startX = e.clientX - panX; startY = e.clientY - panY; }});
      window.addEventListener('mousemove', e => {{ if (!isDragging) return; panX = e.clientX - startX; panY = e.clientY - startY; updateTransform(); }});
      window.addEventListener('mouseup', () => {{ isDragging = false; }});
      viewport.addEventListener('wheel', e => {{ e.preventDefault(); zoom(e.deltaY > 0 ? 0.9 : 1.1); }}, {{ passive: false }});
      viewport.addEventListener('touchstart', e => {{
        if (e.touches.length === 1) {{ isDragging = true; startX = e.touches[0].clientX - panX; startY = e.touches[0].clientY - panY; }}
        else if (e.touches.length === 2) {{ isDragging = false; initDist = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY); initScale = scale; }}
      }}, {{ passive: true }});
      viewport.addEventListener('touchmove', e => {{
        if (isDragging && e.touches.length === 1) {{ panX = e.touches[0].clientX - startX; panY = e.touches[0].clientY - startY; updateTransform(); }}
        else if (e.touches.length === 2 && initDist > 0) {{ const d = Math.hypot(e.touches[0].clientX - e.touches[1].clientX, e.touches[0].clientY - e.touches[1].clientY); scale = Math.min(Math.max(0.85, initScale * (d / initDist)), 5.0); updateTransform(); }}
      }}, {{ passive: true }});
      viewport.addEventListener('touchend', () => {{ isDragging = false; }});
    }}
    function toggleStep(idx, fpId) {{
      const c = document.getElementById('chk-' + idx);
      if (c) {{ c.checked = !c.checked; let done = 0; for (let i = 0; i < totalSteps; i++) {{ const el = document.getElementById('chk-' + i); if (el && el.checked) done++; }} const p = document.getElementById('step-progress'); if (p) p.innerText = done + ' of ' + totalSteps + ' Done'; }}
      if (fpId && String(fpId) !== String(activeFloorId)) switchFloor(fpId);
    }}
    updateBadge();
  </script>
</body>
</html>"""
    return 200, page_html
