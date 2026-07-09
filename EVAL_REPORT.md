# Eval Report

Generated from `data/eval_results.csv`. Domains scored: 30. Crashes: 0.

## Per-Field Accuracy

| Field | Scored | Hits | Accuracy |
|---|---|---|---|
| canonical_org_name | 27 | 23 | 85% |
| hq_phone | 26 | 21 | 81% |
| hq_address | 26 | 21 | 81% |
| recruitment_phone | 25 | 25 | 100% |
| location_count | 26 | 17 | 65% |
| site_type | 26 | 21 | 81% |
| research_url | 24 | 22 | 92% |
| trials_status | 0 | 0 | n/a |

## Top 5 Disagreements Per Field

### canonical_org_name

| Domain | Expected | Actual | Note |
|---|---|---|---|
| cardiorenalinstitute.com | CARE Cardio Renal Institue | Cardiorenal Institute | 'care cardio renal institue' not in 'cardiorenal institute' and vice versa |
| amrconventions.com | AMR Convention Research | AMR Conventions Research LTD | 'amr convention research' not in 'amr conventions research ltd' and vice versa |
| cvillemedresearch.com | Charlotteville Medical Research | Charlottesville Medical Research | 'charlotteville medical research' not in 'charlottesville medical research' and  |
| cra-al.biz | Clinical Research Associates |  | actual is empty |

### hq_phone

| Domain | Expected | Actual | Note |
|---|---|---|---|
| qualityresearch.com | (210) 824-5678 | +12108221003 | expected digits '2108245678', got '2108221003' |
| vitaliscrc.com | 313-887-4536 |  | actual is empty |
| acuroresearch.com | 501) 224-1156 X7-5555 | +15012241156 | expected digits '4115675555', got '5012241156' |
| cra-al.biz | (256) 536-6600 |  | actual is empty |
| palmettoclinical.com | 864-214-1217 |  | actual is empty |

### hq_address

| Domain | Expected | Actual | Note |
|---|---|---|---|
| equity-med.com | 200 Amsterdam Ave. New York, NY 10023 |  | actual is empty |
| vitaliscrc.com | 7445 Allen Road, Suite 260 Allen Park, MI 48101 |  | actual is empty |
| bostonneuroresearch.com | 237a State Rd, North Dartmouth, MA 02747, USA |  | actual is empty |
| cra-al.biz | 131 Longwood Drive Huntsville, AL 35801 |  | actual is empty |
| palmettoclinical.com | 37 Brendan Way Greenville, SC 29615 |  | actual is empty |

### recruitment_phone
No misses. ✅

### location_count

| Domain | Expected | Actual | Note |
|---|---|---|---|
| gulfsouthclinicaltrials.org | 20+ | 50+ | expected tokens ['20+'], got ['50+'] |
| equity-med.com | 5 | 3 | expected tokens ['5'], got ['3'] |
| cardiorenalinstitute.com | 8 | 7 | expected tokens ['8'], got ['7'] |
| cibmtr.org | 1 | 2 | expected tokens ['1'], got ['2'] |
| nextstageclinical.com | 19 | 18 | expected tokens ['19'], got ['18'] |

### site_type

| Domain | Expected | Actual | Note |
|---|---|---|---|
| gulfsouthclinicaltrials.org | embedded | dedicated | expected 'embedded', got 'dedicated' |
| cibmtr.org | unclear | dedicated | expected 'unclear', got 'dedicated' |
| nextstageclinical.com | embedded | dedicated | expected 'embedded', got 'dedicated' |
| investigativeicr.com | unclear | dedicated | expected 'unclear', got 'dedicated' |
| cra-al.biz | dedicated |  | actual is empty |

### research_url

| Domain | Expected | Actual | Note |
|---|---|---|---|
| biophaseresearch.com | https://www.instagram.com/biophaseresearch/ | https://biophaseresearch.com/ | 'instagram.com/biophaseresearch' vs 'biophaseresearch.com' |
| cra-al.biz | http://cra-al.biz/learn.html |  | actual is empty |

### trials_status
No misses. ✅

## Per-Domain Summary

| Domain | Fields Hit | Fields Missed | Fields Skipped |
|---|---|---|---|
| acuroresearch.com | 5 | 1 | 2 |
| amrconventions.com | 6 | 1 | 1 |
| bhccr.com | 7 | 0 | 1 |
| biophaseresearch.com | 6 | 1 | 1 |
| bostonneuroresearch.com | 6 | 1 | 1 |
| butchertownclinicaltrials.com | 7 | 0 | 1 |
| cardiorenalinstitute.com | 5 | 2 | 1 |
| cartainvestigators.com | 7 | 0 | 1 |
| centralstatesresearch.com | 6 | 0 | 2 |
| cibmtr.org | 5 | 2 | 1 |
| cra-al.biz | 1 | 6 | 1 |
| cvillemedresearch.com | 6 | 1 | 1 |
| equity-med.com | 5 | 2 | 1 |
| erahealthresearch.com | 7 | 0 | 1 |
| gulfsouthclinicaltrials.org | 3 | 2 | 3 |
| investigativeicr.com | 5 | 2 | 1 |
| jaclinicalresearch.com | 7 | 0 | 1 |
| lotuscr.com | 4 | 0 | 4 |
| mcrmed.com | 1 | 0 | 7 |
| mgmclinicalresearch.com | 7 | 0 | 1 |
| moallergy.com | 1 | 0 | 7 |
| nextstageclinical.com | 5 | 2 | 1 |
| omnicureresearch.com | 6 | 0 | 2 |
| palmettoclinical.com | 4 | 3 | 1 |
| qps.com | 0 | 0 | 8 |
| qualityresearch.com | 5 | 1 | 2 |
| redriverresearchpartners.com | 7 | 0 | 1 |
| tvcrtrials.com | 6 | 0 | 2 |
| viciscr.com | 7 | 0 | 1 |
| vitaliscrc.com | 3 | 3 | 2 |