/* ═══════════════════════════════════════════════════════════════
   Pinterest Automation — Dashboard JavaScript
   Handles job polling, URL submission, toasts, and modals
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

        // Refresh jobs immediately
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

// Listen for textarea changes
document.addEventListener('DOMContentLoaded', () => {
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
    }
});

// ─── Job Polling ───────────────────────────────────────────────

function startJobPolling() {
    // Initial fetch
    refreshJobs();

    // Poll at interval
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(refreshJobs, POLL_INTERVAL);
}

async function refreshJobs() {
    try {
        const resp = await fetch('/api/jobs?per_page=20');
        if (!resp.ok) return;

        const data = await resp.json();
        updateJobsList(data.jobs);
        updateStats(data.jobs);
    } catch (e) {
        // Silently ignore polling errors
        console.debug('Job polling error:', e);
    }
}

function updateJobsList(jobs) {
    const container = document.getElementById('jobs-list');
    if (!container) return;

    if (jobs.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state-icon">📌</div>
                <div class="empty-state-text">No jobs yet. Paste an Amazon link above to get started!</div>
            </div>
        `;
        return;
    }

    container.innerHTML = jobs.map(job => renderJobCard(job)).join('');
}

function renderJobCard(job) {
    const productImg = job.product_image
        ? `<img class="job-product-img" src="${escapeHtml(job.product_image)}" alt="Product">`
        : `<div class="job-product-img" style="display:flex;align-items:center;justify-content:center;font-size:1.3rem;">📦</div>`;

    const title = escapeHtml(job.product_title || 'Processing...');
    const url = escapeHtml(job.affiliate_url);
    const step = job.current_step ? `<div class="job-step">${escapeHtml(job.current_step)}</div>` : '';
    const error = job.error ? `<div class="job-step text-error">${escapeHtml(job.error.substring(0, 100))}</div>` : '';
    const badge = renderBadge(job.status);
    const retryBtn = job.status === 'failed'
        ? `<button class="btn btn-secondary btn-sm" onclick="retryJob(${job.id})">↻ Retry</button>`
        : '';

    return `
        <div class="job-card" id="job-${job.id}" data-status="${job.status}">
            ${productImg}
            <div class="job-info">
                <div class="job-title">${title}</div>
                <div class="job-url truncate">${url}</div>
                ${step}
                ${error}
            </div>
            <div class="job-status">${badge}</div>
            <div class="job-actions">${retryBtn}</div>
        </div>
    `;
}

function renderBadge(status) {
    const activeStatuses = ['extracting', 'searching', 'downloading', 'generating', 'scheduling', 'publishing'];

    if (status === 'queued') {
        return '<span class="badge badge-queued">⏳ Queued</span>';
    } else if (activeStatuses.includes(status)) {
        return `<span class="badge badge-active"><span class="badge-dot"></span> ${capitalize(status)}</span>`;
    } else if (status === 'completed') {
        return '<span class="badge badge-completed">✓ Completed</span>';
    } else if (status === 'failed') {
        return '<span class="badge badge-failed">✕ Failed</span>';
    } else {
        return `<span class="badge badge-draft">${status}</span>`;
    }
}

function updateStats(jobs) {
    const active = jobs.filter(j => !['completed', 'failed'].includes(j.status)).length;
    const completed = jobs.filter(j => j.status === 'completed').length;
    const failed = jobs.filter(j => j.status === 'failed').length;

    setStatIfExists('stat-active', active);
    setStatIfExists('stat-completed', completed);
    setStatIfExists('stat-failed', failed);
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
        showToast(`Job #${jobId} retrying...`, 'info');
        await refreshJobs();
    } catch (e) {
        showToast(e.message, 'error');
    }
}

// ─── Pin Actions ───────────────────────────────────────────────

async function showPinDetail(pinId) {
    try {
        const resp = await fetch(`/api/pins/${pinId}`);
        if (!resp.ok) throw new Error('Failed to load pin');
        const pin = await resp.json();

        const html = `
            <div style="display:flex;flex-direction:column;gap:var(--space-md);">
                <div>
                    <div class="settings-label" style="margin-bottom:4px;">Title</div>
                    <div>${escapeHtml(pin.title)}</div>
                </div>
                <div>
                    <div class="settings-label" style="margin-bottom:4px;">Description</div>
                    <div style="white-space:pre-wrap;font-size:0.88rem;color:var(--text-secondary);">${escapeHtml(pin.description)}</div>
                </div>
                <div>
                    <div class="settings-label" style="margin-bottom:4px;">Hashtags</div>
                    <div style="font-size:0.88rem;color:var(--accent-primary);">${escapeHtml(pin.hashtags || '—')}</div>
                </div>
                <div>
                    <div class="settings-label" style="margin-bottom:4px;">Alt Text</div>
                    <div style="font-size:0.88rem;color:var(--text-secondary);">${escapeHtml(pin.alt_text || '—')}</div>
                </div>
                ${pin.affiliate_url ? `
                <div>
                    <div class="settings-label" style="margin-bottom:4px;">Affiliate URL</div>
                    <a href="${escapeHtml(pin.affiliate_url)}" target="_blank" style="font-size:0.82rem;word-break:break-all;">${escapeHtml(pin.affiliate_url)}</a>
                </div>` : ''}
                ${pin.creator_username ? `
                <div>
                    <div class="settings-label" style="margin-bottom:4px;">TikTok Creator</div>
                    <div>@${escapeHtml(pin.creator_username)}</div>
                </div>` : ''}
            </div>
        `;
        showModal(`Pin #${pin.id}`, html);
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
            row.style.transform = 'translateX(20px)';
            row.style.transition = 'all 0.3s ease';
            setTimeout(() => row.remove(), 300);
        }
    } catch (e) {
        showToast(e.message, 'error');
    }
}

// ─── Toast Notifications ───────────────────────────────────────

function showToast(message, type = 'info', duration = 4000) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const icons = {
        success: '✓',
        error: '✕',
        warning: '⚠',
        info: 'ℹ',
    };

    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;
    toast.innerHTML = `
        <span class="toast-icon">${icons[type] || icons.info}</span>
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

// ─── Modal ─────────────────────────────────────────────────────

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
