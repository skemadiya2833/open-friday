# Baseline: legacy vision loop, qwen2.5vl:7b-q4_K_M

ctx 32768, max-iter 15, per-run timeout 120 s, 26 tasks x 3 runs, run 2026-10-06 (12:00-14:30). Raw data: bench_baseline_legacy_qwen25vl.json.

| task | group | pass | steps (mean) | wall s (mean) | peak VRAM MB | top failure |
|---|---|---|---|---|---|---|
| notepad_open | notepad | 1/3 | 4.0 | 73 | 9470 | timeout after 120s; no Notepad window |
| notepad_type_save | notepad | 0/3 | 3.0 | 60 | 9622 | agent failed: see actions; file missing: n2.txt |
| notepad_two_lines | notepad | 0/3 | 10.3 | 122 | 9668 | timeout after 120s; file missing: n3.txt |
| notepad_save_and_close | notepad | 0/3 | 9.0 | 121 | 9667 | timeout after 120s; file missing: n4.txt |
| notepad_subfolder | notepad | 0/3 | 10.0 | 122 | 9667 | timeout after 120s; file missing: n5.txt |
| notepad_edit | notepad | 0/3 | 8.0 | 121 | 9670 | timeout after 120s; file missing: n6.txt |
| calc_open | calculator | 2/3 | 6.0 | 92 | 9661 | timeout after 120s; no Calculator window |
| calc_add | calculator | 0/3 | 9.3 | 121 | 9660 | timeout after 120s; display was 'Display is 0 point', wanted ...42 |
| calc_mul | calculator | 0/3 | 8.7 | 121 | 9660 | timeout after 120s; display was 'Display is 5', wanted ...56 |
| calc_div | calculator | 0/3 | 9.0 | 122 | 9661 | timeout after 120s; display was 'Display is 0', wanted ...12 |
| explorer_open_folder | explorer | 0/3 | 9.3 | 122 | 9379 | timeout after 120s; no Explorer window titled 'explorer_open_folder_1' |
| explorer_new_folder | explorer | 0/3 | 9.7 | 122 | 9379 | timeout after 120s; folder not created |
| explorer_subfolder | explorer | 0/3 | 9.3 | 111 | 9379 | timeout after 120s; no Explorer window titled 'sub' |
| explorer_new_textfile | explorer | 0/3 | 9.0 | 121 | 9450 | timeout after 120s; file not created |
| settings_open | settings | 2/3 | 10.0 | 124 | 9463 | timeout after 120s; no Settings window |
| settings_about | settings | 0/3 | 9.0 | 122 | 9473 | timeout after 120s; no Settings window |
| settings_display | settings | 0/3 | 8.7 | 121 | 9478 | timeout after 120s; no Settings window |
| chrome_counter | chrome | 0/3 | 10.3 | 124 | 9470 | timeout after 120s; fewer than 3 clicks; saw [] |
| chrome_form | chrome | 0/3 | 9.7 | 126 | 9474 | timeout after 120s; name was not Friday; saw [] |
| chrome_select | chrome | 0/3 | 8.7 | 126 | 9477 | timeout after 120s; wrong color/agree; saw [{'token': 'chrome_select-1 |
| chrome_scroll | chrome | 0/3 | 1.0 | 39 | 9475 | agent failed: see actions; bottom button not clicked; saw [] |
| chrome_navigate | chrome | 0/3 | 8.7 | 125 | 9475 | timeout after 120s; confirm not clicked; saw [] |
| canvas_click_red | canvas | 0/3 | 9.0 | 124 | 9478 | timeout after 120s; red circle not hit; saw [{'token': 'canvas_click_r |
| canvas_blue_then_red | canvas | 0/3 | 8.7 | 124 | 9478 | timeout after 120s; wrong order; saw [{'token': 'canvas_blue_then_red- |
| canvas_drag | canvas | 0/3 | 11.0 | 124 | 9478 | timeout after 120s; drag did not connect the dots; saw [] |
| canvas_game | canvas | 0/3 | 9.7 | 124 | 9478 | timeout after 120s; fewer than 3 hits; saw [{'token': 'canvas_game-1-1 |

Overall: 5/78 runs passed (6%).
