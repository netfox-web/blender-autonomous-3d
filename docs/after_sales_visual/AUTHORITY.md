# 售後視覺助理：資料權威與邊界

狀態：`NON_PRODUCTION`、`LIVE_MODEL=false`、`AUTO_SHIP=false`、`SELF_PASS=false`。

本模組不是第二套 ERP、BOM、商品主檔、組裝說明或安全認證系統。它只保存來源引用、SHA-256、來源 revision，以及本次照片觀察與人工覆核事件。

| 資料 | 權威 | 本模組行為 |
|---|---|---|
| SKU／商品族／客服案件／補件單 | ERP 既有流程與 PR #67 後續 owner | 只接 typed read-only snapshot；只輸出不可執行 draft |
| 工程版本、BOM、組裝步驟 | 已核准來源；Fox3D 只重用 `kd.py` 的 `instructionsV2`、assembly graph、labels、carton contents | 無 approval provenance 即 fail closed |
| Product DNA | `product_dna.py`／Issue #18／merged PR #19 | 保留 `UNBOUND`、BOM candidate、engineering/manufacturing false；不得提升 |
| 圖片與衍生圖 | 原始 content hash + 去識別衍生 hash | 不覆寫原件；測試只用 synthetic fixture |
| 結構安全 | 人工／正式工程安全審查 | 只提示停用與轉人工；永不判定安全可用 |

## Identity fail-closed

`tenant_id`、`company_id`、SKU、engineering version 任一不一致時狀態為 `BLOCKED_VERSION_OR_IDENTITY`。沒有 approval ref、BOM scope 為 candidate、ERP binding 為 `UNBOUND`、或 approval 過期時為 `BLOCKED_APPROVAL_PROVENANCE`。不得回落至「最新版」。

`TEST_APPROVAL` 只允許 `SYNTHETIC_FIXTURE`，不代表任何真實商品、真實 BOM、真實客服案件或可安全補件。
