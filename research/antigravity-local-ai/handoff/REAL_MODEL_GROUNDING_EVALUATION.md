# SOGH Antigravity: Real Model Physical Grounding Evaluation Report

- **Timestamp**: `2026-11-07T22:59:29+0900`
- **Hardware**: `AMD Ryzen 5 3550H / ASUS TUF Gaming FX505DY`
- **Model**: `Qwen3-1.7B-Q4_K_M.gguf`
- **Available RAM**: `3362.2 MB`
- **Cases Evaluated**: `2`

## Evaluated Cases

| Case ID | Topic | Inference Time | Grounding Verdict | Quarantined | Safety Status |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `TSUKUBA_FAQ_101_SUBMISSION_METHOD` | 出願書類の提出方法 | 12.73s | `CONTRADICTION` | `True` | **QUARANTINED_BLOCKED** |
| `TSUKUBA_FAQ_102_YEAR_SCHEDULE` | 選抜日程・締切日 | 12.9s | `CONTRADICTION` | `True` | **QUARANTINED_BLOCKED** |

## Detailed Responses and Citations

### TSUKUBA_FAQ_101_SUBMISSION_METHOD: 出願書類の提出方法
- **Heading**: 出願書類の提出方法について
- **Generated Answer**: `【公式情報】
出願書類は、出願期間内に書留・速達郵便にて送付してください。持参による提出は受け付けません。

【質問】
出願書類の提出方法について



[Start thinking]

Okay, the user is asking about the submission method for the application documents. Let me check the offi`
- **Verdict Reason**: Quotation diverges from verified official text

### TSUKUBA_FAQ_102_YEAR_SCHEDULE: 選抜日程・締切日
- **Heading**: 2026年度選抜における出願締切日
- **Generated Answer**: `【公式情報】
2026年度選抜の出願締切は11月5日消印有効です。

【質問】
2026年度選抜における出願締切日



[Start thinking]

Okay, the user is asking about the application deadline for the 2026 entrance exam at Waseda University. From the provide`
- **Verdict Reason**: Quotation diverges from verified official text
