'use strict';
(() => {
  function stripCursorParam(path) {
    const qIdx = path.indexOf('?');
    if (qIdx === -1) return path;
    const base = path.slice(0, qIdx);
    const params = path
      .slice(qIdx + 1)
      .split('&')
      .filter(p => p && !p.startsWith('cursor='));
    return params.length ? `${base}?${params.join('&')}` : base;
  }

  const MAX_ATTEMPTS = 2;

  // 400 (malformed cursor), 410 (server can no longer verify a legacy cursor
  // anchor) or an error flagged cursorExpired all mean "restart from page 1".
  function isCursorRejection(err) {
    return Boolean(err && (err.status === 400 || err.status === 410 || err.cursorExpired));
  }

  // Raised when the server still reports an expired cursor after the restart
  // from the first page. Returning the items collected so far would make the
  // caller treat a partial list as complete, so fail loudly instead.
  function cursorExpiredError() {
    const err = new Error('分頁游標已失效，重新載入後仍無法取得完整清單，請稍後再試。');
    err.cursorExpired = true;
    err.incompleteResult = true;
    return err;
  }

  async function fetchAllPages(api, path) {
    let activePath = path;
    for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
      const canRetry = attempt + 1 < MAX_ATTEMPTS;
      let first;
      try {
        first = await api(activePath);
      } catch (err) {
        if (canRetry && isCursorRejection(err)) {
          activePath = stripCursorParam(activePath);
          continue;
        }
        throw err;
      }
      if (first?.cursorExpired) {
        if (!canRetry) throw cursorExpiredError();
        activePath = stripCursorParam(activePath);
        continue;
      }
      const firstItems = Array.isArray(first?.items) ? first.items : [];
      const items = [...firstItems];
      const seen = new Set(firstItems.map(x => x?.id).filter(Boolean));
      let total = Number(first?.total) || items.length;
      const limit = Number(first?.limit) || 100;
      let skipped = Number(first?.skipped) || 0;
      let nextOffset = (Number(first?.offset) || 0) + firstItems.length;
      let cursor = typeof first?.nextCursor === 'string' && first.nextCursor ? first.nextCursor : '';
      const usesCursor = Boolean(cursor);
      let restartFromFirstPage = false;
      while ((usesCursor ? Boolean(cursor) : nextOffset < total) && firstItems.length > 0) {
        const sep = activePath.includes('?') ? '&' : '?';
        const cursorParam = cursor ? `&cursor=${encodeURIComponent(cursor)}` : '';
        let page;
        try {
          page = await api(`${activePath}${sep}offset=${nextOffset}&limit=${limit}${cursorParam}`);
        } catch (err) {
          if (usesCursor && canRetry && isCursorRejection(err)) {
            activePath = stripCursorParam(activePath);
            restartFromFirstPage = true;
            break;
          }
          throw err;
        }
        if (page?.cursorExpired) {
          if (!canRetry) throw cursorExpiredError();
          activePath = stripCursorParam(activePath);
          restartFromFirstPage = true;
          break;
        }
        const pageItems = Array.isArray(page?.items) ? page.items : [];
        if (!pageItems.length) break;
        if (Number.isFinite(Number(page?.total)) && Number(page.total) >= 0) total = Number(page.total);
        if (Number(page?.skipped) > skipped) skipped = Number(page.skipped);
        nextOffset += pageItems.length;
        let added = 0;
        for (const item of pageItems) {
          if (item?.id && seen.has(item.id)) continue;
          if (item?.id) seen.add(item.id);
          items.push(item);
          added++;
        }
        if (!added) break;
        cursor = typeof page?.nextCursor === 'string' && page.nextCursor ? page.nextCursor : '';
      }
      if (restartFromFirstPage) continue;
      return { ...first, items, total: Math.max(total, items.length), skipped };
    }
    throw cursorExpiredError();
  }

  if (typeof window === 'object' && window) {
    window.fox3dFetchAllPages = fetchAllPages;
  }
  if (typeof globalThis === 'object' && globalThis) {
    globalThis.fox3dFetchAllPages = fetchAllPages;
  }
  if (typeof module === 'object' && module && module.exports) {
    module.exports = { fetchAllPages };
  }
})();
