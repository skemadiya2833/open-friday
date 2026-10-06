# Model comparison on a small task subset (hybrid agent, 1 rep). Keep hands off mouse and keyboard.
$ErrorActionPreference = "Continue"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$log = Join-Path $env:TEMP "cmp.log"
Remove-Item $log -ErrorAction SilentlyContinue
foreach ($m in @("qwen3-vl:8b-instruct", "qwen3.5:9b")) {
    $o = "docs/research/bench_hybrid_" + ($m -replace "[:.\-]", "_") + "_subset.json"
    "== $m" | Out-File -Append $log
    & friday_env\Scripts\python.exe -m friday.bench.run --backend hybrid --model $m --reps 1 --ctx 32768 --max-iter 15 `
        --timeout 120 --countdown 8 --tasks notepad_open,notepad_type_save,calc_open,calc_add,explorer_open_folder,settings_about `
        --out $o 2>&1 | Select-String "^\[\d|^\| |Overall|ABORT" | ForEach-Object { $_.Line } | Out-File -Append $log
}
"ALLDONE" | Out-File -Append $log
