# 隔離 CLI 操作

CLI 只跑 synthetic manifest，不呼叫 GPU、網路、ERP 或物流。

```bash
PYTHONPATH=src python -m fox3d.after_sales_visual.cli \
  --manifest tests/fixtures/after_sales_visual/manifest.json \
  --state-dir /tmp/fox3d-after-sales-preview
```

中斷／恢復驗證：

```bash
PYTHONPATH=src python -m fox3d.after_sales_visual.cli --manifest tests/fixtures/after_sales_visual/manifest.json --state-dir /tmp/fox3d-after-sales-preview --stop-after 5
# exit 75；checkpoint 保留
PYTHONPATH=src python -m fox3d.after_sales_visual.cli --manifest tests/fixtures/after_sales_visual/manifest.json --state-dir /tmp/fox3d-after-sales-preview --resume
```

取消會保留已產生的 evidence：

```bash
PYTHONPATH=src python -m fox3d.after_sales_visual.cli --manifest tests/fixtures/after_sales_visual/manifest.json --state-dir /tmp/fox3d-after-sales-preview --cancel
```

同 state-dir 若換 manifest hash，resume 必須拒絕。正式資料不可使用此 fixture CLI。
