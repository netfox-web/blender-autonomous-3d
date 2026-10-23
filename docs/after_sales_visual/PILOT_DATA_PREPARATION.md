# 真照片 pilot 資料準備指南（未授權執行）

只有另行取得資料與整合授權後才能進行。現階段不得把真人客照放入 repo。

每個樣本最少需要：tenant/company、客服 case ref、已核准 SKU、精確 engineering version、approved service BOM hash、manual/instructionsV2 hash、approval ref、source revision、拍攝授權／去識別紀錄、原件 hash、去識別衍生件 hash、人工標註者與時間。

照片組建議包含全景、SKU 標籤、問題區域、五金攤開與包裝標籤；不可把「看不到」標成「缺件」。annotation 必須分為 visible observation、occlusion、人工盤點、候選原因、反證、需補拍視角及 safety escalation。

資料集須固定 seed、train/validation/pilot split，避免同一 case／同一原圖衍生件跨 split。每檔需 rights class、retention/deletion policy、PII review 與 SHA-256。真實 accuracy/recall 門檻、錯誤成本與人工覆核 SLA 應另行核准，fixture 結果不得用來推定。

禁止：未授權客照、活體／人臉資料、ERP dump、secret、BOM candidate 冒充 approved、latest-version fallback、GPU/付費 API 自動上傳、自動補件或結構安全結論。
