# Customer Meter Photo QA - Project Plan

## Problem

Customer collection will create tens of thousands of records. Manually opening every photo and comparing its visible meter number with `MeterNumber` is not scalable.

The live model already contains 57,975 LV Service-Meter objects. A production checker must therefore process only new or edited records, batch service requests, cache attachment metadata, and send uncertain cases to a human review queue.

## Proposed architecture

| Component | Responsibility |
|---|---|
| ArcGIS Pro Python toolbox | Start a scan, choose a date/filter, and open the output report |
| ArcGIS inventory adapter | Read meter objects, linked service points, and attachment metadata |
| Local photo cache | Temporarily store approved image attachments during OCR |
| OCR worker | Detect one or more candidate meter numbers and confidence scores |
| Comparison engine | Normalize conservatively and decide PASS, REVIEW, or FAIL |
| Audit output | CSV first; later a dedicated QA table/dashboard if administrators approve it |
| Scheduler | Run incremental scans after collection begins |

## Milestones

### M1 - Model discovery and preflight inventory - complete

- Confirmed LV Service-Meter subtype and fields.
- Confirmed attachment capability on meter objects and parent service points.
- Built the read-only ArcGIS Pro toolbox.
- Built deterministic comparison and status rules.
- Tested against live DEFAULT without editing it.

### M2 - Representative photo set

- Identify 50-100 records with actual meter photos.
- Include clear, blurred, angled, dark, reflective, and partially covered meters.
- Include the main meter brands and number lengths.
- Remove unrelated customer-identifying content from test copies where practical.
- Label the correct visible meter number for each test photo.

### M3 - OCR benchmark

- Test RapidOCR/ONNX locally first.
- Measure exact-match accuracy, character error rate, unreadable rate, and processing time.
- Test image rotation, crop detection, contrast improvement, and glare handling.
- Keep OCR confusion matches in REVIEW, never automatic PASS.

### M4 - Production-quality scanner

- Query only records edited since the previous successful run.
- Paginate records and attachments safely.
- Retry transient service errors without duplicating audit rows.
- Delete temporary images after processing.
- Resume interrupted runs from a checkpoint.

### M5 - Team review workflow

- Produce a review table with photo preview, entered number, detected number, confidence, and reason.
- Allow reviewers to confirm the entered value, confirm the OCR value, or mark the photo unusable.
- Keep any UN Model write-back disabled until administrators approve fields/domains and permissions.

## Acceptance targets for OCR pilot

| Measure | Initial target |
|---|---|
| High-confidence automatic PASS precision | At least 99.5% |
| False automatic PASS | 0 in the labelled pilot set |
| Photos routed to human review | Acceptable even if high during the first pilot |
| Missing-photo detection | 100% |
| Missing-MeterNumber detection | 100% |
| UN Model edits during development | 0 |

## Decisions still needed

1. Confirm where the field collection form will store meter photos: meter object, parent service point, or one enforced location.
2. Provide a small approved photo sample with known correct meter numbers.
3. Decide whether the final result remains an external report or is written to an administrator-approved QA table.
4. Decide how often production monitoring should run: on demand, hourly, or nightly.
