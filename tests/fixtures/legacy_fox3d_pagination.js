// Frozen copy of src/fox3d/static/fox3d-pagination.js as deployed on main (b30344a),
// before the client learned about cursorExpired / HTTP 410. Used only by the
// cross-version pagination regression test; do not update it with the live client.
'use strict';
(() => {
  async function fetchAllPages(api, path) {
    const first = await api(path);
    const firstItems = Array.isArray(first?.items) ? first.items : [];
    const items = [...firstItems];
    const seen = new Set(firstItems.map(x => x?.id).filter(Boolean));
    let total = Number(first?.total) || items.length;
    const limit = Number(first?.limit) || 100;
    let skipped = Number(first?.skipped) || 0;
    let nextOffset = (Number(first?.offset) || 0) + firstItems.length;
    let cursor = typeof first?.nextCursor === 'string' && first.nextCursor ? first.nextCursor : '';
    const usesCursor = Boolean(cursor);
    while ((usesCursor ? Boolean(cursor) : nextOffset < total) && firstItems.length > 0) {
      const sep = path.includes('?') ? '&' : '?';
      const cursorParam = cursor ? `&cursor=${encodeURIComponent(cursor)}` : '';
      const page = await api(`${path}${sep}offset=${nextOffset}&limit=${limit}${cursorParam}`);
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
    return { ...first, items, total: Math.max(total, items.length), skipped };
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
