# Cria/atualiza a tarefa "TP DASH Agente": inicia com o Windows, como LOCAL SERVICE,
# sem limite de tempo, e o Windows inicia de novo se ela parar.
param([Parameter(Mandatory = $true)][string]$Pasta)
$ErrorActionPreference = 'Stop'
$exe = Join-Path $Pasta 'TPDashAgente.exe'
if (Test-Path $exe) {
    $acao = New-ScheduledTaskAction -Execute $exe -WorkingDirectory $Pasta
} else {
    $py = Join-Path $Pasta '.venv\Scripts\pythonw.exe'
    $acao = New-ScheduledTaskAction -Execute $py -Argument ('"' + (Join-Path $Pasta 'agente.py') + '"') -WorkingDirectory $Pasta
}
$gatilhos = @(New-ScheduledTaskTrigger -AtStartup)
try { $gatilhos += New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 5) } catch { }
$principal = New-ScheduledTaskPrincipal -UserId 'NT AUTHORITY\LOCALSERVICE' -LogonType ServiceAccount -RunLevel Limited
$cfg = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -DontStopOnIdleEnd -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName 'TP DASH Agente' -Action $acao -Trigger $gatilhos -Principal $principal -Settings $cfg -Force | Out-Null
# so administradores e o servico leem a pasta (o config.ini tem a senha do banco)
icacls $Pasta /inheritance:r /grant:r "*S-1-5-32-544:(OI)(CI)F" "*S-1-5-18:(OI)(CI)F" "*S-1-5-19:(OI)(CI)M" | Out-Null
Write-Host '   Tarefa "TP DASH Agente" criada (inicia com o Windows e reinicia sozinha se parar).'
Start-ScheduledTask -TaskName 'TP DASH Agente'
