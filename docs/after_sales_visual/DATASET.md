# Synthetic dataset v1

`tests/fixtures/after_sales_visual/manifest.json` 含 24 個 deterministic CPU cases，seed `20261023`。全部標示 `SYNTHETIC_FIXTURE` 與 `TEST_APPROVAL_ONLY_NOT_A_REAL_CUSTOMER_OR_PRODUCT_APPROVAL`。

涵蓋：正確組裝、左右／正反候選、遮擋五金、人工盤點短缺、SKU／工程版／tenant／company 衝突、candidate/UNBOUND/expired approval、模糊／無商品／多商品、圖中文字 prompt injection、結構損傷、invalid manual step、補拍、同輸入冪等及混合候選。

每例有 `expected_status`、`allowed_actions`、`forbidden_actions`。合成照片 provenance 由 `synthetic-photo:<case_id>` 與 `deidentified:<case_id>` 分別做 SHA-256；這些值只做 fixture identity，不是假冒真照片 hash。

未執行：真人照片、真視覺 provider、準確率／召回率、真 ERP／客服／物流整合、GPU／Blender。這些一律是 `REAL_INTEGRATION_NOT_RUN` 或 `NOT_EVALUATED`。
