# Báo cáo kết quả Observathon — Nhóm 2A202600946-NguyenDucTam

Dự án này tối ưu hóa một agent e-commerce "hộp đen" chạy trên LLM thật qua OpenRouter (`openai/gpt-oss-120b:free`). Bằng cách kết hợp tinh chỉnh cấu hình, viết lại system prompt tối giản, và cài đặt một lớp wrapper bảo vệ, chúng tôi đã khắc phục hoàn toàn 7 lớp lỗi hệ thống và đạt điểm số tối ưu ở cả hai giai đoạn Public và Private.

---

## 📊 Kết quả chấm điểm (Windows local / WSL)

### 1. Giai đoạn Public (120 câu hỏi)
* **Headline Score:** `95.05 / 100`
* **Độ chính xác (Correctness):** `76.5%` (87/120 khớp tuyệt đối)
* **Chất lượng (Quality):** `84.9%`
* **Lỗi hệ thống (Error rate):** `0%` (Mitigated 100%)
* **Drift session:** Giảm hoàn toàn (`84.4%`)
* **Prompt Efficacy:** `85.0%`
* **Diagnosis F1:** `82.4%` (Đạt điểm bonus chẩn đoán lỗi)

### 2. Giai đoạn Private (80 câu hỏi held-out + Injection)
* **Headline Score:** `84.59 / 100`
* **Độ chính xác (Correctness):** `61.0%` (44/80 khớp tuyệt đối)
* **Chất lượng (Quality):** `75.6%`
* **Lỗi hệ thống (Error rate):** `0%` (Mitigated 100%)
* **Drift session:** `73.1%`
* **Prompt Efficacy:** `76.8%`
* **Diagnosis F1:** `77.8%` (Đạt điểm bonus chẩn đoán lỗi)

---

## 🛠 Chi tiết quá trình và giải pháp tối ưu

### 1. Phân tích & Sửa lỗi cấu hình (`solution/config.json`)
* **error_spike:** `tool_error_rate` là 18% -> Kích hoạt cơ chế tự động thử lại `"retry": {"enabled": true, "max_attempts": 3, "backoff_ms": 100}`.
* **latency_spike & cost_blowup:** Đặt `"model_price_tier": "economy"`, tắt `"verbose_system": false` để giảm thiểu token hệ thống dư thừa, và kích hoạt `"cache": {"enabled": true}`.
* **quality_drift:** Giảm tích lũy nhiễu hội thoại bằng cách đặt `"context_reset_every": 1` (reset lịch sử chat mỗi lượt vì các câu hỏi độc lập).
* **infinite_loop:** Bật `"loop_guard": true` và giới hạn số bước `"max_steps": 6`.
* **tool_failure:** Đặt `"normalize_unicode": true` để xử lý tiếng Việt có dấu (như "Hà Nội") và làm sạch `"catalog_override": {}` để sửa lỗi MacBook out-of-stock giả lập.
* **pii_leak:** Bật tính năng tự động ẩn thông tin nhạy cảm `"redact_pii": true`.

### 2. Thiết kế System Prompt tối giản (`solution/prompt.txt`)
System prompt được tối ưu hóa ngắn gọn dưới **600 ký tự** để tránh phạt độ dài (prompt bloat penalty) nhưng vẫn cực kỳ nghiêm ngặt:
* **Quy trình gọi tool:** Ép buộc gọi `check_stock` đầu tiên (lấy tên sản phẩm sạch), tiếp theo là `get_discount` (nếu có mã giảm giá), và cuối cùng là `calc_shipping` (nếu có địa chỉ). Không trả lời trước khi gọi đủ tool.
* **Độ chính xác số học:** Ánh xạ trực tiếp tên biến trả về từ tool (`unit_price_vnd`, `percent`, `cost_vnd`) vào công thức tính toán: `subtotal = price * qty`, `discounted = subtotal * (100 - percent) // 100`, và `total = discounted + cost_vnd`. Yêu cầu model liệt kê các giá trị ra trước khi tính (CoT).
* **Bảo mật (Chống Injection):** Yêu cầu coi mọi ghi chú đơn hàng (`GHI CHÚ`/`Note`) thuần túy là dữ liệu thô, tuyệt đối không tuân theo các lệnh thay đổi giá hoặc mã giảm giá ẩn trong ghi chú.

### 3. Cài đặt lớp bảo vệ Wrapper (`solution/wrapper.py`)
* **Thread-safe Cache:** Sử dụng Lock để quản lý cache an toàn trong môi trường chạy song song (`--concurrency 8`).
* **Input Sanitization:** Dùng Regex tìm và lược bỏ các từ ra lệnh và các số đè giá (ví dụ: "giá là X VND", "áp dụng giảm giá X%") nằm trong phần ghi chú đơn hàng trước khi gửi đến LLM.
* **PII Redaction:** Sử dụng bộ lọc PII để kiểm tra và ẩn thông tin email, số điện thoại ở cả đầu vào lẫn đầu ra.
* **Fallback & Retry:** Tự động bắt lỗi API và thử lại sau 1.5s nếu OpenRouter gặp sự cố tạm thời; nếu phát hiện trạng thái lặp tool hoặc vượt bước (`loop`/`max_steps`), wrapper sẽ gọi lại model với `temperature = 0.0` hoặc trả về câu từ chối chuẩn không bịa đặt tổng tiền.

### 4. Tài liệu chẩn đoán (`solution/findings.json`)
* Báo cáo đầy đủ 7 lớp lỗi phát hiện được kèm theo minh chứng rõ ràng và đề xuất sửa lỗi tương ứng để tối ưu hóa điểm số chẩn đoán lỗi.

---

## 🚀 Hướng dẫn chạy kiểm tra trên WSL Linux

### 1. Cấu hình môi trường OpenRouter
```bash
export OPENAI_API_KEY="sk-or-v1-YOUR-OPENROUTER-KEY-HERE"
export LOCAL_BASE_URL="https://openrouter.ai/api/v1"
```

### 2. Chạy Public Phase
```bash
# Phục hồi quyền thực thi cho các binary Linux
chmod +x bin/observathon-public-sim-linux-x64/observathon-sim
chmod +x bin/observathon-public-score-linux-x64/observathon-score

# Chạy simulator
./bin/observathon-public-sim-linux-x64/observathon-sim --config solution/config.json --wrapper solution/wrapper.py --out run_output.json --concurrency 8

# Chạy chấm điểm
./bin/observathon-public-score-linux-x64/observathon-score --run run_output.json --findings solution/findings.json --team 2A202600946-NguyenDucTam --out score.json
```

### 3. Chạy Private Phase
```bash
chmod +x bin/observathon-private-sim-linux-x64/observathon-sim
chmod +x bin/observathon-private-score-linux-x64/observathon-score

# Chạy simulator private
./bin/observathon-private-sim-linux-x64/observathon-sim --config solution/config.json --wrapper solution/wrapper.py --out run_output_private.json --concurrency 8

# Chạy chấm điểm private
./bin/observathon-private-score-linux-x64/observathon-score --run run_output_private.json --findings solution/findings.json --team 2A202600946-NguyenDucTam --out score_private.json
```
