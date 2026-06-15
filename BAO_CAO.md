# Báo cáo Observathon — PhamHoangAnh

**Mục tiêu:** Sửa agent e-commerce hộp đen qua `config.json`, `prompt.txt`, `wrapper.py`, `findings.json`.

**Config:** `economy` tier, `verbose_system=false`, `context_size=2`, `self_consistency=2`, bật retry/cache/redact.

**Prompt (~600 ký tự):** Tool đúng thứ tự, công thức `// 100`, phân biệt hỏi giá vs đặt hàng, chống injection GHI CHÚ.

**Wrapper (fix chính):** Chuẩn hóa tên thành phố, strip PII, sanitize ghi chú; **`synthesize_answer()`** tính `Tong cong` từ trace tool thay vì tin output LLM.

**Kết quả:** Public **100.0/100** (99/120) · Private **98.12/100** (50/80).

**Chạy:** `sim` → `run_output.json` (cần API key) · `score` → `score.json` (private: `observathon-score --phase private` ở root `task_ai/`).
