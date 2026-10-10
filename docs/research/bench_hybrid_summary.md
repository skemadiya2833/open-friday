# Hybrid agent (a11y tree first, vision fallback), qwen2.5vl:7b-q4_K_M

1 rep per task, same ctx 32768 / 15 steps / 120 s as the baseline. Raw: bench_hybrid_qwen25vl_1rep.json. An earlier 10-run partial (3 reps, bench_hybrid_qwen25vl.json) was stopped by emergency-stop key presses and is not used in the comparison.

| task | group | pass | steps (mean) | wall s (mean) | peak VRAM MB | top failure |
|---|---|---|---|---|---|---|
| notepad_open | notepad | 1/1 | 1.0 | 10 | 9157 |  |
| notepad_type_save | notepad | 0/1 | 3.0 | 20 | 9159 | agent failed: see actions; file missing: n2.txt |
| notepad_two_lines | notepad | 0/1 | 4.0 | 24 | 9154 | agent failed: see actions; file missing: n3.txt |
| notepad_save_and_close | notepad | 0/1 | 15.0 | 81 | 9153 | agent max_iterations but check failed: file missing: n4.txt; Notepad s |
| notepad_subfolder | notepad | 0/1 | 8.0 | 45 | 9155 | agent failed: see actions; file missing: n5.txt |
| notepad_edit | notepad | 0/1 | 3.0 | 18 | 9155 | agent failed: see actions; file missing: n6.txt |
| calc_open | calculator | 1/1 | 1.0 | 9 | 9152 |  |
| calc_add | calculator | 0/1 | 3.0 | 18 | 9221 | agent failed: see actions; display was 'Display is 21,212', wanted ... |
| calc_mul | calculator | 0/1 | 9.0 | 47 | 9220 | agent failed: see actions; display was 'Display is 59,906', wanted ... |
| calc_div | calculator | 0/1 | 9.0 | 52 | 9220 | agent failed: see actions; display was 'Display is 1,14,41,44,14,41,44 |
| explorer_open_folder | explorer | 1/1 | 15.0 | 96 | 9262 |  |
| explorer_new_folder | explorer | 0/1 | 6.0 | 55 | 9288 | agent failed: see actions; folder not created |
| explorer_subfolder | explorer | 0/1 | 3.0 | 20 | 9289 | agent failed: see actions; no Explorer window titled 'sub' |
| explorer_new_textfile | explorer | 0/1 | 5.0 | 33 | 9260 | agent failed: see actions; file not created |
| settings_open | settings | 1/1 | 1.0 | 9 | 9283 |  |
| settings_about | settings | 1/1 | 4.0 | 21 | 9291 |  |
| settings_display | settings | 1/1 | 15.0 | 64 | 9295 |  |
| chrome_counter | chrome | 0/1 | 1.0 | 17 | 9306 | agent failed: see actions; fewer than 3 clicks; saw [] |
| chrome_form | chrome | 0/1 | 1.0 | 18 | 9341 | agent failed: see actions; name was not Friday; saw [] |
| chrome_select | chrome | 0/1 | 0.0 | 7 | 9104 | agent failed: see actions; wrong color/agree; saw [] |
| chrome_scroll | chrome | 0/1 | 2.0 | 20 | 9111 | agent failed: see actions; bottom button not clicked; saw [] |
| chrome_navigate | chrome | 0/1 | 0.0 | 7 | 9112 | agent failed: see actions; confirm not clicked; saw [] |
| canvas_click_red | canvas | 0/1 | 0.0 | 7 | 9123 | agent failed: see actions; red circle not hit; saw [] |
| canvas_blue_then_red | canvas | 0/1 | 0.0 | 7 | 9123 | agent failed: see actions; wrong order; saw [] |
| canvas_drag | canvas | 0/1 | 0.0 | 7 | 9123 | agent failed: see actions; drag did not connect the dots; saw [] |
| canvas_game | canvas | 0/1 | 0.0 | 7 | 9123 | agent failed: see actions; fewer than 3 hits; saw [] |

Overall: 6/26 runs passed (23%).
