# Patent Key Handoff

## What's Needed
A free PatentsView API key to unlock patent data in the pre-enrichment pipeline.

## Why It's Blocked
PatentsView migrated to `search.patentsview.org` in March 2026. The new endpoint requires a free API key. Without it, every patent lookup returns a 401 and `si_patent_filings` fills with "Patent lookup not run" for every company — 0% real evidence.

## How to Get It
1. Go to: **patentsview.org/apis/keyrequest**
2. Fill out the form (~5 min)
3. Key arrives by email

## How to Install It
Add to `/Users/enzoweiss/emolecules-analysis/.env`:
```
PATENTSVIEW_API_KEY=your_key_here
```

## How to Test It
```bash
cd /Users/enzoweiss/emolecules-analysis
python3 pre_enrichment.py --domain gilead.com
```
Look for `patents=N` in the output summary. If it shows a number, it's working.

## Then Run Full Batch
```bash
python3 pre_enrichment.py --from-json --limit 25
python3 run_batch_retest.py --limit 25
```
Check `si_patent_filings` evidence rate — expected to go from 0% → ~60%.

## Rate Limit
45 requests/min. The pipeline already has a 1.4s sleep between calls to stay under.
