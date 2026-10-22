# A Titan application written in PowerShell. Saved as UTF-8 WITH a BOM:
# Windows PowerShell 5.1 reads a script without one in the ANSI code page,
# and every Polish letter would come out wrong.
Import-Module Titan
$polish = (Invoke-Titan info).language -eq 'pl'
if ($polish) { $question = 'Jak masz na imię?' } else { $question = 'What is your name?' }
$name = Invoke-Titan ask $question
if ($null -eq $name) { exit }
$free = [math]::Round((Get-PSDrive C).Free / 1GB, 1)
if ($polish) {
    Invoke-Titan speak "Cześć z PowerShella, $name. Na dysku C jest $free GB wolnego miejsca." | Out-Null
} else {
    Invoke-Titan speak "Hello from PowerShell, $name. Drive C has $free GB free." | Out-Null
}
Invoke-Titan wait 4 | Out-Null
