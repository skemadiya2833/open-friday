# legacy vs hybrid

Compared tasks (complete in both): **16**. Aborted runs excluded: legacy 1, hybrid 0.

Not compared:
- canvas_blue_then_red: legacy: not run; hybrid: ok
- canvas_click_red: legacy: not run; hybrid: ok
- canvas_drag: legacy: not run; hybrid: ok
- canvas_game: legacy: not run; hybrid: ok
- chrome_counter: legacy: not run; hybrid: ok
- chrome_form: legacy: not run; hybrid: ok
- chrome_navigate: legacy: not run; hybrid: ok
- chrome_scroll: legacy: not run; hybrid: ok
- chrome_select: legacy: not run; hybrid: ok
- settings_display: legacy: 1 aborted run(s) discarded; hybrid: ok

| task | group | legacy | hybrid | steps legacy/hybrid | wall s legacy/hybrid |
|---|---|---|---|---|---|
| calc_add | calculator | 0/3 | 0/3 | 9.3/9.0 | 122/48 |
| calc_div | calculator | 0/3 | 0/3 | 8.3/14.7 | 120/77 |
| calc_mul | calculator | 0/3 | 0/3 | 9.3/15.0 | 120/73 |
| calc_open | calculator | 0/3 | 3/3 | 9.0/1.0 | 120/9 |
| explorer_new_folder | explorer | 0/3 | 0/3 | 8.0/12.3 | 122/80 |
| explorer_new_textfile | explorer | 0/3 | 0/3 | 8.0/9.0 | 121/58 |
| explorer_open_folder | explorer | 0/3 | 1/3 | 9.0/3.3 | 121/25 |
| explorer_subfolder | explorer | 0/3 | 1/3 | 8.3/6.0 | 120/38 |
| notepad_edit | notepad | 0/3 | 0/3 | 7.7/7.0 | 121/40 |
| notepad_open | notepad | 2/3 | 3/3 | 6.3/1.0 | 105/9 |
| notepad_save_and_close | notepad | 0/3 | 0/3 | 8.0/11.7 | 109/69 |
| notepad_subfolder | notepad | 0/3 | 0/3 | 8.0/15.0 | 108/76 |
| notepad_two_lines | notepad | 0/3 | 0/3 | 7.7/12.3 | 99/67 |
| notepad_type_save | notepad | 0/3 | 0/3 | 9.0/12.0 | 121/67 |
| settings_about | settings | 0/3 | 1/3 | 8.3/6.0 | 123/35 |
| settings_open | settings | 3/3 | 3/3 | 9.0/1.0 | 121/10 |

| group | legacy | hybrid | Fisher exact p |
|---|---|---|---|
| calculator | 0/12 | 3/12 | 0.217 |
| explorer | 0/12 | 2/12 | 0.478 |
| notepad | 2/18 | 3/18 | 1.000 |
| settings | 3/6 | 4/6 | 1.000 |

**TOTAL** legacy: 5/48, hybrid: 12/48; pass-rate difference (hybrid-legacy) +14.6 pts, bootstrap-over-tasks 95% CI [+4.2, +29.2] pts => MEANINGFUL.
Wilson 95% per arm: legacy 0.05-0.22, hybrid 0.15-0.39.
