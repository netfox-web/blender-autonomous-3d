# 售後視覺助理 v1 契約

## Input

`fox3d.after-sales-visual.case.v1` 需要：tenant/company、case、requested SKU、requested engineering version、雙照片 hash、read-only catalog snapshot、既有 `instructionsV2` snapshot，以及模型無關 observations。

照片 intake 只接受本地 PNG/JPEG bytes；限制 12 MB、24 MP，重新解碼為不帶 EXIF 的 PNG，原件 hash 與衍生件 hash 分開。fixture reader 必須位於明確 root 內，不接受 URL、symlink、路徑跳脫或可執行附件。

## Provider

- `FixtureObservationProvider`: `MOCK_REGRESSION`，固定讀 synthetic observations，不宣稱視覺準確率。
- `DisabledVisualModelAdapter`: `REAL_INTEGRATION_NOT_RUN`，永遠拒絕；本 Issue 不使用 GPU、付費 API 或真人客照。

## Output

`fox3d.after-sales-visual.result.v1` 只會產生 candidate、補拍要求、安全人工轉介與 provenance。confidence 是 `FIXTURE_RULE_SCORE_NOT_MODEL_ACCURACY`。

可能狀態：`NO_CANDIDATE`、`NEEDS_HUMAN_REVIEW`、`NEEDS_MORE_EVIDENCE`、`UNKNOWN`、`BLOCKED_VERSION_OR_IDENTITY`、`BLOCKED_APPROVAL_PROVENANCE`、`SAFETY_REVIEW_REQUIRED`。

補件輸出為 `fox3d.after-sales-visual.erp-draft.v1`：固定 `DRAFT_NOT_SUBMITTED`、`executable=false`、`external_write_performed=false`。只有已核准 snapshot、人工盤點確認、missing-part candidate 及人工 ACCEPT/AMEND 同時成立才可建草稿；仍不得送單或出庫。

## Invalidation and idempotency

輸入 canonical hash 決定 candidate set。相同輸入產生相同 ID；換 SKU、工程版、照片或 catalog revision 會改 hash，舊 candidate set 不得產生新 draft。demo store 只追加人工事件，不覆寫原始結果。
