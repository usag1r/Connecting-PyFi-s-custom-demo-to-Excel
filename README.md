# CSV → Excel Report Builder (with Summary + Charts)

This script converts labeled transaction data from CSV into a multi-sheet Excel report with summaries and charts.

It **builds on PyFi’s Python demo**, extending it into a full reporting pipeline that exports a polished Excel workbook with embedded visualizations and summary statistics.

---

## Background

PyFi’s Python demo focuses on extracting and labeling financial transaction data.  
This project takes the **output of that demo** and produces a stakeholder-ready Excel report:

- Raw labeled data
- Human-readable summaries
- Embedded chart images
- Native Excel charts built directly from the data

This makes it suitable for finance, ops, or audit-style reporting workflows.

---

## What it generates

Output workbook (example: `labeled_data.xlsx`) includes:

### 1) `labeled_data`
Full import of `labeled_data.csv` produced by the PyFi demo pipeline.

### 2) `Summary`
If these files exist, they are added as formatted sections:
- `summary.csv`  
  - expected column: `Summary`
- `summary_stats.csv`  
  - expected columns: `Metric`, `Value`

### 3) `Charts`
Embeds pre-rendered PNG charts:
- `spending_by_spender.png`
- `spending_by_category.png`
- `spending_by_vendor.png`

Charts are scaled and positioned side-by-side with titles.

### 4) `Native Charts`
Creates Excel-native charts from aggregated data:
- Pie — Spending by Spender
- Pie — Spending by Category
- Bar (top 15) — Spending by Vendor

All charts are generated directly inside Excel using `openpyxl`.

---

## Input expectations

### Required
- `labeled_data.csv` (from PyFi demo output)

Expected columns:
- `amount`
- `spender`
- `category`
- `vendor`

### Optional
- `summary.csv`
- `summary_stats.csv`
- PNG chart files listed above

---

## Installation

```bash
pip install pandas openpyxl



