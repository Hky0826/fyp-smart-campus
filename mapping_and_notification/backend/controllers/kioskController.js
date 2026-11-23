/**
 * @file kioskController.js
 * @description Kiosk Navigation Controller for the Campus Navigation System.
 *
 * Provides endpoints for:
 *   1. Combined navigation + filtered map context endpoint (navigateForKiosk).
 *      Consumes the shared visualisationModelService to ensure strict RBAC
 *      and route-relevance filtering.
 *   2. Role-filtered global nodes endpoint (getKioskGlobalNodes) which requires
 *      a role and never leaks inaccessible nodes.
 *   3. Public endpoint to retrieve an active mobile navigation session by token.
 */

const queryAsync = require('../utils/queryAsync');
const { runNavigation } = require('./engineController');
const { buildVisualisationModel, resolveRoleId, isRolePermitted } = require('../services/visualisationModelService');
const kioskSessionService = require('../services/kioskSessionService');
const routeVisualizer = require('../utils/routeVisualizer');

exports.navigateForKiosk = async (req, res) => {
    const current_location = req.body.current_location || req.body.start_node_id;
    const destination_node = req.body.destination_node || req.body.destination_node_id;
    const rbac_role = req.body.rbac_role || (Array.isArray(req.body.roles) && req.body.roles[0]) || 'visitor';
    const walking_speed = req.body.walking_speed || 1.2;

    if (!current_location || !destination_node) {
        return res.status(400).json({
            status: 'error',
            message: 'current_location (or start_node_id) and destination_node (or destination_node_id) are required.'
        });
    }

    try {
        // 1. Run core navigation engine (validates A* path and user role)
        const navResult = await runNavigation({
            currentLocation: current_location,
            destinationNode: destination_node,
            rbacRole: rbac_role,
            walkingSpeed: parseFloat(walking_speed) || 1.2
        });

        // 2. Build filtered map context using shared visualisation service
        // (Applies strict RBAC on all nodes/edges + route relevance)
        const mapContext = await buildVisualisationModel({
            routeResult: navResult,
            rbacRole: rbac_role
        });

        // 3. Generate route floorplan visualizations (PNG with highlighted walking path)
        let visualisations = [];
        try {
            const proto = req.headers['x-forwarded-proto'] || (req.secure ? 'https' : 'http');
            const host = req.headers['x-forwarded-host'] || req.headers.host || 'localhost:5000';
            const baseUrl = process.env.MOBILE_BASE_URL ? process.env.MOBILE_BASE_URL.replace(/\/$/, '') : `${proto}://${host}`;
            const tempToken = 'nav_' + Date.now();
            const generated = await routeVisualizer.generate(navResult, tempToken);
            visualisations = generated.map(v => ({
                floorplan_id: v.floorplanId,
                floor_level: v.floorLevel,
                building_name: v.buildingName,
                filename: v.filename,
                image_url: `${baseUrl}/uploads/visualisations/${v.filename}`,
                local_image_url: `http://127.0.0.1:5000/uploads/visualisations/${v.filename}`,
                file_url: v.filePath ? `file:///${v.filePath.replace(/\\/g, '/')}` : ''
            }));
            navResult.visualisations = visualisations;
        } catch (visErr) {
            console.warn('[KioskController] Route visualizer error:', visErr.message);
        }

        // 4. Create short-lived mobile navigation session and generate QR code
        let qrSession = null;
        try {
            qrSession = await kioskSessionService.createSession({
                navResult,
                mapContext,
                startId: current_location,
                endId: destination_node,
                roleId: rbac_role,
                walkingSpeed: parseFloat(walking_speed) || 1.2,
                req
            });
        } catch (sessionErr) {
            console.warn('[KioskController] Failed to create QR session:', sessionErr.message);
        }

        return res.json({
            status: 'success',
            navigation: navResult,
            map_context: mapContext,
            qr_session: qrSession,
            visualisations: visualisations
        });

    } catch (err) {
        const status = err.status || 500;
        return res.status(status).json({
            status: 'error',
            message: err.message || 'Kiosk navigation failed.'
        });
    }
};

/**
 * Fetch global nodes for the kiosk search/select dropdowns.
 * Strictly requires a role parameter to prevent information leakage.
 */
exports.getKioskGlobalNodes = async (req, res) => {
    const roleParam = req.query.role;

    if (!roleParam || String(roleParam).trim() === '') {
        return res.status(400).json({
            error: 'Role is required to fetch global nodes in kiosk view.'
        });
    }

    const userRoleId = resolveRoleId(roleParam);

    try {
        const sql = `
            SELECT n.node_id, n.room_label, n.node_type, n.floorplan_id, n.is_accessible,
                   f.floor_level, b.building_name,
                   GROUP_CONCAT(nr.role_id) AS allowed_roles
            FROM nodes n 
            JOIN floorplans f ON n.floorplan_id = f.floorplan_id 
            JOIN buildings b ON f.building_id = b.building_id
            LEFT JOIN node_rbac nr ON n.node_id = nr.node_id
            WHERE n.is_accessible != 'DENY'
            GROUP BY n.node_id
            ORDER BY b.building_name, f.floor_level, n.room_label
        `;

        const results = await queryAsync(sql);

        // Filter strictly by RBAC role
        const filteredNodes = results
            .filter(node => isRolePermitted(node, userRoleId))
            .map(node => ({
                node_id: node.node_id,
                room_label: node.room_label,
                node_type: node.node_type,
                floorplan_id: node.floorplan_id,
                floor_level: node.floor_level,
                building_name: node.building_name
            }));

        return res.json(filteredNodes);
    } catch (err) {
        console.error('[KioskController] Error fetching role-filtered global nodes:', err);
        return res.status(500).json({ error: 'Failed to fetch global nodes for role.' });
    }
};

/**
 * Public endpoint to retrieve an active mobile navigation session by token.
 * Does not require admin authentication.
 * Returns only the session's pre-calculated, role-filtered navigation and map context.
 */
exports.getMobileSession = async (req, res) => {
    const { token } = req.params;

    if (!token || typeof token !== 'string') {
        return res.status(400).json({
            status: 'error',
            error: 'INVALID_TOKEN',
            message: 'Session token is required.'
        });
    }

    try {
        const session = await kioskSessionService.getSession(token);

        if (!session) {
            return res.status(404).json({
                status: 'error',
                error: 'SESSION_EXPIRED_OR_NOT_FOUND',
                message: 'This navigation session has expired or is invalid. Please calculate a new route on the kiosk.'
            });
        }

        return res.json({
            status: 'success',
            navigation: session.navigation,
            map_context: session.map_context,
            session_info: {
                start_id: session.current_location,
                destination_id: session.destination_node,
                rbac_role: session.rbac_role,
                walking_speed: session.walking_speed,
                created_at: session.created_at,
                expires_at: session.expires_at
            }
        });
    } catch (err) {
        console.error('[KioskController] Error retrieving mobile session:', err);
        return res.status(500).json({
            status: 'error',
            error: 'SERVER_ERROR',
            message: 'Failed to retrieve navigation session.'
        });
    }
};

/**
 * Public HTML endpoint to render the companion mobile wayfinding page in a clean light theme.
 */
exports.renderMobileRoutePage = async (req, res) => {
    const { token } = req.params;

    if (!token || typeof token !== 'string') {
        return res.status(400).send('<h3>Invalid session token.</h3>');
    }

    try {
        const session = await kioskSessionService.getSession(token);

        if (!session) {
            return res.status(404).send(`
                <!DOCTYPE html>
                <html lang="en">
                <head>
                    <meta charset="UTF-8">
                    <meta name="viewport" content="width=device-width, initial-scale=1.0">
                    <title>Session Expired • Campus Navigation</title>
                    <script src="https://cdn.tailwindcss.com"></script>
                </head>
                <body class="bg-slate-100 text-slate-800 flex items-center justify-center min-h-screen p-4">
                    <div class="bg-white p-6 rounded-2xl shadow-md border border-slate-200 max-w-sm w-full text-center">
                        <div class="w-12 h-12 rounded-full bg-amber-100 text-amber-600 flex items-center justify-center mx-auto mb-3 text-2xl">⏱️</div>
                        <h2 class="text-lg font-bold text-slate-900 mb-1">Session Expired</h2>
                        <p class="text-xs text-slate-600 mb-4">This navigation QR code has expired (15m limit). Please request directions again at the campus kiosk.</p>
                        <div class="text-[11px] text-slate-400 font-mono bg-slate-50 p-2 rounded border border-slate-200">Session: ${token.substring(0, 12)}...</div>
                    </div>
                </body>
                </html>
            `);
        }

        const nav = session.navigation || {};
        const summary = nav.route_summary || {};
        const instructions = nav.instructions || [];
        const mapContext = session.map_context || {};
        const visualisations = nav.visualisations || [];

        // Order floorplans strictly by route progression (Current Location first -> next -> destination)
        const floorplanOrder = [];
        if (Array.isArray(nav.path)) {
            for (const node of nav.path) {
                const fpId = Number(node.floorplan_id);
                if (fpId && !floorplanOrder.includes(fpId) && mapContext[fpId]) {
                    floorplanOrder.push(fpId);
                }
            }
        }
        for (const fpId of Object.keys(mapContext).map(Number)) {
            if (!floorplanOrder.includes(fpId)) {
                floorplanOrder.push(fpId);
            }
        }
        const activeFpId = floorplanOrder[0] || null;

        const visByFloor = {};
        for (const v of visualisations) {
            visByFloor[String(v.floorplan_id)] = v.filename ? `/uploads/visualisations/${v.filename}` : (v.image_url || '');
        }
        const defaultVis = visualisations.find(v => Number(v.floorplan_id) === Number(activeFpId)) || visualisations[0] || null;
        const defaultImgUrl = defaultVis ? (defaultVis.filename ? `/uploads/visualisations/${defaultVis.filename}` : (defaultVis.image_url || '')) : '';

        const html = `
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=3.0, user-scalable=yes">
                <title>Mobile Walking Guide • ${summary.destination_label || 'Campus Route'}</title>
                <script src="https://cdn.tailwindcss.com"></script>
                ${floorplanOrder.map(fpId => {
                    const url = visByFloor[String(fpId)];
                    return url ? `<link rel="preload" as="image" href="${url}">` : '';
                }).join('\n                ')}
                <style>
                    .touch-none { touch-action: none; }
                </style>
            </head>
            <body class="bg-slate-100 text-slate-800 font-sans antialiased p-3 min-h-screen pb-10">
                <div class="max-w-md mx-auto flex flex-col gap-3">
                    
                    <!-- Header Card -->
                    <div class="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm">
                        <div class="flex items-center justify-between mb-2">
                            <span class="text-[10px] font-bold text-teal-700 bg-teal-50 border border-teal-200 px-2 py-0.5 rounded-full uppercase tracking-wider">
                                🧭 Smart Campus Walking Guide
                            </span>
                            <span class="text-[10px] text-slate-500 font-mono">⏱️ Active Session</span>
                        </div>
                        <h1 class="text-base font-bold text-slate-900 leading-tight">
                            ${summary.destination_label || 'Destination'}
                        </h1>
                        <p class="text-xs text-slate-500 mt-0.5">
                            From: <span class="font-medium text-slate-700">${summary.start_label || 'Current Location'}</span>
                        </p>

                        <div class="grid grid-cols-3 gap-2 mt-3 pt-3 border-t border-slate-100 text-center">
                            <div class="bg-slate-50 p-2 rounded-xl border border-slate-200/80">
                                <div class="text-[9px] text-slate-500 uppercase tracking-wider font-semibold">Distance</div>
                                <div class="text-sm font-bold text-teal-700 mt-0.5">${summary.total_distance_m || 0}m</div>
                            </div>
                            <div class="bg-slate-50 p-2 rounded-xl border border-slate-200/80">
                                <div class="text-[9px] text-slate-500 uppercase tracking-wider font-semibold">Est. Time</div>
                                <div class="text-sm font-bold text-indigo-700 mt-0.5">${summary.estimated_time_label || '1 min'}</div>
                            </div>
                            <div class="bg-slate-50 p-2 rounded-xl border border-slate-200/80">
                                <div class="text-[9px] text-slate-500 uppercase tracking-wider font-semibold">Steps</div>
                                <div class="text-sm font-bold text-slate-800 mt-0.5">${instructions.length}</div>
                            </div>
                        </div>
                    </div>

                    <!-- Multi-Floor Level Switcher (Ordered: Current Location -> Next -> Destination) -->
                    ${floorplanOrder.length > 1 ? `
                    <div class="bg-white p-1.5 rounded-xl border border-slate-200 shadow-sm flex gap-1.5 overflow-x-auto">
                        ${floorplanOrder.map((fpId, idx) => {
                            const fp = mapContext[fpId];
                            const isStart = idx === 0;
                            const isEnd = idx === floorplanOrder.length - 1 && floorplanOrder.length > 1;
                            const prefix = isStart ? '🟢 1. ' : (isEnd ? `🏁 ${idx + 1}. ` : `⬆️ ${idx + 1}. `);
                            const suffix = isStart ? ' (Current)' : (isEnd ? ' (Destination)' : '');
                            return `
                                <button onclick="switchFloor('${fpId}')" id="btn-fp-${fpId}" class="floor-btn flex-1 py-1.5 px-2.5 rounded-lg text-center text-xs font-semibold whitespace-nowrap transition-all ${idx === 0 ? 'bg-teal-600 text-white shadow-xs' : 'bg-slate-50 text-slate-600 hover:bg-slate-100'}">
                                    ${prefix}${fp ? fp.building_name : 'Building'} • L${fp ? fp.floor_level : '1'}${suffix}
                                </button>
                            `;
                        }).join('')}
                    </div>
                    ` : ''}

                    <!-- Floor Plan Route Map Card with Full Fit & Smooth Pan/Zoom -->
                    <div class="bg-white rounded-2xl border border-slate-200 overflow-hidden shadow-sm flex flex-col">
                        <div class="px-3.5 py-2.5 border-b border-slate-200 flex items-center justify-between text-xs bg-slate-50">
                            <span class="font-bold text-slate-800 flex items-center gap-1.5">
                                <span>🗺️</span> Floor Plan Walking Route
                            </span>
                            <span id="current-floor-badge" class="text-[10px] font-bold text-teal-700 bg-teal-50 border border-teal-200 px-2 py-0.5 rounded-full">
                                Loading...
                            </span>
                        </div>

                        <!-- Interactive Map Viewport -->
                        <div id="map-viewport" class="relative w-full h-[360px] bg-slate-50 overflow-hidden select-none flex items-center justify-center cursor-grab active:cursor-grabbing touch-none">
                            <!-- Pan & Zoom Canvas Layer -->
                            <div id="map-canvas" class="relative w-full h-full flex items-center justify-center origin-center transition-transform duration-75" style="transform: translate(0px, 0px) scale(1);">
                                ${floorplanOrder.map((fpId) => `
                                    <img 
                                        id="floor-img-${fpId}" 
                                        src="${visByFloor[String(fpId)] || ''}" 
                                        alt="Floor Plan Level ${fpId}" 
                                        class="floor-img absolute max-w-[96%] max-h-[96%] object-contain select-none transition-opacity duration-150 drop-shadow-sm ${String(fpId) === String(activeFpId) ? 'opacity-100 z-10' : 'opacity-0 z-0 pointer-events-none'}"
                                        draggable="false"
                                    />
                                `).join('')}
                            </div>

                            <!-- Zoom/Pan Controls Overlay -->
                            <div class="absolute bottom-3 right-3 flex flex-col gap-1 bg-white/95 backdrop-blur-sm p-1 rounded-xl border border-slate-200 shadow-md z-20">
                                <button onclick="zoom(1.25)" class="w-8 h-8 flex items-center justify-center rounded-lg bg-slate-50 hover:bg-slate-100 text-slate-700 font-bold text-base border border-slate-200 cursor-pointer active:scale-95" title="Zoom In">+</button>
                                <button onclick="resetZoom()" class="w-8 h-8 flex items-center justify-center rounded-lg bg-slate-50 hover:bg-slate-100 text-teal-600 font-bold text-xs border border-slate-200 cursor-pointer active:scale-95" title="Fit to Screen">⟲</button>
                                <button onclick="zoom(0.8)" class="w-8 h-8 flex items-center justify-center rounded-lg bg-slate-50 hover:bg-slate-100 text-slate-700 font-bold text-base border border-slate-200 cursor-pointer active:scale-95" title="Zoom Out">−</button>
                            </div>

                            <!-- Hint Badge Overlay -->
                            <div class="absolute top-2 left-3 pointer-events-none z-20">
                                <span class="text-[10px] text-slate-500 bg-white/90 backdrop-blur-sm px-2 py-0.5 rounded border border-slate-200/80 shadow-xs">
                                    Pinch to zoom • Drag to pan
                                </span>
                            </div>
                        </div>
                    </div>

                    <!-- Turn-by-Turn Directions Checklist -->
                    <div class="bg-white p-4 rounded-2xl border border-slate-200 shadow-sm flex flex-col gap-2.5">
                        <div class="flex items-center justify-between">
                            <h2 class="text-xs font-bold text-slate-900 uppercase tracking-wider flex items-center gap-1.5">
                                <span>🚶</span> Step-by-Step Directions
                            </h2>
                            <span id="step-progress" class="text-[9px] text-teal-700 font-semibold bg-teal-50 px-2 py-0.5 rounded border border-teal-100">
                                0 of ${instructions.length} Done
                            </span>
                        </div>

                        <div class="flex flex-col gap-2 mt-1">
                            ${instructions.map((step, idx) => `
                                <div onclick="toggleStep(${idx}, ${step.floorplan_id || 'null'})" class="step-item flex items-start gap-3 p-3 rounded-xl bg-slate-50 border border-slate-200 cursor-pointer hover:border-slate-300 transition-all">
                                    <input type="checkbox" id="chk-${idx}" class="mt-0.5 rounded text-teal-600 bg-white border-slate-300 cursor-pointer pointer-events-none">
                                    <div class="flex-1 min-w-0">
                                        <div class="flex items-center justify-between gap-1">
                                            <span class="text-xs font-bold text-slate-900">${idx + 1}. ${step.instruction || step.description || 'Proceed along corridor'}</span>
                                            ${step.distance_m ? `<span class="text-[10px] text-slate-500 font-mono shrink-0">${step.distance_m}m</span>` : ''}
                                        </div>
                                        ${step.building_name ? `<div class="text-[10px] text-teal-700 font-medium mt-0.5">${step.building_name} Floor ${step.floor_level}</div>` : ''}
                                    </div>
                                </div>
                            `).join('')}
                        </div>
                    </div>

                    <!-- Footer -->
                    <div class="text-center text-[10px] text-slate-400 py-3">
                        Smart Campus Navigation • Companion Mobile View
                    </div>

                </div>

                <script>
                    const totalSteps = ${instructions.length};
                    const mapContext = ${JSON.stringify(mapContext)};
                    const navResult = ${JSON.stringify(nav)};
                    const floorImages = ${JSON.stringify(visByFloor)};
                    const floorplanOrder = ${JSON.stringify(floorplanOrder)};
                    let activeFloorId = ${activeFpId ? String(activeFpId) : 'null'};

                    // Pan and Zoom Transform State
                    let scale = 1.0;
                    let panX = 0, panY = 0;
                    let isDragging = false;
                    let startX = 0, startY = 0;
                    let initialDistance = 0;
                    let initialScale = 1.0;

                    const canvas = document.getElementById('map-canvas');
                    const viewport = document.getElementById('map-viewport');

                    function updateTransform() {
                        if (canvas) {
                            canvas.style.transform = 'translate(' + panX + 'px, ' + panY + 'px) scale(' + scale + ')';
                        }
                    }

                    function zoom(factor) {
                        scale = Math.min(Math.max(0.85, scale * factor), 5.0);
                        if (scale <= 1.0) {
                            panX = 0;
                            panY = 0;
                        }
                        updateTransform();
                    }

                    function resetZoom() {
                        scale = 1.0;
                        panX = 0;
                        panY = 0;
                        updateTransform();
                    }

                    function updateBadge() {
                        const badge = document.getElementById('current-floor-badge');
                        if (!badge || !activeFloorId || !mapContext[activeFloorId]) return;
                        const fp = mapContext[activeFloorId];
                        const startNode = navResult.path ? navResult.path[0] : null;
                        const endNode = navResult.path ? navResult.path[navResult.path.length - 1] : null;
                        const isStartFloor = startNode && startNode.floorplan_id === Number(activeFloorId);
                        const isEndFloor = endNode && endNode.floorplan_id === Number(activeFloorId);
                        const label = (fp.building_name || 'Building') + ' • Level ' + fp.floor_level + 
                                      (isStartFloor ? ' (Current Location)' : (isEndFloor ? ' (Destination)' : ''));
                        badge.innerText = label;
                    }

                    function switchFloor(fpId) {
                        activeFloorId = String(fpId);

                        // 1. Update tab buttons
                        document.querySelectorAll('.floor-btn').forEach(btn => {
                            btn.classList.remove('bg-teal-600', 'text-white', 'shadow-xs');
                            btn.classList.add('bg-slate-50', 'text-slate-600');
                        });
                        const active = document.getElementById('btn-fp-' + fpId);
                        if (active) {
                            active.classList.add('bg-teal-600', 'text-white', 'shadow-xs');
                            active.classList.remove('bg-slate-50', 'text-slate-600');
                        }

                        // 2. Instant zero-delay image swap (already in DOM/cache)
                        document.querySelectorAll('.floor-img').forEach(img => {
                            img.classList.remove('opacity-100', 'z-10');
                            img.classList.add('opacity-0', 'z-0', 'pointer-events-none');
                        });
                        const targetImg = document.getElementById('floor-img-' + fpId);
                        if (targetImg) {
                            targetImg.classList.remove('opacity-0', 'z-0', 'pointer-events-none');
                            targetImg.classList.add('opacity-100', 'z-10');
                        }

                        resetZoom();
                        updateBadge();
                    }

                    // Mouse Drag Events
                    if (viewport) {
                        viewport.addEventListener('mousedown', e => {
                            e.preventDefault();
                            isDragging = true;
                            startX = e.clientX - panX;
                            startY = e.clientY - panY;
                        });
                        window.addEventListener('mousemove', e => {
                            if (!isDragging) return;
                            panX = e.clientX - startX;
                            panY = e.clientY - startY;
                            updateTransform();
                        });
                        window.addEventListener('mouseup', () => { isDragging = false; });

                        // Mouse Wheel Zoom
                        viewport.addEventListener('wheel', e => {
                            e.preventDefault();
                            const factor = e.deltaY > 0 ? 0.9 : 1.1;
                            zoom(factor);
                        }, { passive: false });

                        // Touch Drag & Pinch-to-Zoom
                        viewport.addEventListener('touchstart', e => {
                            if (e.touches.length === 1) {
                                isDragging = true;
                                startX = e.touches[0].clientX - panX;
                                startY = e.touches[0].clientY - panY;
                            } else if (e.touches.length === 2) {
                                isDragging = false;
                                const dx = e.touches[0].clientX - e.touches[1].clientX;
                                const dy = e.touches[0].clientY - e.touches[1].clientY;
                                initialDistance = Math.hypot(dx, dy);
                                initialScale = scale;
                            }
                        }, { passive: true });

                        viewport.addEventListener('touchmove', e => {
                            if (isDragging && e.touches.length === 1) {
                                panX = e.touches[0].clientX - startX;
                                panY = e.touches[0].clientY - startY;
                                updateTransform();
                            } else if (e.touches.length === 2 && initialDistance > 0) {
                                const dx = e.touches[0].clientX - e.touches[1].clientX;
                                const dy = e.touches[0].clientY - e.touches[1].clientY;
                                const dist = Math.hypot(dx, dy);
                                scale = Math.min(Math.max(0.85, initialScale * (dist / initialDistance)), 5.0);
                                updateTransform();
                            }
                        }, { passive: true });

                        viewport.addEventListener('touchend', () => { isDragging = false; });

                        // Double Tap to Toggle Zoom
                        let lastTap = 0;
                        viewport.addEventListener('touchend', e => {
                            const now = Date.now();
                            if (now - lastTap < 300) {
                                e.preventDefault();
                                if (scale > 1.2) resetZoom();
                                else zoom(2.2);
                            }
                            lastTap = now;
                        });
                    }

                    function toggleStep(idx, stepFpId) {
                        const chk = document.getElementById('chk-' + idx);
                        if (chk) {
                            chk.checked = !chk.checked;
                            updateProgress();
                        }
                        if (stepFpId && String(stepFpId) !== activeFloorId) {
                            switchFloor(stepFpId);
                        }
                    }

                    function updateProgress() {
                        let done = 0;
                        for (let i = 0; i < totalSteps; i++) {
                            const c = document.getElementById('chk-' + i);
                            if (c && c.checked) done++;
                        }
                        const prog = document.getElementById('step-progress');
                        if (prog) prog.innerText = done + ' of ' + totalSteps + ' Done';
                    }

                    // Initial setup
                    updateBadge();
                </script>
            </body>
            </html>
        `;

        res.setHeader('Content-Type', 'text/html');
        return res.send(html);
    } catch (err) {
        console.error('[KioskController] Error rendering mobile route page:', err);
        return res.status(500).send('<h3>Error rendering mobile route page.</h3>');
    }
};

