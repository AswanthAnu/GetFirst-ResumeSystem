/**
 * app.js — Antigravity Resume System Frontend
 * Vanilla JS — no dependencies. PDF upload via FormData.
 */

// ─── State ────────────────────────────────────────────────────────
let currentResult = null;     // Last pipeline result
let currentPdfFile = null;    // Currently selected PDF File object
let activeModalId = null;

// ─── Tab Switching ────────────────────────────────────────────────

function switchTab(tab) {
  document.querySelectorAll('.panel').forEach(p => {
    p.classList.remove('active');
    p.classList.add('hidden');
  });
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));

  const panel = document.getElementById(`panel-${tab}`);
  panel.classList.remove('hidden');
  panel.classList.add('active');
  document.getElementById(`tab-${tab}`).classList.add('active');

  if (tab === 'history') loadHistory();
}

function switchOutputTab(tab) {
  ['cv', 'text', 'letter', 'changes'].forEach(t => {
    document.getElementById(`otab-${t}`).classList.toggle('active', t === tab);
    document.getElementById(`opanel-${t}`).classList.toggle('hidden', t !== tab);
  });
}

function switchModalTab(tab) {
  ['cv', 'original', 'jd', 'changes'].forEach(t => {
    document.getElementById(`mtab-${t}`).classList.toggle('active', t === tab);
    document.getElementById(`modal-body-${t}`).classList.toggle('hidden', t !== tab);
  });
}

// ─── PDF File Selection ───────────────────────────────────────────

function handleFileSelect(input) {
  const file = input.files[0];
  if (!file) return;
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    showToast('Please select a PDF file.', 'error');
    input.value = '';
    return;
  }
  currentPdfFile = file;
  const zone = document.getElementById('upload-zone');
  zone.classList.add('has-file');
  document.getElementById('upload-icon').textContent = '✅';
  document.getElementById('upload-text').innerHTML = `
    <span class="upload-filename">${escapeHtml(file.name)}</span>
    <span class="upload-sub">${(file.size / 1024).toFixed(0)} KB — click to change</span>
  `;
}

// Drag and drop support
document.addEventListener('DOMContentLoaded', () => {
  const zone = document.getElementById('upload-zone');
  if (!zone) return;

  zone.addEventListener('dragover', e => {
    e.preventDefault();
    zone.classList.add('drag-over');
  });
  zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
  zone.addEventListener('drop', e => {
    e.preventDefault();
    zone.classList.remove('drag-over');
    const file = e.dataTransfer.files[0];
    if (file && file.name.toLowerCase().endsWith('.pdf')) {
      const input = document.getElementById('input-cv-pdf');
      // Create a DataTransfer to assign the file
      const dt = new DataTransfer();
      dt.items.add(file);
      input.files = dt.files;
      handleFileSelect(input);
    } else {
      showToast('Please drop a PDF file.', 'error');
    }
  });
});

// ─── Status Bar ───────────────────────────────────────────────────

function setStatus(state, text) {
  const dot = document.querySelector('.status-dot');
  const txt = document.getElementById('status-text');
  dot.className = `status-dot ${state}`;
  txt.textContent = text;
}

// ─── Loading Animation ────────────────────────────────────────────

// The pipeline runs as a single API call — the frontend has no visibility
// into which step is executing. The step list in the UI is informational
// only (it shows what the pipeline does, not where it currently is).
// We use a simple spinner with no fake progress timer.

function startLoadingAnimation() {}

function stopLoadingAnimation() {}

// ─── UI State Transitions ─────────────────────────────────────────

function showLoading() {
  document.getElementById('empty-state').classList.add('hidden');
  document.getElementById('loading-state').classList.remove('hidden');
  document.getElementById('output-content').classList.add('hidden');
  setStatus('running', 'Running pipeline…');
  startLoadingAnimation();
}

function showOutput(result) {
  stopLoadingAnimation();
  document.getElementById('loading-state').classList.add('hidden');
  document.getElementById('output-content').classList.remove('hidden');
  setStatus('success', 'Generation complete');
  renderOutput(result);
}

function showError(message) {
  stopLoadingAnimation();
  document.getElementById('loading-state').classList.add('hidden');
  document.getElementById('empty-state').classList.remove('hidden');
  setStatus('error', 'Error');
  showToast(message, 'error');
}

// ─── Generate ─────────────────────────────────────────────────────

async function handleGenerate() {
  if (!currentPdfFile) return showToast('Please upload your CV PDF first.', 'error');
  const jobTitle = document.getElementById('input-job-title').value.trim();
  const company = document.getElementById('input-company').value.trim();
  const jd = document.getElementById('input-jd').value.trim();

  if (!jobTitle) return showToast('Please enter a job title.', 'error');
  if (!company) return showToast('Please enter a company name.', 'error');
  if (!jd) return showToast('Please paste the job description.', 'error');

  document.getElementById('btn-generate').disabled = true;
  document.getElementById('btn-regenerate').disabled = true;
  document.getElementById('btn-confirm').disabled = true;
  currentResult = null;

  showLoading();

  // Build multipart form data
  const formData = new FormData();
  formData.append('cv_pdf', currentPdfFile, currentPdfFile.name);
  formData.append('job_title', jobTitle);
  formData.append('company', company);
  formData.append('job_description', jd);

  try {
    const res = await fetch('/api/generate', {
      method: 'POST',
      body: formData,  // No Content-Type header — browser sets multipart boundary
    });

    const json = await res.json();
    if (!res.ok) {
      // FastAPI 422 returns detail as an array of {loc, msg} objects
      const detail = Array.isArray(json.detail)
        ? json.detail.map(d => `${d.loc?.join('.') || '?'}: ${d.msg}`).join('; ')
        : (json.detail || 'Generation failed.');
      throw new Error(detail);
    }

    currentResult = json.data;
    showOutput(currentResult);
    document.getElementById('btn-regenerate').disabled = false;
    document.getElementById('btn-confirm').disabled = false;

  } catch (err) {
    showError(err.message);
  } finally {
    document.getElementById('btn-generate').disabled = false;
  }
}

async function handleRegenerate() {
  // Stateless — re-send same PDF + inputs, no prior result passed
  await handleGenerate();
}

// ─── Render Output ────────────────────────────────────────────────

function renderOutput(result) {
  // Generated LaTeX CV
  document.getElementById('cv-view').textContent = result.modified_cv_latex || '(no LaTeX generated)';

  // Original plain text from PDF
  document.getElementById('text-view').textContent = result.cv_text || '(no text extracted)';

  // Cover letter
  renderLetter(result.cover_letter_text);

  // Changes + Analysis
  renderChanges(result.key_changes_summary, result.analysis);

  // Validation
  renderValidation(result.validation);

  switchOutputTab('cv');
}

function renderLetter(text) {
  const container = document.getElementById('letter-view');
  const today = new Date().toLocaleDateString('en-IE', {
    year: 'numeric', month: 'long', day: 'numeric'
  });
  container.innerHTML = `<div class="letter-date">${today}</div>${escapeHtml(text || '')}`;
}

function renderChanges(summary, analysis) {
  const container = document.getElementById('changes-view');
  let html = '';

  if (summary && summary.length) {
    summary.forEach((change, i) => {
      html += `<div class="change-chip">
        <span class="change-num">${i + 1}</span>
        <span>${escapeHtml(change)}</span>
      </div>`;
    });
  } else {
    html = '<p style="color:var(--text-3);font-size:0.85rem;">No changes summary available.</p>';
  }

  if (analysis) {
    html += `<div class="analysis-section">`;
    if (analysis.key_requirements?.length) {
      html += `<div class="analysis-row">
        <span class="analysis-label">Requirements</span>
        ${analysis.key_requirements.slice(0, 5).map(r => `<span class="tag">${escapeHtml(r)}</span>`).join('')}
      </div>`;
    }
    if (analysis.matching_skills?.length) {
      html += `<div class="analysis-row">
        <span class="analysis-label">Matched</span>
        ${analysis.matching_skills.slice(0, 5).map(s => `<span class="tag">${escapeHtml(s)}</span>`).join('')}
      </div>`;
    }
    if (analysis.gaps?.length) {
      html += `<div class="analysis-row">
        <span class="analysis-label">Gaps</span>
        ${analysis.gaps.slice(0, 3).map(g => `<span class="tag gap">${escapeHtml(g)}</span>`).join('')}
      </div>`;
    }
    html += `</div>`;
  }

  container.innerHTML = html;
}

function renderValidation(validation) {
  if (!validation) return;
  const banner = document.getElementById('validation-banner');
  let html = '';

  const checks = [
    { key: 'entity_check', label: 'Entity check passed — no hallucinated companies, roles, or technologies' },
    { key: 'latex_check',  label: 'LaTeX structure validated — document is well-formed and compilable' },
    { key: 'timeline_check', label: 'Timeline preserved — all original dates present in generated CV' },
  ];

  checks.forEach(c => {
    if (validation[c.key] === true) {
      html += `<div class="vb-item ok">✓ ${c.label}</div>`;
    }
  });
  (validation.warnings || []).forEach(w => {
    html += `<div class="vb-item warn">⚠ ${escapeHtml(w)}</div>`;
  });

  banner.innerHTML = html;
}

// ─── Confirm ─────────────────────────────────────────────────────

async function handleConfirm() {
  if (!currentResult) return;

  const appliedDate = document.getElementById('input-applied-date').value || null;
  document.getElementById('btn-confirm').disabled = true;

  try {
    const res = await fetch('/api/confirm', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pipeline_result: currentResult, applied_date: appliedDate }),
    });
    const json = await res.json();
    if (!res.ok) throw new Error(json.detail || 'Save failed.');

    const appId = json.application_id;
    const dlPath = json.cover_letter_path || '';
    const isUrl = dlPath.startsWith('http');
    const dlLink = `<a href="/api/applications/${appId}/download" style="color:#fff;text-decoration:underline;margin-left:8px" target="_blank">⬇ Download DOCX</a>`;
    showToast(`Saved! ${isUrl ? dlLink : 'CV & cover letter generated.'}`, 'success');
    currentResult = null;
    document.getElementById('btn-confirm').disabled = true;
    document.getElementById('btn-regenerate').disabled = true;

    // Reset form
    document.getElementById('input-job-title').value = '';
    document.getElementById('input-company').value = '';
    document.getElementById('input-jd').value = '';
    currentPdfFile = null;
    const zone = document.getElementById('upload-zone');
    zone.classList.remove('has-file');
    document.getElementById('upload-icon').textContent = '📄';
    document.getElementById('upload-text').innerHTML = `
      <span class="upload-primary">Click to upload your CV PDF</span>
      <span class="upload-sub">Exported from Overleaf</span>`;
    document.getElementById('input-cv-pdf').value = '';

    document.getElementById('output-content').classList.add('hidden');
    document.getElementById('empty-state').classList.remove('hidden');
    setStatus('idle', 'Ready');

  } catch (err) {
    showToast(err.message, 'error');
    document.getElementById('btn-confirm').disabled = false;
  }
}

// ─── Copy Helpers ─────────────────────────────────────────────────

function copyCV() {
  const text = document.getElementById('cv-view').textContent;
  if (!text) return;
  navigator.clipboard.writeText(text)
    .then(() => showToast('LaTeX CV copied! Paste into Overleaf.', 'info'))
    .catch(() => showToast('Copy failed.', 'error'));
}

function copyLetter() {
  if (!currentResult?.cover_letter_text) return;
  navigator.clipboard.writeText(currentResult.cover_letter_text)
    .then(() => showToast('Cover letter copied to clipboard!', 'info'))
    .catch(() => showToast('Copy failed.', 'error'));
}

// ─── History ──────────────────────────────────────────────────────

let historyRecords = [];

function renderHistoryCards(records) {
  const container = document.getElementById('history-list');
  if (!records.length) {
    container.innerHTML = '<p class="empty-sub" style="text-align:center;padding:3rem">No matching applications.</p>';
    return;
  }
  container.innerHTML = records.map(r => {
    const date = r.applied_date
      ? new Date(r.applied_date).toLocaleDateString('en-IE')
      : r.created_at ? new Date(r.created_at).toLocaleDateString('en-IE') : '—';
    const status = r.status || 'confirmed';
    return `<div class="history-card" onclick="openModal('${r.id}')">
      <div class="hc-status ${status}"></div>
      <div class="hc-content">
        <div class="hc-title">${escapeHtml(r.job_title)}</div>
        <div class="hc-company">${escapeHtml(r.company)}</div>
        <div class="hc-meta">Saved: ${date}</div>
      </div>
      <span class="hc-badge ${status}">${status}</span>
    </div>`;
  }).join('');
}

function filterHistory() {
  const input = document.getElementById('history-search');
  if (!input) { renderHistoryCards(historyRecords); return; }
  const query = input.value.toLowerCase().trim();
  if (!query) { renderHistoryCards(historyRecords); return; }
  const filtered = historyRecords.filter(r =>
    (r.job_title || '').toLowerCase().includes(query) ||
    (r.company || '').toLowerCase().includes(query)
  );
  renderHistoryCards(filtered);
}

async function loadHistory() {
  const container = document.getElementById('history-list');
  container.innerHTML = '<p style="color:var(--text-3);text-align:center;padding:2rem">Loading…</p>';

  try {
    const res = await fetch('/api/applications');
    const json = await res.json();
    if (!res.ok) throw new Error(json.detail || 'Failed to load history');

    historyRecords = json.data;
    if (!historyRecords.length) {
      container.innerHTML = '<p class="empty-sub" style="text-align:center;padding:3rem">No applications saved yet.</p>';
      return;
    }

    filterHistory(); // applies search if query present, else renders all

  } catch (err) {
    container.innerHTML = `<p style="color:var(--danger);text-align:center;padding:2rem">${escapeHtml(err.message)}</p>`;
  }
}

// ─── Modal ────────────────────────────────────────────────────────

async function openModal(id) {
  activeModalId = id;
  document.getElementById('modal-overlay').classList.remove('hidden');
  document.getElementById('modal-header').innerHTML = '<p style="color:var(--text-3)">Loading…</p>';
  switchModalTab('cv');

  try {
    const res = await fetch(`/api/applications/${id}`);
    const json = await res.json();
    if (!res.ok) throw new Error(json.detail || 'Not found');

    const r = json.data;
    const date = r.applied_date
      ? new Date(r.applied_date).toLocaleDateString('en-IE') : '—';

    document.getElementById('modal-header').innerHTML = `
      <h3>${escapeHtml(r.job_title)} — ${escapeHtml(r.company)}</h3>
      <p>Applied: ${date} · Status: ${r.status}</p>`;

    document.getElementById('modal-body-cv').textContent = r.cv_latex_generated || '(no CV stored)';
    document.getElementById('modal-body-original').textContent = r.cv_text_original || '(no original text stored)';
    document.getElementById('modal-body-jd').textContent = r.job_description_raw || '(no JD stored)';

    let changes = [];
    try { changes = JSON.parse(r.key_changes_summary || '[]'); } catch {}
    document.getElementById('modal-body-changes').innerHTML = changes.length
      ? changes.map((c, i) => `<div class="change-chip">
          <span class="change-num">${i + 1}</span><span>${escapeHtml(c)}</span>
        </div>`).join('')
      : '<p style="color:var(--text-3)">No changes summary stored.</p>';

    const badge = document.getElementById('modal-status-badge');
    badge.textContent = r.status; badge.className = `modal-status-badge ${r.status}`;
    document.getElementById('modal-btn-applied').style.display =
      r.status === 'applied' ? 'none' : 'inline-flex';

    // Show download button if cover letter exists
    const dlBtn = document.getElementById('modal-btn-download');
    if (dlBtn) {
      if (r.cover_letter_path) {
        dlBtn.href = `/api/applications/${r.id}/download`;
        dlBtn.style.display = 'inline-flex';
      } else {
        dlBtn.style.display = 'none';
      }
    }

  } catch (err) {
    document.getElementById('modal-header').innerHTML =
      `<p style="color:var(--danger)">${escapeHtml(err.message)}</p>`;
  }
}

function closeModal() {
  document.getElementById('modal-overlay').classList.add('hidden');
  activeModalId = null;
}

async function markApplied() {
  if (!activeModalId) return;
  try {
    const res = await fetch(`/api/applications/${activeModalId}/status`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ status: 'applied' }),
    });
    if (!res.ok) throw new Error('Failed to update status.');
    document.getElementById('modal-status-badge').textContent = 'applied';
    document.getElementById('modal-status-badge').className = 'modal-status-badge applied';
    document.getElementById('modal-btn-applied').style.display = 'none';
    showToast('Marked as applied!', 'success');
    loadHistory();
  } catch (err) { showToast(err.message, 'error'); }
}

// ─── Toast ────────────────────────────────────────────────────────

let _toastTimer = null;
function showToast(message, type = 'info') {
  const toast = document.getElementById('toast');
  toast.innerHTML = message;  // supports HTML (e.g. download links)
  toast.className = `toast ${type}`;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => toast.classList.add('hidden'), 5000);
}

// ─── Utility ─────────────────────────────────────────────────────

function escapeHtml(str) {
  if (typeof str !== 'string') return String(str ?? '');
  return str.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

// ─── Keyboard Shortcuts ───────────────────────────────────────────
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') closeModal();
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') handleGenerate();
});
