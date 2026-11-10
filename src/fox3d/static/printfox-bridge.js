'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const base = '/api/print-workspace/printfox';
  const tenant = 'sonaqueen-home';
  let connected = false;
  let busy = false;
  let offset = 0;
  let designTotal = 0;
  let timer = null;
  let moreBtn = null;

  const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const say = (text, error = false) => {
    $('pf-message').textContent = text;
    $('pf-message').className = error ? 'error' : '';
  };
  const labels = {
    pending: '排隊中',
    claimed: '工作機已接單',
    running: '生圖中',
    done: '完成',
    failed: '失敗',
    canceled: '已取消',
    rejected: '驗證失敗，未派工',
    submission_unknown: '送出結果待核對',
  };

  async function api(path, options = {}) {
    const response = await fetch(base + path, { ...options, headers: { 'Content-Type': 'application/json', 'X-Tenant-Id': tenant } });
    let data;
    try {
      data = await response.json();
    } catch {
      throw Error('服務回應無法讀取，請更新狀態核對。');
    }
    if (!response.ok) throw Error(typeof data.detail === 'string' ? data.detail : '請檢查輸入設定。');
    return data;
  }

  function controls() {
    $('pf-save-config').disabled = busy;
    $('pf-clear-token').disabled = busy || !connected;
    $('pf-clear-token').hidden = !connected;
    $('pf-generate-btn').disabled = busy || !connected;
    $('pf-refresh-btn').disabled = busy || !connected;
    $('pf-search-btn').disabled = busy || !connected;
  }

  async function action(fn) {
    if (busy) return;
    busy = true;
    controls();
    try {
      await fn();
    } catch (error) {
      say(error.message, true);
    } finally {
      busy = false;
      controls();
    }
  }

  async function connection() {
    const r = await api('/connection');
    connected = r.connected;
    if ($('pf-url') && r.baseUrl) $('pf-url').placeholder = r.baseUrl;
    $('pf-origin').textContent = r.baseUrl || '';
    $('pf-connection-status').textContent = connected
      ? `已連接 · 在線工作機 ${r.status?.workers_online ?? '未知'} · 佇列 ${r.status?.queue ?? '未知'}`
      : '尚未連接';
    controls();
    return r;
  }

  function ensureMoreButton() {
    if (moreBtn) return moreBtn;
    moreBtn = document.createElement('button');
    moreBtn.type = 'button';
    moreBtn.id = 'pf-more';
    moreBtn.className = 'secondary';
    moreBtn.textContent = '載入更多';
    moreBtn.hidden = true;
    moreBtn.onclick = () => action(() => designs(false));
    return moreBtn;
  }

  async function designs(reset = true) {
    if (reset) {
      offset = 0;
      $('pf-designs').replaceChildren();
    }
    const r = await api('/designs?q=' + encodeURIComponent($('pf-q').value) + '&offset=' + offset);
    designTotal = r.total;
    $('pf-count').textContent = `${r.total} 份設計稿`;
    for (const d of r.items) {
      const card = document.createElement('div');
      card.className = 'pf-card';
      const img = document.createElement('img');
      img.loading = 'lazy';
      img.alt = `${d.title} 的縮圖`;
      img.src = `${base}/designs/${encodeURIComponent(d.id)}/preview?workspace=${tenant}`;
      img.onerror = () => {
        img.hidden = true;
      };
      const title = document.createElement('strong');
      title.textContent = d.title;
      const meta = document.createElement('small');
      meta.textContent = `${d.source} · ${d.id}${d.jobId ? ' · 生圖任務 ' + d.jobId : ''}`;
      const button = document.createElement('button');
      button.type = 'button';
      button.textContent = '匯入原圖';
      button.onclick = () =>
        action(async () => {
          say('下載並核對原圖中…');
          const a = await api('/designs/' + encodeURIComponent(d.id) + '/import', { method: 'POST' });
          window.dispatchEvent(new CustomEvent('printfox:imported', { detail: { assetId: a.id } }));
          say(`已匯入「${d.title}」。請在下方商品的「原稿」欄選取，核對尺寸後儲存。`);
        });
      card.append(img, title, meta, button);
      $('pf-designs').append(card);
    }
    offset += r.items.length;
    const more = ensureMoreButton();
    more.hidden = offset >= designTotal;
    if (!more.isConnected) $('pf-designs').insertAdjacentElement('afterend', more);
  }

  function renderTasks(items) {
    $('pf-tasks').innerHTML =
      items
        .map(
          task =>
            `<div class="pf-task"><strong>${esc(labels[task.state] || task.state)} · ${esc(task.progress ?? 0)}%</strong><small>${esc(task.params?.styles?.[0]?.desc || '')}<br>${esc(task.remoteJobId || task.requestId)}</small>${task.message ? `<p>${esc(task.message)}</p>` : ''}<button type="button" data-refresh="${task.requestId}">更新狀態</button>${['pending', 'claimed', 'running'].includes(task.state) ? `<button class="secondary" type="button" data-cancel="${task.requestId}">取消這筆生圖</button>` : ''}</div>`
        )
        .join('') || '<p>尚未從此工作台送出生圖。</p>';
    $('pf-tasks').querySelectorAll('[data-refresh]').forEach(button => {
      button.onclick = () =>
        action(async () => {
          const t = await api('/tasks/' + button.dataset.refresh);
          if (t.remoteJobId && sessionStorage.getItem('fox3d-printfox-pending') === t.requestId)
            sessionStorage.removeItem('fox3d-printfox-pending');
          await tasks();
          if (t.state === 'done') await designs();
        });
    });
    $('pf-tasks').querySelectorAll('[data-cancel]').forEach(button => {
      button.onclick = () =>
        action(async () => {
          await api('/tasks/' + button.dataset.cancel + '/cancel', { method: 'POST' });
          await tasks();
        });
    });
  }

  async function tasks() {
    clearTimeout(timer);
    const r = await api('/tasks');
    renderTasks(r.items);
    if (r.items.some(t => ['pending', 'claimed', 'running'].includes(t.state))) {
      timer = setTimeout(async () => {
        if (!connected) return;
        if (busy) {
          timer = setTimeout(() => tasks().catch(e => say(e.message, true)), 10000);
          return;
        }
        try {
          let finished = false;
          for (const t of r.items.filter(t => ['pending', 'claimed', 'running'].includes(t.state)).slice(0, 10)) {
            const next = await api('/tasks/' + t.requestId);
            if (next.state === 'done') finished = true;
          }
          await tasks();
          if (finished) {
            await designs();
            say('生圖已完成，請選擇圖稿匯入。');
          }
        } catch (error) {
          say(error.message, true);
        }
      }, 10000);
    }
  }

  function generateTargetHint() {
    const t = $('pf-target')?.value.trim();
    const style = $('pf-style')?.value.trim();
    const title = $('pf-title')?.value.trim();
    return [title, style, t].filter(Boolean).join(' · ');
  }

  $('pf-connect').onsubmit = event => {
    event.preventDefault();
    action(async () => {
      const token = $('pf-token').value;
      $('pf-token').value = '';
      await api('/connection', { method: 'POST', body: JSON.stringify({ token }) });
      await connection();
      await designs();
      await tasks();
      say('已連接 PrintFox。可以匯入原圖或送出一次生圖。');
    });
  };

  $('pf-clear-token').onclick = () =>
    action(async () => {
      await api('/connection', { method: 'DELETE' });
      connected = false;
      clearTimeout(timer);
      $('pf-designs').replaceChildren();
      $('pf-tasks').replaceChildren();
      await connection();
      say('已中斷連線。已送出的遠端生圖會繼續，可重新連接後管理。');
    });

  $('pf-search-btn').onclick = () => action(() => designs(true));
  $('pf-q').addEventListener('keydown', e => {
    if (e.key === 'Enter') {
      e.preventDefault();
      action(() => designs(true));
    }
  });

  $('pf-refresh-btn').onclick = () =>
    action(async () => {
      await connection();
      if (connected) {
        await designs();
        await tasks();
      }
    });

  $('pf-generate').onsubmit = event => {
    event.preventDefault();
    action(async () => {
      const promptParts = [$('pf-prompt').value.trim(), generateTargetHint()].filter(Boolean);
      const prompt = promptParts.join(' — ');
      const requestId = sessionStorage.getItem('fox3d-printfox-pending') || crypto.randomUUID();
      sessionStorage.setItem('fox3d-printfox-pending', requestId);
      const task = await api('/tasks', {
        method: 'POST',
        body: JSON.stringify({
          requestId,
          prompt,
          negative: $('pf-negative').value.trim(),
          size: 'wide',
          count: 1,
          engine: 'comfyui',
        }),
      });
      if (task.remoteJobId || task.state === 'rejected') sessionStorage.removeItem('fox3d-printfox-pending');
      await tasks();
      say(
        task.message || '已送出單次生圖。完成後可從圖庫匯入，尺寸仍需核對。',
        ['submission_unknown', 'rejected'].includes(task.state)
      );
    });
  };

  action(async () => {
    await connection();
    if (connected) {
      await designs();
      await tasks();
    }
  });
})();
