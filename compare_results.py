"""
Compare Test A (holistic) vs Test B (categorical) results side by side.
Run this after both tests complete.

Usage: python3 compare_results.py
"""

import json

def load_results(path):
    with open(path) as f:
        data = json.load(f)
    return {r["domain"]: r for r in data["results"]}, data

def main():
    try:
        a_by_domain, a_data = load_results("results/test_a_results.json")
    except FileNotFoundError:
        print("ERROR: results/test_a_results.json not found. Run test_a_holistic.py first.")
        return

    try:
        b_by_domain, b_data = load_results("results/test_b_results.json")
    except FileNotFoundError:
        print("ERROR: results/test_b_results.json not found. Run test_b_categorical.py first.")
        return

    all_domains = sorted(set(list(a_by_domain.keys()) + list(b_by_domain.keys())))

    print(f"\n{'='*100}")
    print(f"TEST COMPARISON — A (Holistic) vs B (Categorical)")
    print(f"{'='*100}")
    print(f"\n{'Domain':<30} {'A Score':>8} {'A Status':<12} {'B Score':>8} {'B Status':<12} {'Delta':>6} {'Match':>6}")
    print(f"{'-'*30} {'-'*8} {'-'*12} {'-'*8} {'-'*12} {'-'*6} {'-'*6}")

    score_diffs = []
    status_matches = 0
    status_total = 0

    for domain in all_domains:
        a = a_by_domain.get(domain, {})
        b = b_by_domain.get(domain, {})

        a_score = a.get("icp_score", "N/A")
        b_score = b.get("icp_score", "N/A")
        a_status = a.get("qualification_status", "N/A")
        b_status = b.get("qualification_status", "N/A")

        if isinstance(a_score, (int, float)) and isinstance(b_score, (int, float)):
            delta = b_score - a_score
            score_diffs.append(abs(delta))
            delta_str = f"{delta:+d}"
        else:
            delta_str = "N/A"

        if a_status != "N/A" and b_status != "N/A":
            status_total += 1
            match = "Y" if a_status == b_status else "N"
            if a_status == b_status:
                status_matches += 1
        else:
            match = "-"

        print(f"{domain:<30} {str(a_score):>8} {a_status:<12} {str(b_score):>8} {b_status:<12} {delta_str:>6} {match:>6}")

    # Summary stats
    print(f"\n{'='*100}")
    print(f"SUMMARY")
    print(f"{'='*100}")
    print(f"\n  Test A (Holistic):")
    print(f"    Total API calls: {a_data.get('total_api_calls', 'N/A')}")
    for k, v in a_data.get("summary", {}).items():
        print(f"    {k}: {v}")

    print(f"\n  Test B (Categorical):")
    print(f"    Total API calls: {b_data.get('total_api_calls', 'N/A')}")
    for k, v in b_data.get("summary", {}).items():
        print(f"    {k}: {v}")

    if score_diffs:
        print(f"\n  Score Comparison:")
        print(f"    Avg absolute score difference: {sum(score_diffs)/len(score_diffs):.1f} points")
        print(f"    Max score difference: {max(score_diffs)} points")
        print(f"    Status agreement rate: {status_matches}/{status_total} ({100*status_matches/status_total:.0f}%)")

        # Flag big disagreements
        big_diffs = []
        for domain in all_domains:
            a = a_by_domain.get(domain, {})
            b = b_by_domain.get(domain, {})
            a_score = a.get("icp_score")
            b_score = b.get("icp_score")
            if isinstance(a_score, (int, float)) and isinstance(b_score, (int, float)):
                if abs(a_score - b_score) >= 20:
                    big_diffs.append((domain, a_score, b_score, a.get("qualification_status"), b.get("qualification_status")))

        if big_diffs:
            print(f"\n  LARGE DISAGREEMENTS (20+ point diff):")
            for domain, a_s, b_s, a_st, b_st in sorted(big_diffs, key=lambda x: abs(x[1]-x[2]), reverse=True):
                print(f"    {domain}: A={a_s} ({a_st}) vs B={b_s} ({b_st}) [delta={b_s-a_s:+d}]")

                # Show reasoning from both
                a_reasoning = a_by_domain[domain].get("reasoning", "N/A")
                b_evidence = b_by_domain[domain].get("key_evidence", [])[:3]
                print(f"      A reasoning: {a_reasoning[:120]}")
                if b_evidence:
                    print(f"      B evidence: {'; '.join(str(e) for e in b_evidence[:3])[:120]}")

    print()


if __name__ == "__main__":
    main()
