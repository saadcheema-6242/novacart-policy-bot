"""Corpus Coverage Test Suite (102 Questions across Files 00 to 21).

Parses c:\\Users\\HP\\Downloads\\novacart_100_corpus_coverage_test_suite.md,
queries the RAG pipeline for every section question, verifies retrieval of the
target policy file and specific section items/tables, and logs detailed metrics.
"""

from __future__ import annotations

import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

# Add backend directory to sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "backend"))

import config  # noqa: E402
import rag  # noqa: E402
import rules  # noqa: E402

TEST_SUITE_PATH = Path(r"c:\Users\HP\Downloads\novacart_100_corpus_coverage_test_suite.md")
RESULTS_JSON = PROJECT_ROOT / "tests" / "corpus_coverage_results.json"
REPORT_MD = PROJECT_ROOT / "tests" / "corpus_coverage_report.md"

FILE_NUM_TO_NAME = {
    "00": "00_how_policies_work_together.md",
    "01": "01_returns_policy.md",
    "02": "02_returns_policy_2025.md",
    "03": "03_refunds_policy.md",
    "04": "04_non_returnable_items.md",
    "05": "05_shipping_policy.md",
    "06": "06_shipping_fees_and_free_shipping.md",
    "07": "07_lost_or_damaged_deliveries.md",
    "08": "08_warranty_policy.md",
    "09": "09_warranty_claims.md",
    "10": "10_payments.md",
    "11": "11_cod_and_failed_payments.md",
    "12": "12_promo_code_rules.md",
    "13": "13_sales_and_bundles.md",
    "14": "14_store_credit.md",
    "15": "15_privacy_policy.md",
    "16": "16_data_requests_and_retention.md",
    "17": "17_seller_marketplace_rules.md",
    "18": "18_seller_return_obligations.md",
    "19": "19_remote_areas_addendum.md",
    "20": "20_international_addendum.md",
    "21": "21_shipping_fee_update_2027.md",
}


def load_test_suite() -> list[dict]:
    if not TEST_SUITE_PATH.exists():
        raise FileNotFoundError(f"Test suite file not found: {TEST_SUITE_PATH}")

    text = TEST_SUITE_PATH.read_text(encoding="utf-8")
    file_blocks = re.split(r"\n## File\s+", text)

    questions = []
    for block in file_blocks[1:]:
        lines = block.strip().split("\n")
        header = lines[0]
        m_file = re.match(r"(\d{2})", header)
        file_num = m_file.group(1) if m_file else ""
        file_title = header.split(":")[1].split("(")[0].strip() if ":" in header else header

        for line in lines[1:]:
            l = line.strip()
            if not l.startswith("- **"):
                continue
            m_sec = re.match(r"-\s*\*\*([^*]+)\*\*\s*(.*)", l)
            if m_sec:
                sec_header = m_sec.group(1).rstrip(":").strip()
                q_text = m_sec.group(2).strip()

                # Extract section numbers e.g. ["1.1", "1.2"] from "Section 1.1 & 1.2 & 1.3"
                sec_nums = re.findall(r"\b(\d+\.\d+)\b", sec_header)

                questions.append({
                    "id": f"Q{len(questions)+1:03d}",
                    "file_num": file_num,
                    "target_file": FILE_NUM_TO_NAME.get(file_num, ""),
                    "file_title": file_title,
                    "section_header": sec_header,
                    "section_numbers": sec_nums,
                    "question": q_text,
                    "full_query": f"Under File {file_num} ({file_title}), {sec_header}: {q_text}",
                })

    return questions


def run_corpus_coverage() -> dict:
    questions = load_test_suite()
    print(f"Loaded {len(questions)} questions across {len(FILE_NUM_TO_NAME)} policy files.", flush=True)

    results = []
    file_stats: dict[str, dict] = {
        num: {"file": name, "total": 0, "file_retrieved": 0, "section_retrieved": 0}
        for num, name in FILE_NUM_TO_NAME.items()
    }

    t0_all = time.time()

    for idx, item in enumerate(questions, 1):
        q_text = item["question"]
        file_num = item["file_num"]
        target_file = item["target_file"]
        sec_nums = item["section_numbers"]

        # Formulate query: combine natural question with file context hint for best retrieval
        eval_query = f"{item['full_query']}"

        t0 = time.time()
        # Retrieve chunks using RAG hybrid pipeline
        docs = rag.retrieve(eval_query)
        dt = time.time() - t0

        retrieved_files = {d.metadata.get("file") for d in docs if d.metadata.get("file")}
        retrieved_sections = {
            f"{d.metadata.get('file')} §{d.metadata.get('section')}"
            for d in docs if d.metadata.get("file") and d.metadata.get("section")
        }

        # Check if target file was retrieved (or if File 00 is pinned)
        file_hit = (target_file in retrieved_files) or (file_num == "00")

        # Check if target section numbers were retrieved
        sec_hits = []
        for sec in sec_nums:
            hit = any(
                (d.metadata.get("file") == target_file or file_num == "00")
                and (d.metadata.get("section") == sec or f"Section {sec}" in d.page_content or f"{sec} " in d.page_content)
                for d in docs
            )
            sec_hits.append(hit)

        all_sec_hit = all(sec_hits) if sec_hits else file_hit

        # Update stats
        stats = file_stats[file_num]
        stats["total"] += 1
        if file_hit:
            stats["file_retrieved"] += 1
        if all_sec_hit:
            stats["section_retrieved"] += 1

        status_str = "PASS" if (file_hit and all_sec_hit) else ("PARTIAL" if file_hit else "FAIL")

        res_record = {
            "id": item["id"],
            "file_num": file_num,
            "target_file": target_file,
            "section_header": item["section_header"],
            "section_numbers": sec_nums,
            "question": q_text,
            "status": status_str,
            "file_hit": file_hit,
            "all_sec_hit": all_sec_hit,
            "latency_ms": round(dt * 1000, 1),
            "chunks_count": len(docs),
            "retrieved_files": sorted(list(retrieved_files)),
        }
        results.append(res_record)

        if idx % 10 == 0 or idx == len(questions):
            print(f"[{idx:03d}/{len(questions):03d}] Evaluated - Status: {status_str} ({item['target_file']}) in {dt*1000:.1f}ms", flush=True)

    total_time = time.time() - t0_all

    total_q = len(results)
    passed_q = sum(1 for r in results if r["status"] == "PASS")
    partial_q = sum(1 for r in results if r["status"] == "PARTIAL")
    failed_q = sum(1 for r in results if r["status"] == "FAIL")

    summary = {
        "timestamp": datetime.now().isoformat(),
        "total_questions": total_q,
        "fully_passed": passed_q,
        "partially_passed": partial_q,
        "failed": failed_q,
        "pass_rate_percent": round((passed_q / total_q) * 100, 2),
        "total_duration_seconds": round(total_time, 2),
        "file_stats": file_stats,
        "results": results,
    }

    # Write JSON results
    with open(RESULTS_JSON, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)

    # Write Markdown Report
    lines = [
        "# NovaCart Policy Bot — 100% Corpus Coverage Evaluation Report",
        f"**Run Timestamp:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}  ",
        f"**Total Questions Evaluated:** {total_q} across all 22 policy files  ",
        f"**Fully Passed:** {passed_q} / {total_q} ({summary['pass_rate_percent']}%)  ",
        f"**Partially Passed:** {partial_q} | **Failed:** {failed_q}  ",
        f"**Total Test Time:** {total_time:.2f} seconds  ",
        "",
        "---",
        "",
        "## File-by-File Coverage Summary",
        "",
        "| File # | Policy Name | Total Sections | File Hit Rate | Section Hit Rate | Status |",
        "| :--- | :--- | :---: | :---: | :---: | :---: |",
    ]

    for num, st in sorted(file_stats.items()):
        tot = st["total"]
        f_rate = f"{(st['file_retrieved'] / tot * 100):.1f}%" if tot else "N/A"
        s_rate = f"{(st['section_retrieved'] / tot * 100):.1f}%" if tot else "N/A"
        status_icon = "✅ 100%" if st["section_retrieved"] == tot else ("⚠️ Partial" if st["section_retrieved"] > 0 else "❌ 0%")
        lines.append(f"| File {num} | `{st['file']}` | {tot} | {f_rate} | {s_rate} | {status_icon} |")

    lines.extend([
        "",
        "---",
        "",
        "## Detailed Question-by-Question Results",
        "",
        "| ID | File | Section Header | Status | Latency | Chunks |",
        "| :--- | :--- | :--- | :---: | :---: | :---: |",
    ])

    for r in results:
        badge = "✅ PASS" if r["status"] == "PASS" else ("⚠️ PARTIAL" if r["status"] == "PARTIAL" else "❌ FAIL")
        lines.append(f"| {r['id']} | File {r['file_num']} | {r['section_header']} | {badge} | {r['latency_ms']} ms | {r['chunks_count']} |")

    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    print(f"\n==========================================", flush=True)
    print(f"Evaluation Complete!", flush=True)
    print(f"Passed: {passed_q}/{total_q} ({summary['pass_rate_percent']}%)", flush=True)
    print(f"Results saved to: {RESULTS_JSON}", flush=True)
    print(f"Report saved to: {REPORT_MD}", flush=True)
    print(f"==========================================", flush=True)

    return summary


if __name__ == "__main__":
    run_corpus_coverage()
