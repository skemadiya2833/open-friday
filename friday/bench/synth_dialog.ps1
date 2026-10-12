# Synthetic dialogs for live agent tests (Stage K4). WinForms controls are exposed to UI Automation (Tk is not).
#   powershell -File synth_dialog.ps1 -Mode crash|save|hung -Out <dir>
param([string]$Mode, [string]$Out)
Add-Type -AssemblyName System.Windows.Forms
$f = New-Object System.Windows.Forms.Form
$f.StartPosition = 'CenterScreen'; $f.Width = 520; $f.Height = 200; $f.TopMost = $true
$lbl = New-Object System.Windows.Forms.Label
$lbl.Left = 20; $lbl.Top = 20; $lbl.Width = 460; $lbl.Height = 50
function AddBtn($text, $x) {
    $b = New-Object System.Windows.Forms.Button
    $b.Text = $text; $b.Left = $x; $b.Top = 90; $b.Width = 110; $b.Height = 32
    $b.Add_Click({ Set-Content -Path (Join-Path $Out 'choice.txt') -Value $this.Text; $f.Close() })
    $f.Controls.Add($b)
}
switch ($Mode) {
    'crash' { $f.Text = 'Synthetic App crashed'; $lbl.Text = 'Synthetic App has stopped working. Send a crash report?'; AddBtn 'Send' 20; AddBtn "Don't send" 150 }
    'save'  { $f.Text = 'Synthetic Notepad'; $lbl.Text = 'Do you want to save changes to Untitled?'; AddBtn 'Save' 20; AddBtn "Don't Save" 150; AddBtn 'Cancel' 280 }
    'hung'  { $f.Text = 'Synthetic Hung App'; $lbl.Text = 'Working...'; $f.Add_Shown({ Start-Sleep -Seconds 40; $f.Close() }) }
}
$f.Controls.Add($lbl)
[void]$f.ShowDialog()
