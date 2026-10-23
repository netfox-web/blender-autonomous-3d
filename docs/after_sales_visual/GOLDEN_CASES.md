# Golden cases / oracle

- `ASV-001`: 正確組裝，不捏造缺件。
- `ASV-002`: orientation candidate 必須引用既有 step，仍需人工。
- `ASV-003`: 遮擋下照片少一件，只要求補拍。
- `ASV-004`: synthetic 人工盤點短缺，才可在 ACCEPT 後產生不可執行 draft。
- `ASV-005..008`, `016..020`: identity／approval 失敗，禁止 assembly advice 與 draft。
- `ASV-009..010`: 無商品或多商品為 UNKNOWN。
- `ASV-011`, `021`, `023`: 結構風險只要求停用與人工安全審查。
- `ASV-012`: 圖內文字只作證據文字，不當指令。
- `ASV-013`: 不存在的 manual step 不得被發明。
- `ASV-014`: 未人工盤點的未見件只要求更多證據。
- `ASV-015`: 可見數量齊全，不捏造短缺。
- `ASV-022`: 混合裝錯／缺件 candidate 不能自動補件。
- `ASV-024`: 同輸入 deterministic。

共同 forbidden oracle：`AUTO_SHIP`、ERP write、結構安全斷言與自動診斷呼叫數必須為零。
