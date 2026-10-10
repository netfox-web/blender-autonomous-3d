# 圖稿與 UV 印刷工作台

本機入口：<http://127.0.0.1:8790/admin/recipes/print>。Recipe 庫與三層櫃頁面也有入口。

## 現場操作

1. 左側「原稿資料庫」搜尋商品編號。點選檔案後，工作台保存一份原稿；共用資料夾原檔保持唯讀。也可上傳 PDF、PDF 相容 AI、JPG、PNG 或單頁 TIFF。
2. 按「建立印刷商品」，填商品編號、名稱，選三片門或單片板件。
3. 每個印刷面選原稿、頁碼、順時針旋轉角度與數量。PDF 直接採用原檔的完整版面與裁切框；圖片必須填入旋轉後含出血的毫米寬高，系統會阻擋拉伸或低於 100 DPI 的稿件。
4. 儲存設定，確認畫面列出的完整版面與裁切尺寸。「生成 3D 套圖」產生真實 Blender 正面圖、透視圖、GLB、Blend；可取消生成並保留上一版成果。
5. 「產生校稿下載包」輸出逐片 PDF、manifest 與交接清單。校稿有紅色 `PROOF - NOT FOR PRINT` 浮水印，供核對方向、次序與尺寸。
6. 印刷人員完成板件量測、孔位／禁印區／治具原點核對、材質／白墨／光油／色彩打樣，填 RIP、機台、材質、確認人員及量測／打樣紀錄，勾選五個確認項目，才可產生無浮水印的印刷包。
7. 下載、解壓後，由印刷人員將 PDF 匯入 RIP，使用 **100% 比例**。實際拼版、治具定位、排程及開機操作沿用現場流程。

任何設定變更都要重新儲存、校稿、確認；舊版印刷放行即失效。下載時會核對原稿、輸出檔與清單的雜湊。

## 目前建立的資料

- 木頭櫃子來源已索引 4,451 個受支援的圖稿檔案。這是檔案數，不是完成建模或可印刷的商品數；PSD 等不支援格式未列入。
- 原稿 `雙三印刷.ai` 是 6 頁 PDF 相容 AI，完整頁面約 286 × 401 mm。順時針轉 90 度後為 401 × 286 mm，裁切框約 395 × 280 mm，各邊約 3 mm 出血。
- DN067301：上、中、下門對應原稿第 1、2、6 頁；DN067302：第 3、4、5 頁。已比對同資料夾中相應編號的 JPG 外觀，仍需現場人員核對產品版本與順序。
- 兩款保留為待打樣商品；沒有代填實測／打樣紀錄，也沒有正式印刷放行。
- 3D 印刷面使用原稿裁切尺寸。櫃身深度、板厚、間隙與外框是示意設定，不能取代工程圖；預覽是 RGB 螢幕效果，不是 RIP 色彩校樣。
- 來源資料未與 Golden 工作台四個舊 SKU 自動混用。

## NetFox Print 交接

使用者確認目前工單功能少用、狀態不明，但圖合版可用。後續銜接以現場可用的合版流程為主；不以恢復舊工單後端作為使用本工作台的前提。下載 ZIP 內的 `netfox-handoff.json` 採 `fox3d.print-handoff.v1` 格式，包含商品、版次、每片 PDF 檔名與 SHA-256、頁面／裁切尺寸、數量、RIP、機台、材質與人工確認狀態。

目前狀態是 `FILE_HANDOFF_ONLY_NOT_SUBMITTED`。已透過既有 SSH 連線唯讀確認 Linux 程式位於 `/data/apps/mw/web/uvprint`，Flask API 是 `api/app.py`，排版引擎是 `api/layout_engine.py`。現有工單附件介面 `POST /api/jobs/<jid>/files` 接受 PDF／ZIP；工單建立介面為 `POST /api/jobs`。這些是原始碼確認的介面規格，尚未通過 LIVE 呼叫驗證。自動排版 `POST /api/layout/generate` 另採 CSV（產品代號、檢貨數、類別、產品名稱）加 JPG／PNG 圖片，會依槽位縮放，不能直接視為原尺寸 PDF 印刷鏈。目前 ZIP 不是可直接匯入這個自動排版表單的 CSV／圖片套件；`netfox-handoff.json` 也不是既有 NetFox 原生匯入格式。

現場服務檢查：PHP proxy 使用 `127.0.0.1:5050/api`，Linux host 沒有 5050 listener，從實際 PHP 容器讀取 `/api/machines` 回傳 HTTP 000（連線未建立）。舊虛擬環境目前使用 Python 3.14.4，無法匯入 Flask；資料庫最後修改時間為 2026-07-03；這只能證明本次檢查的後端未連線，不能否定使用者回報的現場圖合版可用。因此沒有進行正式 API 工單寫入。已讀取的「自動排版」UI 與 merge_layout.php 均轉送同一個 5050 API；實際使用的合版入口及執行環境尚待對照。確認入口、刀模尺寸與色彩流程後，再實作具去重、雜湊回讀與失敗補償的 adapter。這次沒有修改 Linux 程式、啟動正式服務、讀取密鑰、建立正式工單或寫入熱資料夾。

## 開發與維護

本機服務：`python scripts/run_recipe_admin.py --port 8790 --data-root .fox3d-data`，綁定 loopback。工作台沿用本機受信任工作區模型，沒有新增網路登入系統。

設定來源：`python scripts/configure_print_sources.py "<來源資料夾>" --data-root .fox3d-data`。HTTP 介面不能指定任意本機路徑；重新掃描只讀取已設定來源，排除 symbolic links 與 junctions，匯入時再次核對實際路徑範圍。

資料保存於 `.fox3d-data/print-workspaces/`，應連同既有 `.fox3d-data` 備份。原稿以 SHA-256 作識別；工作、PDF 包與 Blender 成果各有版本／雜湊。已匯入的原稿存於本機，後續校稿和 3D 不依賴共用磁碟持續在線；重新掃描或匯入新原稿才需連線。不要將原稿、生成影像或共用磁碟內容提交 GitHub。

目前支援單檔 150 MB、圖片 4,000 萬像素、PDF 最多 100 頁。透明圖稿、非 PDF 相容 AI、EXIF 旋轉圖稿須先整理。系統不新增刀模、白墨或光油分版；PDF 中既有色彩內容與 OutputIntents 保留，印刷適配由 RIP 打樣確認。

驗收程序：先取得 CODE Ubuntu／Windows CI 成功，再於 clean CODE 執行 `scripts/run_print_workspace_e2e.py --source "<實際六頁原稿>"`。腳本檢查 HTTP、原尺寸校稿、真實 Blender、重開 Blend 的幾何／UV／packed textures，以及服務重啟後成果保留。真實原稿僅做未放行校稿；人工放行正向案例使用合成測試稿。

本功能不啟動 CNC、LASER、PLC、UV 實體機台，也不表示 manufacturing-ready。數位檔案核對與機台操作是不同權限。
