const API = '/api/notes';
let notes = [];
let activeNote = null;
let saveTimer = null;
let searchQuery = '';

async function fetchNotes() {
  try {
    const res = await fetch(API, { credentials: 'include' });
    if (res.status === 401) { window.location = '/'; return; }
    notes = await res.json();
    renderList(notes);
  } catch(e) { showToast('Failed to load notes'); }
}

function formatDate(isoStr) {
  const d = new Date(isoStr);
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
    + '  ·  '
    + d.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' });
}

function formatShort(isoStr) {
  const d = new Date(isoStr);
  const now = new Date();
  const diff = now - d;
  if (diff < 60000) return 'just now';
  if (diff < 3600000) return Math.floor(diff/60000) + 'm ago';
  if (diff < 86400000) return Math.floor(diff/3600000) + 'h ago';
  return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
}

function renderList(list) {
  const el = document.getElementById('notes-list');
  if (!list.length) { el.innerHTML = '<div class="empty-list">No notes found</div>'; return; }

  const pinned = list.filter(n => n.pinned);
  const unpinned = list.filter(n => !n.pinned);
  let html = '';

  if (pinned.length) {
    html += '<div class="section-label">Pinned</div>';
    html += pinned.map(n => noteItemHTML(n)).join('');
  }
  if (unpinned.length) {
    if (pinned.length) html += '<div class="section-label">All notes</div>';
    html += unpinned.map(n => noteItemHTML(n)).join('');
  }

  el.innerHTML = html;
}

function noteItemHTML(n) {
  const active = activeNote && activeNote.id === n.id ? ' active' : '';
  const pinIcon = n.pinned ? '<span class="pin-icon">★</span>' : '';
  const preview = n.content ? n.content.replace(/\n/g, ' ').slice(0, 60) + (n.content.length > 60 ? '…' : '') : '—';
  return `<div class="note-item${active}" onclick="openNote(${n.id})">
    <div class="note-item-title">${pinIcon}${escHtml(n.title || 'Untitled')}</div>
    <div class="note-item-preview">${escHtml(preview)}</div>
    <div class="note-item-meta">
      <span>${formatShort(n.updated_at)}</span>
    </div>
  </div>`;
}

function escHtml(s) {
  return String(s == null ? '' : s)
    .replace(/&/g,'&amp;')
    .replace(/</g,'&lt;')
    .replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;')
    .replace(/'/g,'&#39;');
}

function openNote(id) {
  if (saveTimer) { clearTimeout(saveTimer); saveNow(); }
  activeNote = notes.find(n => n.id === id);
  if (!activeNote) return;

  document.getElementById('empty-editor').style.display = 'none';
  const ae = document.getElementById('editor-active');
  ae.style.display = 'flex';

  const titleEl = document.getElementById('note-title-input');
  titleEl.value = activeNote.title;
  autoResize(titleEl);

  document.getElementById('note-body-input').value = activeNote.content;
  document.getElementById('note-date-line').textContent = 'Last edited ' + formatDate(activeNote.updated_at);
  setSaveIndicator('saved');
  updatePinBtn();
  renderList(getFilteredNotes());
  
  if (window.innerWidth <= 640) {
    showEditor();
  }
}

function updatePinBtn() {
  const btn = document.getElementById('pin-btn');
  if (activeNote && activeNote.pinned) {
    btn.classList.add('pin-active');
    btn.querySelector('svg').style.fill = 'currentColor';
  } else {
    btn.classList.remove('pin-active');
    btn.querySelector('svg').style.fill = 'none';
  }
}

async function createNote() {
  try {
    const res = await fetch(API, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ title: 'New note', content: '' })
    });
    const note = await res.json();
    notes.unshift(note);
    renderList(getFilteredNotes());
    openNote(note.id);
    document.getElementById('note-title-input').focus();
    document.getElementById('note-title-input').select();
  } catch(e) { showToast('Could not create note'); }
}

function scheduleSave() {
  setSaveIndicator('saving');
  clearTimeout(saveTimer);
  saveTimer = setTimeout(saveNow, 900);
}

async function saveNow() {
  if (!activeNote) return;
  const title = document.getElementById('note-title-input').value.trim() || 'Untitled';
  const content = document.getElementById('note-body-input').value;
  try {
    const res = await fetch(`${API}/${activeNote.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ title, content })
    });
    const updated = await res.json();
    activeNote.title = updated.title;
    activeNote.content = updated.content;
    activeNote.updated_at = updated.updated_at;
    setSaveIndicator('saved');
    document.getElementById('note-date-line').textContent = 'Last edited ' + formatDate(updated.updated_at);
    const idx = notes.findIndex(n => n.id === activeNote.id);
    if (idx !== -1) notes[idx] = activeNote;
    renderList(getFilteredNotes());
  } catch(e) { setSaveIndicator('error'); }
}

async function togglePin() {
  if (!activeNote) return;
  const newPinned = !activeNote.pinned;
  try {
    const res = await fetch(`${API}/${activeNote.id}`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ pinned: newPinned })
    });
    const updated = await res.json();
    activeNote.pinned = updated.pinned;
    const idx = notes.findIndex(n => n.id === activeNote.id);
    if (idx !== -1) notes[idx] = activeNote;
    updatePinBtn();
    renderList(getFilteredNotes());
    showToast(newPinned ? 'Note pinned' : 'Note unpinned');
  } catch(e) { showToast('Could not update note'); }
}

function confirmDelete() { document.getElementById('delete-modal').classList.add('open'); }
function closeModal() { document.getElementById('delete-modal').classList.remove('open'); }

async function deleteNote() {
  closeModal();
  if (!activeNote) return;
  const id = activeNote.id;
  try {
    await fetch(`${API}/${id}`, { method: 'DELETE', credentials: 'include' });
    notes = notes.filter(n => n.id !== id);
    activeNote = null;
    document.getElementById('editor-active').style.display = 'none';
    document.getElementById('empty-editor').style.display = 'flex';
    renderList(getFilteredNotes());
    showToast('Note deleted');
  } catch(e) { showToast('Could not delete note'); }
}

function filterNotes(q) {
  searchQuery = q.toLowerCase();
  renderList(getFilteredNotes());
}

function getFilteredNotes() {
  if (!searchQuery) return notes;
  return notes.filter(n =>
    n.title.toLowerCase().includes(searchQuery) ||
    n.content.toLowerCase().includes(searchQuery)
  );
}

function setSaveIndicator(state) {
  const el = document.getElementById('save-indicator');
  el.className = 'save-indicator';
  if (state === 'saved') { el.textContent = 'Saved'; el.classList.add('saved'); }
  else if (state === 'saving') { el.textContent = 'Saving…'; }
  else if (state === 'error') { el.textContent = 'Save failed'; el.style.color = 'var(--danger)'; }
  else { el.textContent = '—'; }
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = el.scrollHeight + 'px';
}

function showToast(msg) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.classList.add('show');
  setTimeout(() => t.classList.remove('show'), 2200);
}

function showList() {
  document.querySelector('.sidebar').classList.remove('hidden');
  document.getElementById('editor-pane').classList.remove('active');
}

function showEditor() {
  document.querySelector('.sidebar').classList.add('hidden');
  document.getElementById('editor-pane').classList.add('active');
}

function toggleNavMenu() {
  document.getElementById('nav-links').classList.toggle('mobile-open');
}

window.addEventListener('beforeunload', () => {
  if (saveTimer) saveNow();
});

document.addEventListener('keydown', e => {
  if ((e.ctrlKey || e.metaKey) && e.key === 'n') { e.preventDefault(); createNote(); }
  if ((e.ctrlKey || e.metaKey) && e.key === 's') { e.preventDefault(); if (saveTimer) { clearTimeout(saveTimer); saveNow(); } }
});

fetchNotes();
