/**
 * @file cleanupScheduler.js
 * @description Automatic Background Cleanup Scheduler for Email Visualisation Files and Expired Kiosk Sessions.
 *
 * Safely purges generated route visualization PNGs stored under backend/uploads/visualisations
 * that are older than the configured retention threshold (default: 24 hours), and expired kiosk sessions.
 */

'use strict';

const fs = require('fs');
const path = require('path');

const VIS_DIR = path.resolve(__dirname, '..', 'uploads', 'visualisations');

/**
 * Ensures the target visualisations directory exists.
 */
function ensureVisDir() {
    if (!fs.existsSync(VIS_DIR)) {
        fs.mkdirSync(VIS_DIR, { recursive: true });
    }
}

/**
 * Execute a single cleanup sweep of expired visualisation images.
 *
 * @param {number} [customRetentionHours] - Optional override for retention hours.
 * @returns {Promise<{ scanned: number, deleted: number, errors: number }>}
 */
async function runCleanup(customRetentionHours) {
    ensureVisDir();

    const retentionHours = customRetentionHours !== undefined
        ? Number(customRetentionHours)
        : parseInt(process.env.VISUALISATION_RETENTION_HOURS || '24', 10);

    const retentionMs = retentionHours * 60 * 60 * 1000;
    const cutoff = Date.now() - retentionMs;

    let scanned = 0;
    let deleted = 0;
    let errors = 0;

    try {
        const files = fs.readdirSync(VIS_DIR);

        for (const file of files) {
            // Safety: strictly only touch .png files
            if (!file.toLowerCase().endsWith('.png')) {
                continue;
            }

            const filePath = path.join(VIS_DIR, file);

            // Safety check: ensure path is strictly contained within VIS_DIR
            const resolvedPath = path.resolve(filePath);
            if (!resolvedPath.startsWith(VIS_DIR)) {
                console.warn(`[CleanupScheduler] Skipped suspicious path outside target directory: ${resolvedPath}`);
                continue;
            }

            try {
                const stat = fs.statSync(filePath);

                if (!stat.isFile()) {
                    continue;
                }

                scanned++;

                // If file modification timestamp is older than 24h cutoff
                if (stat.mtimeMs < cutoff) {
                    const ageHours = ((Date.now() - stat.mtimeMs) / (1000 * 60 * 60)).toFixed(1);
                    fs.unlinkSync(filePath);
                    deleted++;
                    console.log(`[CleanupScheduler] Deleted expired visualisation: ${file} (age: ${ageHours}h)`);
                }
            } catch (fileErr) {
                errors++;
                console.error(`[CleanupScheduler] Error inspecting/deleting file ${file}:`, fileErr.message);
            }
        }

        if (deleted > 0 || errors > 0) {
            console.log(`[CleanupScheduler] Sweep completed: scanned ${scanned} file(s), deleted ${deleted} expired file(s), ${errors} error(s).`);
        }
    } catch (dirErr) {
        console.error('[CleanupScheduler] Failed to read visualisations directory:', dirErr.message);
    }

    // Also purge expired mobile navigation sessions
    try {
        const kioskSessionService = require('../services/kioskSessionService');
        await kioskSessionService.cleanupExpiredSessions();
    } catch (sessionErr) {
        console.warn('[CleanupScheduler] Session cleanup warning:', sessionErr.message);
    }

    return { scanned, deleted, errors };
}

/**
 * Starts the continuous background scheduler.
 * Runs an initial sweep on startup and repeats on an interval.
 *
 * @param {Object} [options]
 * @param {number} [options.intervalMinutes] - Interval between cleanup runs (default: 60 minutes).
 * @param {number} [options.retentionHours]  - File age threshold in hours (default: 24 hours).
 * @returns {{ stop: Function, runNow: Function }}
 */
function startCleanupScheduler(options = {}) {
    ensureVisDir();

    const intervalMinutes = options.intervalMinutes || parseInt(process.env.CLEANUP_INTERVAL_MINUTES || '60', 10);
    const intervalMs = Math.max(intervalMinutes, 1) * 60 * 1000;

    console.log(`[CleanupScheduler] Initializing background cleanup scheduler (Interval: ${intervalMinutes}m, Retention: ${options.retentionHours || process.env.VISUALISATION_RETENTION_HOURS || 24}h).`);

    // Run initial sweep asynchronously after a brief 3-second startup grace period
    const initialTimeout = setTimeout(() => {
        runCleanup(options.retentionHours).catch(err => {
            console.error('[CleanupScheduler] Initial sweep error:', err.message);
        });
    }, 3000);
    initialTimeout.unref();

    // Recurring interval
    const intervalId = setInterval(() => {
        runCleanup(options.retentionHours).catch(err => {
            console.error('[CleanupScheduler] Scheduled sweep error:', err.message);
        });
    }, intervalMs);
    intervalId.unref();

    return {
        stop: () => {
            clearTimeout(initialTimeout);
            clearInterval(intervalId);
            console.log('[CleanupScheduler] Background cleanup scheduler stopped.');
        },
        runNow: (customHours) => runCleanup(customHours)
    };
}

module.exports = {
    runCleanup,
    startCleanupScheduler,
    VIS_DIR
};
