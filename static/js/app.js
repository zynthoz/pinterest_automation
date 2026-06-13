/* ═══════════════════════════════════════════════════════════════
   Pinterest Automation — Workspace JavaScript
   Orchestrates visual pipelines, dynamic ingestion and drawers
   ═══════════════════════════════════════════════════════════════ */

// ─── Configuration ─────────────────────────────────────────────
const POLL_INTERVAL = 5000; // 5 seconds
let pollTimer = null;
let isSubmitting = false;

// ─── Tab Switching (Single / Bulk) ─────────────────────────────
function switchTab(mode) {
    const singleTab = document.getElementById('tab-single');
    const bulkTab = document.getElementById('tab-bulk');
    const singleInput = document.getElementById('input-single');
    const bulkInput = document.getElementById('input-bulk');

    if (!singleTab) return; // not on dashboard page

    if (mode === 'single') {
        singleTab.classList.add('active');
        bulkTab.classList.remove('active');
        singleInput.classList.remove('hidden');
        bulkInput.classList.add('hidden');
    } else {
        bulkTab.classList.add('active');
        singleTab.classList.remove('active');
        bulkInput.classList.remove('hidden');
        singleInput.classList.add('hidden');
    }
}

// ─── URL Submission ────────────────────────────────────────────
async function submitSingle() {
    if (isSubmitting) return;

    const input = document.getElementById('single-url-input');
    const url = input.value.trim();

    if (!url) {
        showToast('Please enter an Amazon URL', 'warning');
        input.focus();
        return;
    }

    if (!isAmazonUrl(url)) {
        showToast('That doesn\'t look like an Amazon URL', 'error');
        return;
    }

    setButtonLoading('btn-add-single', 'btn-add-text', 'btn-add-spinner', true);
    isSubmitting = true;

    try {
        const resp = await fetch('/api/products', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ affiliate_url: url }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || 'Failed to create job');
        }

        const data = await resp.json();
        showToast(`Job #${data.id} created! Processing...`, 'success');
        input.value = '';

        await refreshJobs();
    } catch (e) {
        showToast(e.message, 'error');
    } finally {
        setButtonLoading('btn-add-single', 'btn-add-text', 'btn-add-spinner', false);
        isSubmitting = false;
    }
}

async function submitBulk() {
    if (isSubmitting) return;

    const textarea = document.getElementById('bulk-url-input');
    const lines = textarea.value.split('\n').map(l => l.trim()).filter(l => l.length > 0);

    if (lines.length === 0) {
        showToast('Please paste at least one URL', 'warning');
        return;
    }

    const validUrls = lines.filter(isAmazonUrl);
    if (validUrls.length === 0) {
        showToast('No valid Amazon URLs found', 'error');
        return;
    }

    setButtonLoading('btn-add-bulk', 'btn-bulk-text', 'btn-bulk-spinner', true);
    isSubmitting = true;

    try {
        const resp = await fetch('/api/products/bulk', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ affiliate_urls: validUrls }),
        });

        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || 'Bulk submission failed');
        }

        const data = await resp.json();
        showToast(`${data.length} jobs queued successfully!`, 'success');
        textarea.value = '';
        updateBulkCount();

        await refreshJobs();
    } catch (e) {
        showToast(e.message, 'error');
    } finally {
        setButtonLoading('btn-add-bulk', 'btn-bulk-text', 'btn-bulk-spinner', false);
        isSubmitting = false;
    }
}

function isAmazonUrl(url) {
    const lower = url.toLowerCase();
    return ['amazon.com', 'amazon.co.uk', 'amazon.ca', 'amazon.de', 'amzn.to', 'a.co'].some(
        d => lower.includes(d)
    );
}

// Bulk URL counter
function updateBulkCount() {
    const textarea = document.getElementById('bulk-url-input');
    const counter = document.getElementById('bulk-count');
    if (!textarea || !counter) return;

    const lines = textarea.value.split('\n').filter(l => l.trim().length > 0);
    const valid = lines.filter(isAmazonUrl);
    counter.textContent = `${valid.length} URL${valid.length !== 1 ? 's' : ''} detected`;
}

// Collapsible Guide Panel
function toggleGuide() {
    const panel = document.getElementById('guide-panel');
    if (!panel) return;
    const isCollapsed = panel.classList.toggle('collapsed');
    localStorage.setItem('pinbot_guide_collapsed', isCollapsed ? 'true' : 'false');
}

// Listen for textarea changes
document.addEventListener('DOMContentLoaded', () => {
    // Restore collapsible guide panel state
    const guidePanel = document.getElementById('guide-panel');
    if (guidePanel) {
        const collapsed = localStorage.getItem('pinbot_guide_collapsed');
        if (collapsed === 'true') {
            guidePanel.classList.add('collapsed');
        }
    }

    const bulkInput = document.getElementById('bulk-url-input');
    if (bulkInput) {
        bulkInput.addEventListener('input', updateBulkCount);
    }

    // Enter key on single input
    const singleInput = document.getElementById('single-url-input');
    if (singleInput) {
        singleInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                submitSingle();
            }
        });

        // Instant visual validation for Amazon URLs
        singleInput.addEventListener('input', () => {
            const btn = document.getElementById('btn-add-single');
            const url = singleInput.value;
            if (url.trim() && !isAmazonUrl(url)) {
                singleInput.classList.add('input-error');
                if (btn) btn.disabled = true;
            } else {
                singleInput.classList.remove('input-error');
                if (btn) btn.disabled = false;
            }
        });
    }
});

// ─── Job Polling ───────────────────────────────────────────────
function startJobPolling() {
    refreshJobs();
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(refreshJobs, POLL_INTERVAL);
}

async function refreshJobs() {
    try {
        const resp = await fetch('/api/jobs?per_page=20');
        if (!resp.ok) return;

        const data = await resp.json();
        window.latestJobs = data.jobs; // Cache for immediate filter re-renders
        updateJobsList(data.jobs);
        updateStats(data.jobs, data.total);
    } catch (e) {
        console.debug('Job polling error:', e);
    }
}

function updateJobsList(jobs) {
    const container = document.getElementById('jobs-list');
    if (!container) return;

    if (!jobs || jobs.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">
                    <svg class="icon icon-lg" viewBox="0 0 24 24"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"></polyline></svg>
                </div>
                <div class="empty-state-text">No active runs or recent pipelines found. Paste an Amazon affiliate link in the Link Hub to start!</div>
            </div>
        `;
        return;
    }

    const searchInput = document.getElementById('jobs-search-input');
    const query = searchInput ? searchInput.value.trim().toLowerCase() : '';

    const filteredJobs = query
        ? jobs.filter(job => {
            const title = (job.product_title || '').toLowerCase();
            const url = (job.affiliate_url || '').toLowerCase();
            const status = (job.status || '').toLowerCase();
            const step = (job.current_step || '').toLowerCase();
            const id = String(job.id);
            return title.includes(query) || url.includes(query) || status.includes(query) || step.includes(query) || id.includes(query);
        })
        : jobs;

    if (filteredJobs.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">
                    <svg class="icon icon-lg" viewBox="0 0 24 24"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
                </div>
                <div class="empty-state-text">No runs match your search query.</div>
            </div>
        `;
        return;
    }

    container.innerHTML = filteredJobs.map(job => renderJobCard(job)).join('');
}

// ─── Real-Time Visual Pipeline Calculation ───────────────────
function getPipelineStepsState(status, currentStep, isFailed) {
    const steps = {
        scrape: 'queued', // completed, active, failed, queued
        download: 'queued',
        copy: 'queued',
        publish: 'queued',
        progress: 0
    };

    if (status === 'completed') {
        steps.scrape = 'completed';
        steps.download = 'completed';
        steps.copy = 'completed';
        steps.publish = 'completed';
        steps.progress = 100;
        return steps;
    }

    const stepWords = (currentStep || '').toLowerCase();

    // Map stages based on current step or progress
    let stage = 0; // 0 = queued/none, 1 = scrape, 2 = download, 3 = copy, 4 = publish
    if (stepWords.includes('search') || stepWords.includes('extract') || stepWords.includes('tiktok')) {
        stage = 1;
    } else if (stepWords.includes('download')) {
        stage = 2;
    } else if (stepWords.includes('generating') || stepWords.includes('gemini') || stepWords.includes('copy')) {
        stage = 3;
    } else if (stepWords.includes('publish') || stepWords.includes('schedule') || stepWords.includes('pinterest')) {
        stage = 4;
    }

    if (isFailed) {
        if (stage === 1 || stage === 0) {
            steps.scrape = 'failed';
        } else if (stage === 2) {
            steps.scrape = 'completed';
            steps.download = 'failed';
        } else if (stage === 3) {
            steps.scrape = 'completed';
            steps.download = 'completed';
            steps.copy = 'failed';
        } else if (stage === 4) {
            steps.scrape = 'completed';
            steps.download = 'completed';
            steps.copy = 'completed';
            steps.publish = 'failed';
        }
        steps.progress = Math.max(0, (stage - 1) * 33.3);
    } else {
        if (stage === 0) {
            if (status === 'queued') {
                steps.progress = 0;
            } else {
                steps.scrape = 'active';
                steps.progress = 0;
            }
        } else if (stage === 1) {
            steps.scrape = 'active';
            steps.progress = 0;
        } else if (stage === 2) {
            steps.scrape = 'completed';
            steps.download = 'active';
            steps.progress = 33.3;
        } else if (stage === 3) {
            steps.scrape = 'completed';
            steps.download = 'completed';
            steps.copy = 'active';
            steps.progress = 66.6;
        } else if (stage === 4) {
            steps.scrape = 'completed';
            steps.download = 'completed';
            steps.copy = 'completed';
            steps.publish = 'active';
            steps.progress = 100;
        }
    }

    return steps;
}

function renderJobCard(job) {
    const productImg = job.product_image
        ? `<img class="job-product-img" src="${escapeHtml(job.product_image)}" alt="Product">`
        : `<div class="job-product-img" style="display:flex;align-items:center;justify-content:center;font-size:1.3rem;background:var(--bg-sidebar);">📦</div>`;

    const title = escapeHtml(job.product_title || 'Processing...');
    const url = escapeHtml(job.affiliate_url);
    const badge = renderBadge(job.status);
    const retryBtn = (job.status === 'failed' || job.status === 'completed')
        ? `<div class="job-actions" style="margin-top: 2px; display: flex; justify-content: flex-end;">
               <button class="btn btn-secondary btn-sm" onclick="retryJob(${job.id})">
                   <svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M21.5 2v6h-6M21.34 15.57a10 10 0 1 1-.57-8.38l5.67-5.67"/></svg>
                   ${job.status === 'completed' ? 'Re-upload' : 'Retry Run'}
               </button>
           </div>`
        : '';

    const isFailed = job.status === 'failed';
    const pipeline = getPipelineStepsState(job.status, job.current_step, isFailed);

    const errorBanner = job.error
        ? `<div class="job-error-banner" id="job-error-${job.id}">
               <svg class="icon icon-sm" viewBox="0 0 24 24" style="flex-shrink:0;"><circle cx="12" cy="12" r="10"></circle><line x1="12" y1="8" x2="12" y2="12"></line><line x1="12" y1="16" x2="12.01" y2="16"></line></svg>
               <span>Error</span>
               <button class="btn-copy-error" onclick="copyError(this)" title="Copy error details">
                   <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"></path></svg>
               </button>
               <span class="error-tooltip">${escapeHtml(job.error)}</span>
           </div>`
        : '';

    const pipelineHtml = job.status === 'completed'
        ? ''
        : `
            <!-- Real-time pipeline visual steps -->
            <div class="pipeline">
                <div class="pipeline-line">
                    <div class="pipeline-line-progress" style="width: ${pipeline.progress}%" id="job-progress-line-${job.id}"></div>
                </div>
                <div class="pipeline-step ${pipeline.scrape}" id="job-step-scrape-${job.id}">
                    <div class="pipeline-dot" title="Scrape TikTok">
                        <svg class="icon icon-sm" viewBox="0 0 24 24"><circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line></svg>
                    </div>
                    <div class="pipeline-label">Scrape TikTok</div>
                </div>
                <div class="pipeline-step ${pipeline.download}" id="job-step-download-${job.id}">
                    <div class="pipeline-dot" title="Download Video">
                        <svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
                    </div>
                    <div class="pipeline-label">Download Video</div>
                </div>
                <div class="pipeline-step ${pipeline.copy}" id="job-step-copy-${job.id}">
                    <div class="pipeline-dot" title="AI Copy Generation">
                        <svg class="icon icon-sm" viewBox="0 0 24 24"><path d="m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275Z"/></svg>
                    </div>
                    <div class="pipeline-label">AI Copy</div>
                </div>
                <div class="pipeline-step ${pipeline.publish}" id="job-step-publish-${job.id}">
                    <div class="pipeline-dot" title="Publish or Schedule">
                        <svg class="icon icon-sm" viewBox="0 0 24 24"><line x1="22" y1="2" x2="11" y2="13"></line><polygon points="22 2 15 22 11 13 2 9 22 2"></polygon></svg>
                    </div>
                    <div class="pipeline-label">Publish/Schedule</div>
                </div>
            </div>
        `;

    const deleteBtn = `
        <button class="btn-delete-job" onclick="deleteJob(${job.id})" title="${job.status === 'completed' || job.status === 'failed' ? 'Delete Run' : 'Cancel Run'}">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
        </button>
    `;

    return `
        <div class="job-card" id="job-${job.id}" data-status="${job.status}">
            <div class="job-card-header">
                ${productImg}
                <div class="job-info">
                    <div class="job-title" title="${title}">${title}</div>
                    <div class="job-meta">
                        <div class="job-meta-item">
                            <svg class="icon icon-sm" viewBox="0 0 24 24"><path d="M10 13a5 5 0 0 0 7.54.54l3-3a5 5 0 0 0-7.07-7.07l-1.72 1.71"></path><path d="M14 11a5 5 0 0 0-7.54-.54l-3 3a5 5 0 0 0 7.07 7.07l1.71-1.71"></path></svg>
                            <a href="${url}" target="_blank" class="truncate">${url}</a>
                        </div>
                        <div class="job-meta-item">
                            <span>#${job.id}</span>
                        </div>
                    </div>
                </div>
                <div class="job-status-container">
                    <div class="job-status">${badge}</div>
                    ${deleteBtn}
                </div>
            </div>

            ${pipelineHtml}

            <!-- Live Step Status (Logs) -->
            <div class="job-status-update" id="job-status-update-${job.id}">
                <span class="status-dot"></span>
                <span class="status-text" id="job-status-text-${job.id}">${escapeHtml(job.current_step || 'Waiting in queue...')}</span>
            </div>

            ${errorBanner}
            ${retryBtn}
        </div>
    `;
}

function renderBadge(status) {
    const activeStatuses = ['extracting', 'searching', 'downloading', 'generating', 'scheduling', 'publishing'];

    if (status === 'queued') {
        return '<span class="badge badge-queued">Queued</span>';
    } else if (activeStatuses.includes(status)) {
        return `<span class="badge badge-active">${capitalize(status)}</span>`;
    } else if (status === 'completed') {
        return '<span class="badge badge-completed">Completed</span>';
    } else if (status === 'failed') {
        return '<span class="badge badge-failed">Failed</span>';
    } else {
        return `<span class="badge badge-draft">${status}</span>`;
    }
}

function updateStats(jobs, total) {
    const active = jobs.filter(j => !['completed', 'failed'].includes(j.status)).length;
    const completed = jobs.filter(j => j.status === 'completed').length;
    const failed = jobs.filter(j => j.status === 'failed').length;

    setStatIfExists('stat-active', active);
    setStatIfExists('stat-completed', completed);
    setStatIfExists('stat-failed', failed);
    if (total !== undefined) {
        setStatIfExists('stat-total', total);
    }
}

function setStatIfExists(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
}

// ─── Job Actions ───────────────────────────────────────────────
async function retryJob(jobId) {
    try {
        const resp = await fetch(`/api/jobs/${jobId}/retry`, { method: 'POST' });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || 'Retry failed');
        }
        showToast('Job queued for retry/re-upload', 'success');
        await refreshJobs();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

async function deleteJob(jobId) {
    const confirmMsg = "Are you sure you want to delete this run? If it is currently running, it will be cancelled.";
    if (!confirm(confirmMsg)) return;

    try {
        const resp = await fetch(`/api/jobs/${jobId}`, { method: 'DELETE' });
        if (!resp.ok) {
            const err = await resp.json();
            throw new Error(err.detail || 'Delete failed');
        }
        showToast('Job deleted successfully', 'info');
        if (window.latestJobs) {
            window.latestJobs = window.latestJobs.filter(j => j.id !== jobId);
            filterJobs();
        }
    } catch (e) {
        showToast(e.message, 'error');
    }
}

function filterJobs() {
    updateJobsList(window.latestJobs || []);
}

function copyError(btn) {
    const banner = btn.closest('.job-error-banner');
    const tooltip = banner?.querySelector('.error-tooltip');
    if (!tooltip) return;

    const text = tooltip.textContent || '';
    navigator.clipboard.writeText(text).then(() => {
        showToast('Error copied to clipboard', 'info');
    }).catch(() => {
        // Fallback for insecure contexts
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        showToast('Error copied to clipboard', 'info');
    });
}

// ─── Pin Actions ───────────────────────────────────────────────
async function showPinDetail(pinId) {
    try {
        const resp = await fetch(`/api/pins/${pinId}`);
        if (!resp.ok) throw new Error('Failed to load pin');
        const pin = await resp.json();

        const html = `
            <div style="display:flex;flex-direction:column;gap:var(--space-md);">
                <div style="border-bottom:1px solid var(--border-subtle);padding-bottom:12px;">
                    <div class="settings-label" style="margin-bottom:4px;">Title</div>
                    <div class="settings-value" style="font-weight:600;font-size:0.95rem;color:var(--text-primary);">${escapeHtml(pin.title)}</div>
                </div>
                <div style="border-bottom:1px solid var(--border-subtle);padding-bottom:12px;">
                    <div class="settings-label" style="margin-bottom:4px;">Description</div>
                    <div style="white-space:pre-wrap;font-size:0.88rem;color:var(--text-secondary);line-height:1.5;">${escapeHtml(pin.description)}</div>
                </div>
                <div style="border-bottom:1px solid var(--border-subtle);padding-bottom:12px;">
                    <div class="settings-label" style="margin-bottom:4px;">Hashtags</div>
                    <div style="font-size:0.88rem;color:var(--accent-primary);font-weight:600;">${escapeHtml(pin.hashtags || '—')}</div>
                </div>
                <div style="border-bottom:1px solid var(--border-subtle);padding-bottom:12px;">
                    <div class="settings-label" style="margin-bottom:4px;">Alt Text</div>
                    <div style="font-size:0.88rem;color:var(--text-secondary);">${escapeHtml(pin.alt_text || '—')}</div>
                </div>
                ${pin.affiliate_url ? `
                <div style="border-bottom:1px solid var(--border-subtle);padding-bottom:12px;">
                    <div class="settings-label" style="margin-bottom:4px;">Affiliate URL</div>
                    <a href="${escapeHtml(pin.affiliate_url)}" target="_blank" style="font-size:0.82rem;word-break:break-all;color:var(--accent-primary);font-weight:500;">${escapeHtml(pin.affiliate_url)}</a>
                </div>` : ''}
                ${pin.creator_username ? `
                <div style="padding-bottom:12px;">
                    <div class="settings-label" style="margin-bottom:4px;">TikTok Creator</div>
                    <div style="font-size:0.88rem;color:var(--text-primary);font-weight:500;">@${escapeHtml(pin.creator_username)}</div>
                </div>` : ''}
            </div>
        `;
        showModal(`Pin Details (#${pin.id})`, html);
    } catch (e) {
        showToast('Failed to load pin details', 'error');
    }
}

async function deletePin(pinId) {
    if (!confirm('Delete this pin? This will also remove it from Pinterest if published.')) return;

    try {
        const resp = await fetch(`/api/pins/${pinId}`, { method: 'DELETE' });
        if (!resp.ok) throw new Error('Delete failed');

        showToast('Pin deleted', 'success');
        const row = document.getElementById(`pin-row-${pinId}`);
        if (row) {
            row.style.opacity = '0';
            row.style.transform = 'translateY(10px)';
            row.style.transition = 'all 0.25s ease';
            setTimeout(() => row.remove(), 250);
        }
    } catch (e) {
        showToast(e.message, 'error');
    }
}

// ─── Toast Notifications ───────────────────────────────────────
function showToast(message, type = 'info', duration = 4000) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const symbols = {
        success: '✓',
        error: '✕',
        warning: '⚠',
        info: 'ℹ',
    };

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${symbols[type] || symbols.info}</span>
        <span class="toast-message">${escapeHtml(message)}</span>
        <button class="toast-close" onclick="dismissToast(this)">✕</button>
    `;

    container.appendChild(toast);

    // Auto-dismiss
    setTimeout(() => dismissToast(toast.querySelector('.toast-close')), duration);
}

function dismissToast(closeBtn) {
    const toast = closeBtn.closest('.toast');
    if (!toast || toast.classList.contains('toast-exit')) return;

    toast.classList.add('toast-exit');
    setTimeout(() => toast.remove(), 300);
}

// ─── Slidesheet Modal Drawer ───────────────────────────────────
function showModal(title, bodyHtml, footerHtml = '') {
    const overlay = document.getElementById('modal-overlay');
    const titleEl = document.getElementById('modal-title');
    const bodyEl = document.getElementById('modal-body');
    const footerEl = document.getElementById('modal-footer');

    if (!overlay) return;

    titleEl.textContent = title;
    bodyEl.innerHTML = bodyHtml;
    footerEl.innerHTML = footerHtml;
    overlay.classList.add('active');

    // Close on overlay click
    overlay.onclick = (e) => {
        if (e.target === overlay) closeModal();
    };

    // Close on Escape
    document.addEventListener('keydown', handleModalEscape);
}

// Dynamic modal closing
function closeModal() {
    const overlay = document.getElementById('modal-overlay');
    if (overlay) overlay.classList.remove('active');
    document.removeEventListener('keydown', handleModalEscape);
}

function handleModalEscape(e) {
    if (e.key === 'Escape') closeModal();
}

// ─── Utilities ─────────────────────────────────────────────────
function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function capitalize(str) {
    return str.charAt(0).toUpperCase() + str.slice(1);
}

function setButtonLoading(btnId, textId, spinnerId, loading) {
    const textEl = document.getElementById(textId);
    const spinnerEl = document.getElementById(spinnerId);
    const btnEl = document.getElementById(btnId);

    if (!textEl || !spinnerEl || !btnEl) return;

    if (loading) {
        textEl.classList.add('hidden');
        spinnerEl.classList.remove('hidden');
        btnEl.disabled = true;
    } else {
        textEl.classList.remove('hidden');
        spinnerEl.classList.add('hidden');
        btnEl.disabled = false;
    }
}
