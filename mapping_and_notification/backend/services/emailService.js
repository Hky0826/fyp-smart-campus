/**
 * @file emailService.js
 * @description Email Service for the Campus Navigation System.
 *
 * Supports two delivery modes, selectable at runtime via the `email_delivery_mode`
 * field on any request payload (or falling back to the EMAIL_MODE environment variable):
 *
 *   - "ethereal"  Use Ethereal SMTP (development / testing sandbox).
 *   - "smtp"      Use a real SMTP provider configured in .env.
 *
 * Route visualization images are embedded as inline CID attachments in the
 * VISITOR email only for appointment_routing events. The host email never
 * receives visualization images.
 */

'use strict';

const nodemailer = require('nodemailer');
const fs   = require('fs');
const path = require('path');

const ETHEREAL_CACHE_PATH = path.join(__dirname, '..', 'data', 'ethereal_account.json');

// Ensure data folder exists
const dataDir = path.dirname(ETHEREAL_CACHE_PATH);
if (!fs.existsSync(dataDir)) {
    fs.mkdirSync(dataDir, { recursive: true });
}

// ─────────────────────────────────────────────────────────────────────────────
// TRANSPORTER FACTORY
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Build a Nodemailer transporter for the requested delivery mode.
 *
 * @param {string} [mode] - "ethereal" | "smtp". Falls back to EMAIL_MODE env var,
 *                          then to "ethereal" if neither is set.
 * @returns {Promise<import('nodemailer').Transporter>}
 */
async function getTransporter(mode) {
    // Resolve the effective mode
    const effectiveMode = (mode || process.env.EMAIL_MODE || 'ethereal').toLowerCase();

    if (effectiveMode === 'smtp') {
        const host = process.env.SMTP_HOST;
        const port = process.env.SMTP_PORT;
        const user = process.env.SMTP_USER;
        const pass = process.env.SMTP_PASSWORD;

        if (!host || !port || !user || !pass) {
            throw new Error('[EmailService] EMAIL_MODE=smtp requested but SMTP configuration is incomplete in .env. Required: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD.');
        }

        console.log(`[EmailService] Using real SMTP server: ${host}`);
        return nodemailer.createTransport({
            host,
            port:   parseInt(port, 10),
            secure: process.env.SMTP_SECURE === 'true' || parseInt(port, 10) === 465,
            auth: {
                user,
                pass
            }
        });
    }

    // ── Ethereal mode ──────────────────────────────────────────────────────────
    console.log('[EmailService] Using Ethereal SMTP sandbox.');
    let etherealAccount;

    if (fs.existsSync(ETHEREAL_CACHE_PATH)) {
        try {
            etherealAccount = JSON.parse(fs.readFileSync(ETHEREAL_CACHE_PATH, 'utf8'));
            console.log('[EmailService] Loaded cached Ethereal account credentials.');
        } catch (_) {
            console.error('[EmailService] Failed to parse cached Ethereal account, recreating...');
        }
    }

    if (!etherealAccount) {
        console.log('[EmailService] Creating new Ethereal SMTP test account...');
        etherealAccount = await nodemailer.createTestAccount();
        fs.writeFileSync(ETHEREAL_CACHE_PATH, JSON.stringify(etherealAccount, null, 2), 'utf8');
        console.log(`[EmailService] Saved Ethereal credentials to: ${ETHEREAL_CACHE_PATH}`);
    }

    return nodemailer.createTransport({
        host:   etherealAccount.smtp.host,
        port:   etherealAccount.smtp.port,
        secure: etherealAccount.smtp.secure,
        auth: {
            user: etherealAccount.user,
            pass: etherealAccount.pass
        }
    });
}

// ─────────────────────────────────────────────────────────────────────────────
// FORMATTING HELPERS
// ─────────────────────────────────────────────────────────────────────────────

function formatWalkingTime(seconds) {
    if (seconds === undefined || seconds === null || seconds === '') return '0 seconds';
    const secs = Number(seconds);
    if (secs < 60) return `${secs} second${secs !== 1 ? 's' : ''}`;
    const mins = Math.floor(secs / 60);
    const remainingSecs = secs % 60;
    const minPart = `${mins} minute${mins !== 1 ? 's' : ''}`;
    const secPart = remainingSecs > 0 ? ` ${remainingSecs} second${remainingSecs !== 1 ? 's' : ''}` : '';
    return minPart + secPart;
}

function formatEventType(type) {
    if (!type) return 'Unknown Event';
    return type.split('_').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
}

function formatLocationDisplay(label) {
    if (label && label.trim().length > 0) return label.trim();
    return 'Unknown Location';
}

function formatBuildingName(name) {
    if (name && name.trim().length > 0) return name.trim();
    return 'Main Campus Building';
}

function formatFloorLevel(level) {
    if (level === undefined || level === null || level === '') return 'N/A';
    const lvlNum = Number(level);
    if (lvlNum === 1 || lvlNum === 0) return 'Ground Floor';
    return `Level ${lvlNum}`;
}

// ─────────────────────────────────────────────────────────────────────────────
// SEND WITH RETRY
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Send an email with retry logic for transient errors.
 *
 * @param {import('nodemailer').Transporter} transporter
 * @param {string}   toEmail
 * @param {string}   subject
 * @param {string}   htmlContent
 * @param {Array}    [attachments=[]] - Nodemailer attachment objects.
 * @param {number}   [maxRetries=3]
 */
async function sendEmailWithRetry(transporter, toEmail, subject, htmlContent, attachments = [], maxRetries = 3) {
    let attempt = 0;
    const senderAddress = process.env.SMTP_FROM || process.env.SMTP_USER || 'noreply@campusnavigation.com';

    while (attempt < maxRetries) {
        attempt++;
        try {
            const info = await transporter.sendMail({
                from:        `"Campus Navigation Hub" <${senderAddress}>`,
                to:          toEmail,
                subject,
                html:        htmlContent,
                attachments
            });

            console.log(`[EmailService] Email dispatched. SMTP messageId=${info.messageId}`);
            const previewUrl = nodemailer.getTestMessageUrl(info);
            if (previewUrl) {
                console.log(`[EmailService] Ethereal Sandbox Email Preview Link:\n           --> ${previewUrl} <--`);
            }
            return { success: true, info, previewUrl };
        } catch (error) {
            console.warn(`[EmailService] SMTP send attempt ${attempt}/${maxRetries} failed:`, error.message);
            if (attempt >= maxRetries) {
                return { success: false, error };
            }
            await new Promise(resolve => setTimeout(resolve, 2000));
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// ROUTE VISUALIZATION HTML SECTION
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Build the combined per-floor HTML sections.
 * Each floor segment shows: Building/Floor header → Route visualization image → Turn-by-turn directions for that floor.
 *
 * Instructions are grouped by their `floorplan_id` field (added by engineController.generateInstructions).
 * Visualizations are matched to floors by their `floorplanId` field.
 *
 * @param {Array<{cid, buildingName, floorLevel, floorplanId}>} visualizations
 * @param {Array} instructions  - Instruction steps with floorplan_id, floor_level, building_name.
 * @returns {string} HTML string for combined per-floor sections.
 */
function buildPerFloorSectionsHTML(visualizations, instructions) {
    if ((!visualizations || visualizations.length === 0) && (!instructions || instructions.length === 0)) {
        return '';
    }

    // Group instructions by floorplan_id, preserving order of first appearance
    const floorOrder = [];
    const floorInstructions = {};
    const floorMeta = {};

    if (instructions && instructions.length > 0) {
        for (const step of instructions) {
            const fpId = step.floorplan_id;
            if (fpId == null) continue;
            const key = String(fpId);
            if (!floorInstructions[key]) {
                floorInstructions[key] = [];
                floorOrder.push(key);
                floorMeta[key] = {
                    building_name: step.building_name || 'Building',
                    floor_level: step.floor_level != null ? step.floor_level : 'N/A'
                };
            }
            floorInstructions[key].push(step);
        }
    }

    // Build visualization lookup by floorplanId
    const vizByFloorplan = {};
    if (visualizations && visualizations.length > 0) {
        for (const viz of visualizations) {
            const key = String(viz.floorplanId);
            vizByFloorplan[key] = viz;
            // Ensure this floor is in the order even if it has no instructions
            if (!floorInstructions[key]) {
                floorInstructions[key] = [];
                if (!floorOrder.includes(key)) {
                    floorOrder.push(key);
                }
                floorMeta[key] = {
                    building_name: viz.buildingName || 'Building',
                    floor_level: viz.floorLevel != null ? viz.floorLevel : 'N/A'
                };
            }
        }
    }

    // Build per-floor sections
    const sections = floorOrder.map(fpKey => {
        const meta = floorMeta[fpKey] || {};
        const viz = vizByFloorplan[fpKey];
        const steps = floorInstructions[fpKey] || [];

        const bldgName = meta.building_name || 'Building';
        const floorLvl = meta.floor_level;

        // Floor header
        let sectionHTML = `
            <div style="border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 18px; overflow: hidden;">
                <div style="background-color: #f8fafc; padding: 10px 16px; border-bottom: 1px solid #e2e8f0;">
                    <h3 style="margin: 0; font-size: 12px; font-weight: 700; color: #4f46e5; text-transform: uppercase; letter-spacing: 0.05em;">📍 ${bldgName} &mdash; Floor ${floorLvl}</h3>
                </div>
                <div style="padding: 12px 16px;">`;

        // Visualization image
        if (viz) {
            sectionHTML += `
                    <img
                        src="cid:${viz.cid}"
                        alt="${bldgName} Floor ${floorLvl} route map"
                        style="max-width: 100%; border-radius: 8px; border: 1px solid #e2e8f0; display: block; margin-bottom: 16px;"
                    />`;
        }

        // Per-floor directions
        if (steps.length > 0) {
            sectionHTML += `
                    <p style="font-size: 11px; font-weight: 700; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; margin: 0 0 8px 0;">Turn-by-Turn Directions</p>
                    <div style="margin-top: 4px;">`;

            for (const step of steps) {
                const icons = {
                    start:      '🟢',
                    walk:       '⬆️',
                    turn:       step.action === 'left' ? '↰' : '↱',
                    transition: step.action === 'elevator' ? '🛗' : step.action === 'stairwell' ? '🪜' : '🚪',
                    arrive:     '🏁'
                };
                const stepIcon = icons[step.type] || '•';
                sectionHTML += `
                        <div style="display: flex; gap: 12px; margin-bottom: 8px; padding: 12px; background-color: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0; align-items: center;">
                            <span style="font-size: 18px; line-height: 1;">${stepIcon}</span>
                            <div style="font-size: 13.5px; color: #334155; font-weight: 500;">
                                ${step.description}
                                ${step.type === 'walk' ? `<span style="font-size: 11px; color: #64748b; font-weight: normal; margin-left: 6px;">(${step.distance_m}m)</span>` : ''}
                            </div>
                        </div>`;
            }

            sectionHTML += `
                    </div>`;
        }

        sectionHTML += `
                </div>
            </div>`;

        return sectionHTML;
    }).join('');

    return sections;
}

/**
 * Convert routeVisualizations array to Nodemailer attachment objects.
 *
 * @param {Array<{cid, filePath, filename}>} visualizations
 * @returns {Array}
 */
function buildAttachments(visualizations) {
    if (!visualizations || visualizations.length === 0) return [];
    return visualizations.map(viz => ({
        filename: viz.filename,
        path:     viz.filePath,
        cid:      viz.cid
    }));
}

// ─────────────────────────────────────────────────────────────────────────────
// HOST EMAIL
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Draft and send the Host email.
 * The host email never includes route visualization images.
 *
 * @param {Object} opts
 * @param {string} opts.toEmail
 * @param {string} opts.hostName
 * @param {string} opts.visitorName
 * @param {number} opts.visitorId
 * @param {string} opts.eventType
 * @param {string} opts.visitorRole
 * @param {string} opts.startNodeLabel
 * @param {string} opts.destinationNodeLabel
 * @param {number} opts.walkingTimeSeconds
 * @param {number} opts.totalDistanceMetres
 * @param {string} opts.alertMsg
 * @param {Array}  opts.instructions
 * @param {string} [opts.emailDeliveryMode]  - "ethereal" | "smtp"
 */
async function sendHostEmail({
    toEmail, hostName, visitorName, visitorId, eventType, visitorRole,
    startNodeLabel, destinationNodeLabel, walkingTimeSeconds, totalDistanceMetres,
    alertMsg, instructions, emailDeliveryMode
}) {
    const transporter          = await getTransporter(emailDeliveryMode);
    const formattedEventType   = formatEventType(eventType);
    const startLabel           = formatLocationDisplay(startNodeLabel);
    const destinationLabel     = formatLocationDisplay(destinationNodeLabel);
    const walkingTimeLabel     = formatWalkingTime(walkingTimeSeconds);
    const distanceStr          = `${Number(totalDistanceMetres || 0).toFixed(2)} metres`;
    const genTimeStr           = new Date().toLocaleString('en-US', { timeZoneName: 'short' });

    const subjectPrefix = eventType === 'emergency_alert'
        ? '🚨 Campus Emergency Alert'
        : eventType === 'visitor_arrival'
            ? '📍 Campus Visitor Arrival Notification'
            : '🔔 Campus Host Notification';
    const subject = `${subjectPrefix}: ${visitorName}`;

    let bodyHTML = '';

    // ── Visitor Arrival ──────────────────────────────────────────────────────
    if (eventType === 'visitor_arrival') {
        bodyHTML = `
        <div style="font-family: 'Inter', -apple-system, sans-serif; line-height: 1.6; color: #1e293b; max-width: 600px; margin: 0 auto; border: 1px solid #e2e8f0; padding: 24px; border-radius: 12px; background-color: #ffffff;">
            <div style="background: linear-gradient(135deg, #10b981, #059669); padding: 16px; border-radius: 8px; margin-bottom: 20px; text-align: center;">
                <h2 style="color: #ffffff; margin: 0; font-size: 20px; font-weight: bold; letter-spacing: 0.05em;">📍 CAMPUS VISITOR ARRIVAL NOTIFICATION</h2>
            </div>
            <p style="font-size: 15px; margin-top: 0;">Dear <strong>${hostName}</strong>,</p>
            <p style="font-size: 15px; color: #334155; font-weight: 500; margin-bottom: 24px;">
                Your visitor <strong>${visitorName}</strong> has successfully arrived at <strong>${destinationLabel}</strong>.
            </p>
            <div style="border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 18px; overflow: hidden;">
                <div style="background-color: #f8fafc; padding: 10px 16px; border-bottom: 1px solid #e2e8f0;">
                    <h3 style="margin: 0; font-size: 12px; font-weight: 700; color: #10b981; text-transform: uppercase; letter-spacing: 0.05em;">Visitor Information</h3>
                </div>
                <div style="padding: 12px 16px;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                        <tr><td style="padding: 4px 0; color: #64748b; width: 40%;">Visitor Name:</td><td style="padding: 4px 0; color: #1e293b; font-weight: 600;">${visitorName}</td></tr>
                        <tr><td style="padding: 4px 0; color: #64748b;">Visitor Role:</td><td style="padding: 4px 0; color: #1e293b; font-weight: 600;">${visitorRole || 'Visitor'}</td></tr>
                        <tr><td style="padding: 4px 0; color: #64748b;">Event Type:</td><td style="padding: 4px 0; color: #1e293b; font-weight: 600;">Visitor Arrival</td></tr>
                    </table>
                </div>
            </div>
            <div style="border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 24px; overflow: hidden;">
                <div style="background-color: #f8fafc; padding: 10px 16px; border-bottom: 1px solid #e2e8f0;">
                    <h3 style="margin: 0; font-size: 12px; font-weight: 700; color: #10b981; text-transform: uppercase; letter-spacing: 0.05em;">Arrival Details</h3>
                </div>
                <div style="padding: 12px 16px;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                        <tr><td style="padding: 4px 0; color: #64748b; width: 40%;">Arrival Location:</td><td style="padding: 4px 0; color: #1e293b; font-weight: 600;">${destinationLabel}</td></tr>
                        <tr><td style="padding: 4px 0; color: #64748b;">Arrival Time:</td><td style="padding: 4px 0; color: #1e293b; font-weight: 600;">${genTimeStr}</td></tr>
                    </table>
                </div>
            </div>
            <div style="border-top: 2px solid #e2e8f0; margin-top: 24px; padding-top: 12px; font-size: 11px; color: #94a3b8; text-align: center;">
                This is an automated notification from the Campus Navigation System.
            </div>
        </div>`;

    // ── Emergency Alert ──────────────────────────────────────────────────────
    } else if (eventType === 'emergency_alert') {
        bodyHTML = `
        <div style="font-family: 'Inter', -apple-system, sans-serif; line-height: 1.6; color: #1e293b; max-width: 600px; margin: 0 auto; border: 1px solid #fecaca; padding: 24px; border-radius: 12px; background-color: #ffffff;">
            <div style="background: linear-gradient(135deg, #ef4444, #dc2626); padding: 16px; border-radius: 8px; margin-bottom: 20px; text-align: center;">
                <h2 style="color: #ffffff; margin: 0; font-size: 20px; font-weight: bold; letter-spacing: 0.05em;">🚨 CAMPUS EMERGENCY ALERT</h2>
            </div>
            <p style="font-size: 15px; margin-top: 0;">Dear <strong>${hostName}</strong>,</p>
            <p style="font-size: 15px; color: #991b1b; font-weight: 600; margin-bottom: 24px; padding: 12px; background-color: #fef2f2; border-left: 4px solid #ef4444; border-radius: 4px;">
                An emergency has been detected involving your visitor <strong>${visitorName}</strong>.<br/><br/>
                Please take the necessary action immediately.
            </p>
            <div style="border: 1px solid #fecaca; border-radius: 8px; margin-bottom: 24px; overflow: hidden;">
                <div style="background-color: #fef2f2; padding: 10px 16px; border-bottom: 1px solid #fecaca;">
                    <h3 style="margin: 0; font-size: 12px; font-weight: 700; color: #dc2626; text-transform: uppercase; letter-spacing: 0.05em;">Emergency Information</h3>
                </div>
                <div style="padding: 12px 16px;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                        <tr><td style="padding: 4px 0; color: #64748b; width: 40%;">Visitor Name:</td><td style="padding: 4px 0; color: #1e293b; font-weight: 600;">${visitorName}</td></tr>
                        <tr><td style="padding: 4px 0; color: #64748b;">Current Location:</td><td style="padding: 4px 0; color: #1e293b; font-weight: 600;">${startLabel}</td></tr>
                        <tr><td style="padding: 4px 0; color: #64748b;">Destination:</td><td style="padding: 4px 0; color: #1e293b; font-weight: 600;">${destinationLabel}</td></tr>
                        <tr><td style="padding: 4px 0; color: #64748b;">Alert Time:</td><td style="padding: 4px 0; color: #dc2626; font-weight: 700;">${genTimeStr}</td></tr>
                    </table>
                </div>
            </div>
            <div style="border-top: 2px solid #e2e8f0; margin-top: 24px; padding-top: 12px; font-size: 11px; color: #94a3b8; text-align: center;">
                This is an automated emergency notification from the Campus Navigation System.
            </div>
        </div>`;

    // ── Appointment Routing (Host) ────────────────────────────────────────────
    } else {
        bodyHTML = `
        <div style="font-family: 'Inter', -apple-system, sans-serif; line-height: 1.6; color: #1e293b; max-width: 600px; margin: 0 auto; border: 1px solid #e2e8f0; padding: 24px; border-radius: 12px; background-color: #ffffff;">
            <div style="background: linear-gradient(135deg, #4f46e5, #3b82f6); padding: 16px; border-radius: 8px; margin-bottom: 20px; text-align: center;">
                <h2 style="color: #ffffff; margin: 0; font-size: 20px; font-weight: bold; letter-spacing: 0.05em;">🔔 CAMPUS HOST NOTIFICATION</h2>
            </div>
            <p style="font-size: 15px; margin-top: 0;">Dear <strong>${hostName}</strong>,</p>
            <p style="font-size: 15px; color: #334155; font-weight: 500; margin-bottom: 24px;">
                Your visitor <strong>${visitorName}</strong> has arrived at <strong>${startLabel}</strong> and is currently navigating to <strong>${destinationLabel}</strong>.
            </p>
            <div style="border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 18px; overflow: hidden;">
                <div style="background-color: #f8fafc; padding: 10px 16px; border-bottom: 1px solid #e2e8f0;">
                    <h3 style="margin: 0; font-size: 12px; font-weight: 700; color: #4f46e5; text-transform: uppercase; letter-spacing: 0.05em;">Visitor Information</h3>
                </div>
                <div style="padding: 12px 16px;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                        <tr><td style="padding: 4px 0; color: #64748b; width: 40%;">Visitor Name:</td><td style="padding: 4px 0; color: #1e293b; font-weight: 600;">${visitorName}</td></tr>
                        <tr><td style="padding: 4px 0; color: #64748b;">Visitor Role:</td><td style="padding: 4px 0; color: #1e293b; font-weight: 600;">${visitorRole || 'Visitor'}</td></tr>
                        <tr><td style="padding: 4px 0; color: #64748b;">Event Type:</td><td style="padding: 4px 0; color: #1e293b; font-weight: 600;">${formattedEventType}</td></tr>
                    </table>
                </div>
            </div>
            <div style="border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 18px; overflow: hidden;">
                <div style="background-color: #f8fafc; padding: 10px 16px; border-bottom: 1px solid #e2e8f0;">
                    <h3 style="margin: 0; font-size: 12px; font-weight: 700; color: #4f46e5; text-transform: uppercase; letter-spacing: 0.05em;">Journey Details</h3>
                </div>
                <div style="padding: 12px 16px;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                        <tr><td style="padding: 4px 0; color: #64748b; width: 40%;">Current Location:</td><td style="padding: 4px 0; color: #1e293b; font-weight: 600;">${startLabel}</td></tr>
                        <tr><td style="padding: 4px 0; color: #64748b;">Destination:</td><td style="padding: 4px 0; color: #1e293b; font-weight: 600;">${destinationLabel}</td></tr>
                    </table>
                </div>
            </div>
            <div style="border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 24px; overflow: hidden;">
                <div style="background-color: #f8fafc; padding: 10px 16px; border-bottom: 1px solid #e2e8f0;">
                    <h3 style="margin: 0; font-size: 12px; font-weight: 700; color: #4f46e5; text-transform: uppercase; letter-spacing: 0.05em;">Route Summary</h3>
                </div>
                <div style="padding: 12px 16px;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                        <tr><td style="padding: 4px 0; color: #64748b; width: 40%;">Estimated Walking Time:</td><td style="padding: 4px 0; color: #0d9488; font-weight: 700;">${walkingTimeLabel}</td></tr>
                        <tr><td style="padding: 4px 0; color: #64748b;">Total Distance:</td><td style="padding: 4px 0; color: #0d9488; font-weight: 700;">${distanceStr}</td></tr>
                    </table>
                </div>
            </div>
            <div style="font-size: 12px; color: #64748b; padding-top: 14px; border-top: 1px solid #e2e8f0;">
                <strong>Generated Time:</strong> ${genTimeStr}
            </div>
        </div>`;
    }

    // Host email — no attachments, no visualization
    return sendEmailWithRetry(transporter, toEmail, subject, bodyHTML, [], 3);
}

// ─────────────────────────────────────────────────────────────────────────────
// VISITOR EMAIL
// ─────────────────────────────────────────────────────────────────────────────

/**
 * Draft and send the Visitor email.
 * For appointment_routing, route visualization images are embedded inline via CID.
 *
 * @param {Object} opts
 * @param {string} opts.toEmail
 * @param {string} opts.visitorName
 * @param {string} opts.destinationNodeLabel
 * @param {string} opts.destBuilding
 * @param {number} opts.destFloor
 * @param {string} opts.startNodeLabel
 * @param {string} opts.startBuilding
 * @param {number} opts.startFloor
 * @param {number} opts.walkingTimeSeconds
 * @param {number} opts.totalDistanceMetres
 * @param {Array}  opts.instructions
 * @param {string} opts.eventType
 * @param {Array}  [opts.routeVisualizations=[]]  - CID image descriptors (visitor only).
 * @param {string} [opts.emailDeliveryMode]       - "ethereal" | "smtp"
 */
async function sendVisitorEmail({
    toEmail, visitorName, destinationNodeLabel, destBuilding, destFloor,
    startNodeLabel, startBuilding, startFloor, walkingTimeSeconds,
    totalDistanceMetres, instructions, eventType,
    routeVisualizations = [],
    emailDeliveryMode
}) {
    const transporter      = await getTransporter(emailDeliveryMode);
    const destinationLabel = formatLocationDisplay(destinationNodeLabel);
    const startLabel       = formatLocationDisplay(startNodeLabel);
    const startBldgName    = formatBuildingName(startBuilding);
    const destBldgName     = formatBuildingName(destBuilding);
    const startFloorLevel  = formatFloorLevel(startFloor);
    const destFloorLevel   = formatFloorLevel(destFloor);
    const walkingTimeLabel = formatWalkingTime(walkingTimeSeconds);
    const distanceStr      = `${Number(totalDistanceMetres || 0).toFixed(2)} metres`;

    // Build turn-by-turn directions HTML
    let instructionsHTML = '<div style="margin-top: 10px;">';
    if (instructions && instructions.length > 0) {
        instructionsHTML += instructions.map(step => {
            const icons = {
                start:      '🟢',
                walk:       '⬆️',
                turn:       step.action === 'left' ? '↰' : '↱',
                transition: step.action === 'elevator' ? '🛗' : step.action === 'stairwell' ? '🪜' : '🚪',
                arrive:     '🏁'
            };
            const stepIcon = icons[step.type] || '•';
            return `
                <div style="display: flex; gap: 12px; margin-bottom: 8px; padding: 12px; background-color: #f8fafc; border-radius: 8px; border: 1px solid #e2e8f0; align-items: center;">
                    <span style="font-size: 18px; line-height: 1;">${stepIcon}</span>
                    <div style="font-size: 13.5px; color: #334155; font-weight: 500;">
                        ${step.description}
                        ${step.type === 'walk' ? `<span style="font-size: 11px; color: #64748b; font-weight: normal; margin-left: 6px;">(${step.distance_m}m)</span>` : ''}
                    </div>
                </div>`;
        }).join('');
    } else {
        instructionsHTML += '<p style="font-style: italic; font-size: 13px; color: #64748b;">No directions available.</p>';
    }
    instructionsHTML += '</div>';

    const genTimeStr = new Date().toLocaleString('en-US', { timeZoneName: 'short' });
    let subject = '';
    let bodyHTML = '';
    let attachments = [];

    // ── Visitor Arrival ──────────────────────────────────────────────────────
    if (eventType === 'visitor_arrival') {
        subject = `✅ Destination Reached: ${destinationLabel}`;
        bodyHTML = `
        <div style="font-family: 'Inter', -apple-system, sans-serif; line-height: 1.6; color: #1e293b; max-width: 600px; margin: 0 auto; border: 1px solid #e2e8f0; padding: 24px; border-radius: 12px; background-color: #ffffff;">
            <div style="background: linear-gradient(135deg, #10b981, #059669); padding: 16px; border-radius: 8px; margin-bottom: 20px; text-align: center;">
                <h2 style="color: #ffffff; margin: 0; font-size: 20px; font-weight: bold; letter-spacing: 0.05em;">✅ DESTINATION REACHED</h2>
            </div>
            <p style="font-size: 15px; margin-top: 0;">Dear <strong>${visitorName || 'Visitor'}</strong>,</p>
            <p style="font-size: 15px; color: #334155; margin-bottom: 24px;">
                You have successfully arrived at <strong>${destinationLabel}</strong>.<br/><br/>
                Thank you for using the Campus Navigation System.
            </p>
            <div style="border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 24px; overflow: hidden;">
                <div style="background-color: #f8fafc; padding: 10px 16px; border-bottom: 1px solid #e2e8f0;">
                    <h3 style="margin: 0; font-size: 12px; font-weight: 700; color: #10b981; text-transform: uppercase; letter-spacing: 0.05em;">Arrival Details</h3>
                </div>
                <div style="padding: 12px 16px;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                        <tr><td style="padding: 4px 0; color: #64748b; width: 40%;">Arrival Time:</td><td style="padding: 4px 0; color: #1e293b; font-weight: 600;">${genTimeStr}</td></tr>
                    </table>
                </div>
            </div>
        </div>`;

    // ── Emergency Alert ──────────────────────────────────────────────────────
    } else if (eventType === 'emergency_alert') {
        subject = `🚨 Emergency Alert: Action Required`;
        bodyHTML = `
        <div style="font-family: 'Inter', -apple-system, sans-serif; line-height: 1.6; color: #1e293b; max-width: 600px; margin: 0 auto; border: 1px solid #fecaca; padding: 24px; border-radius: 12px; background-color: #ffffff;">
            <div style="background: linear-gradient(135deg, #ef4444, #dc2626); padding: 16px; border-radius: 8px; margin-bottom: 20px; text-align: center;">
                <h2 style="color: #ffffff; margin: 0; font-size: 20px; font-weight: bold; letter-spacing: 0.05em;">🚨 EMERGENCY ALERT</h2>
            </div>
            <p style="font-size: 15px; margin-top: 0;">Dear <strong>${visitorName || 'Visitor'}</strong>,</p>
            <p style="font-size: 15px; color: #991b1b; font-weight: 600; margin-bottom: 24px; padding: 12px; background-color: #fef2f2; border-left: 4px solid #ef4444; border-radius: 4px;">
                An emergency has been reported while you are navigating through the campus.<br/><br/>
                Please remain calm and follow the emergency instructions provided by campus authorities.
            </p>
            <div style="border: 1px solid #fecaca; border-radius: 8px; margin-bottom: 24px; overflow: hidden;">
                <div style="background-color: #fef2f2; padding: 10px 16px; border-bottom: 1px solid #fecaca;">
                    <h3 style="margin: 0; font-size: 12px; font-weight: 700; color: #dc2626; text-transform: uppercase; letter-spacing: 0.05em;">Emergency Information</h3>
                </div>
                <div style="padding: 12px 16px;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                        <tr><td style="padding: 4px 0; color: #64748b; width: 40%;">Current Location:</td><td style="padding: 4px 0; color: #1e293b; font-weight: 600;">${startLabel}</td></tr>
                        <tr><td style="padding: 4px 0; color: #dc2626; font-weight: 700;">Alert Time:</td><td style="padding: 4px 0; color: #dc2626; font-weight: 700;">${genTimeStr}</td></tr>
                    </table>
                </div>
            </div>
            <div style="border-top: 2px solid #e2e8f0; margin-top: 24px; padding-top: 12px; font-size: 11px; color: #94a3b8; text-align: center;">
                This is an automated emergency notification from the Campus Navigation System.
            </div>
        </div>`;

    // ── Appointment Routing (Visitor) ─────────────────────────────────────────
    } else {
        subject = `🗺️ Campus Navigation Guide: Route to ${destinationLabel}`;
        attachments = buildAttachments(routeVisualizations);

        // Build combined per-floor sections (visualization + directions grouped by floor)
        const perFloorHTML = buildPerFloorSectionsHTML(routeVisualizations, instructions);

        bodyHTML = `
        <div style="font-family: 'Inter', -apple-system, sans-serif; line-height: 1.6; color: #1e293b; max-width: 600px; margin: 0 auto; border: 1px solid #e2e8f0; padding: 24px; border-radius: 12px; background-color: #ffffff;">
            <div style="background: linear-gradient(135deg, #4f46e5, #06b6d4); padding: 16px; border-radius: 8px; margin-bottom: 20px; text-align: center;">
                <h2 style="color: #ffffff; margin: 0; font-size: 20px; font-weight: bold; letter-spacing: 0.05em;">🗺️ CAMPUS NAVIGATION GUIDE</h2>
            </div>

            <p style="font-size: 15px; margin-top: 0;">Dear <strong>${visitorName || 'Visitor'}</strong>,</p>
            <p style="font-size: 15px; color: #334155; margin-bottom: 24px;">
                Your route from <strong>${startLabel}</strong> to <strong>${destinationLabel}</strong> has been generated successfully.
            </p>

            <!-- Journey Details Card -->
            <div style="border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 18px; overflow: hidden;">
                <div style="background-color: #f8fafc; padding: 10px 16px; border-bottom: 1px solid #e2e8f0;">
                    <h3 style="margin: 0; font-size: 12px; font-weight: 700; color: #4f46e5; text-transform: uppercase; letter-spacing: 0.05em;">Journey Details</h3>
                </div>
                <div style="padding: 12px 16px;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                        <tr><td style="padding: 4px 0; color: #64748b; width: 40%;">Current Location:</td><td style="padding: 4px 0; color: #1e293b; font-weight: 600;">${startLabel}</td></tr>
                        <tr><td style="padding: 4px 0; color: #64748b;">Current Building:</td><td style="padding: 4px 0; color: #1e293b; font-weight: 600;">${startBldgName} (${startFloorLevel})</td></tr>
                        <tr><td style="padding: 4px 0; color: #64748b;">Destination:</td><td style="padding: 4px 0; color: #1e293b; font-weight: 600;">${destinationLabel}</td></tr>
                        <tr><td style="padding: 4px 0; color: #64748b;">Destination Building:</td><td style="padding: 4px 0; color: #1e293b; font-weight: 600;">${destBldgName} (${destFloorLevel})</td></tr>
                    </table>
                </div>
            </div>

            <!-- Route Summary Card -->
            <div style="border: 1px solid #e2e8f0; border-radius: 8px; margin-bottom: 18px; overflow: hidden;">
                <div style="background-color: #f8fafc; padding: 10px 16px; border-bottom: 1px solid #e2e8f0;">
                    <h3 style="margin: 0; font-size: 12px; font-weight: 700; color: #4f46e5; text-transform: uppercase; letter-spacing: 0.05em;">Route Summary</h3>
                </div>
                <div style="padding: 12px 16px;">
                    <table style="width: 100%; border-collapse: collapse; font-size: 14px;">
                        <tr><td style="padding: 4px 0; color: #64748b; width: 40%;">Estimated Walking Time:</td><td style="padding: 4px 0; color: #0d9488; font-weight: 700;">${walkingTimeLabel}</td></tr>
                        <tr><td style="padding: 4px 0; color: #64748b;">Total Distance:</td><td style="padding: 4px 0; color: #0d9488; font-weight: 700;">${distanceStr}</td></tr>
                    </table>
                </div>
            </div>

            <!-- Per-Floor Route Segments (Visualization + Directions) -->
            ${perFloorHTML}

            <div style="border-top: 2px solid #e2e8f0; margin-top: 24px; padding-top: 12px; font-size: 11px; color: #94a3b8; text-align: center;">
                This is an automated notification from the Campus Navigation System.
            </div>
        </div>`;
    }

    return sendEmailWithRetry(transporter, toEmail, subject, bodyHTML, attachments, 3);
}

// ─────────────────────────────────────────────────────────────────────────────
// EXPORTS
// ─────────────────────────────────────────────────────────────────────────────

module.exports = {
    sendHostEmail,
    sendVisitorEmail
};
