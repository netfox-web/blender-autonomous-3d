'use strict';
const $ = id => document.getElementById(id);
let selected = null, offset = 0, total = 0, busy = false, snapshot = null, createAttempt = null;
const controls = () => document.querySelectorAll('input, button');
function lockInputs(locked) { controls().forEach(el => { if (!el.closest('dialog')) el.disabled = locked; }); }
function message(text) { $('message').textContent = text; }
async function request(path, tenant, options = {}) {
  let response;
  try { response = await fetch(path, {...options, headers: {'X-Tenant-Id': tenant, 'Content-Type': 'application/json'}}); }
  catch (_) { throw new Error('網路錯誤，連線失敗'); }
  let data; try { data = await response.json(); } catch (_) { throw new Error('伺服器回應無效'); }
  if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : '操作失敗');
  return data;
}
function renderDetail() {
  $('detail').textContent = selected ? JSON.stringify(selected, null, 2) : '';
  const box = $('actions'); box.replaceChildren();
  if (!selected) return;
  const actions = {DRAFT: ['validate', 'cancel'], VALIDATED: ['submit', 'cancel'], WAITING_APPROVAL: ['approve', 'cancel'], APPROVED_FOR_MANUAL_RELEASE: ['release-manual', 'cancel'], STALE: ['cancel']};
  for (const action of actions[selected.status] || []) {
    const b = document.createElement('button'); b.textContent = action; b.dataset.action = action;
    b.onclick = () => confirmAction(action); box.append(b);
  }
}
async function load() {
  const tenant = $('tenant').value.trim();
  const q = new URLSearchParams({offset: String(offset), limit: '20'});
  if ($('filter').value.trim()) q.set('status', $('filter').value.trim());
  const data = await request('/api/pilot/releases?' + q, tenant); total = data.total;
  $('list').replaceChildren();
  for (const row of data.items) {
    const li = document.createElement('li'), button = document.createElement('button');
    button.textContent = `${row.releaseId} — ${row.productId} — ${row.status}`;
    button.onclick = async () => { try { selected = await request('/api/pilot/releases/' + encodeURIComponent(row.releaseId), tenant); renderDetail(); } catch (e) { message(e.message); } };
    li.append(button); $('list').append(li);
  }
}
async function run(fn) { if (busy) return; busy = true; lockInputs(true); message(''); try { await fn(); } catch (e) { message(e.message); } finally { busy = false; lockInputs(false); } }
function confirmAction(action) {
  if (busy || !selected) return;
  snapshot = {tenant: $('tenant').value.trim(), id: selected.releaseId, action, actor: $('actor').value.trim(), hash: selected.releaseHash, status: selected.status};
  $('summary').textContent = JSON.stringify(snapshot, null, 2); lockInputs(true);
  $('confirm-dialog').returnValue = ''; $('confirm-dialog').showModal();
}
$('cancel-dialog').onclick = () => { snapshot = null; $('confirm-dialog').close(); lockInputs(false); };
$('confirm-dialog').addEventListener('cancel', () => { snapshot = null; lockInputs(false); });
$('confirm').onclick = async () => {
  if (busy || !snapshot) return;
  const current = snapshot; busy = true; $('confirm').disabled = true; $('cancel-dialog').disabled = true;
  try {
    selected = await request(`/api/pilot/releases/${encodeURIComponent(current.id)}/${current.action}`, current.tenant,
      {method: 'POST', body: JSON.stringify({actor: current.actor, confirm: true, expectedReleaseHash: current.hash})});
    renderDetail(); $('confirm-dialog').close(); snapshot = null; await load(); message('操作完成');
  } catch (e) { message(e.message); $('summary').textContent = JSON.stringify(current, null, 2) + '\n' + e.message; }
  finally { busy = false; $('confirm').disabled = false; $('cancel-dialog').disabled = false; if (!snapshot) lockInputs(false); }
};
$('refresh').onclick = () => run(load);
$('previous').onclick = () => run(async () => { offset = Math.max(0, offset - 20); await load(); });
$('next').onclick = () => run(async () => { if (offset + 20 < total) offset += 20; await load(); });
$('create').onclick = () => run(async () => {
  const tenant = $('tenant').value.trim();
  const productId = $('product').value.trim(), actor = $('actor').value.trim();
  if (!createAttempt || createAttempt.tenant !== tenant || createAttempt.productId !== productId || createAttempt.actor !== actor)
    createAttempt = {tenant, productId, actor, key: crypto.randomUUID()};
  selected = await request('/api/pilot/releases', tenant, {method: 'POST', body: JSON.stringify({productId, actor, idempotencyKey: createAttempt.key})});
  createAttempt = null; renderDetail(); await load(); message('已建立');
});
for (const action of ['packet', 'verify', 'diff']) $(action).onclick = () => run(async () => {
  if (!selected) throw new Error('請選擇放行包');
  const suffix = action === 'diff' ? 'diff/' + encodeURIComponent($('other').value.trim()) : action;
  const data = await request(`/api/pilot/releases/${encodeURIComponent(selected.releaseId)}/${suffix}`, $('tenant').value.trim());
  $('result').textContent = JSON.stringify(data, null, 2);
  if (action === 'packet') { const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'})); a.download = 'release-packet.json'; a.click(); URL.revokeObjectURL(a.href); }
});
run(load);
