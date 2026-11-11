# Renova calendarios_oficiais.json (IBGE + FGV) e publica. Roda no PC do Léo pelo Agendador de
# Tarefas (trimestral), porque servicodados.ibge.gov.br recusa a nuvem. Log: ferramentas/renovar_calendarios.log
$ErrorActionPreference = "Continue"
$repo = Split-Path -Parent $PSScriptRoot
$py   = "C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe"
$git  = "C:\Program Files\Git\cmd\git.exe"
$log  = Join-Path $PSScriptRoot "renovar_calendarios.log"
function Log($m) { "$(Get-Date -Format 'yyyy-MM-dd HH:mm') $m" | Out-File -FilePath $log -Append -Encoding utf8 }

Set-Location $repo
$env:PYTHONIOENCODING = "utf-8"
& $git pull --rebase --autostash -q origin main
if ($LASTEXITCODE -ne 0) { Log "ERRO no git pull"; exit 1 }

$saida = & $py -X utf8 -c "import kpis_oficiais as K; i=K._calendario_ibge(); f=K._calendario_fgv_incc(); print('IBGE', sum(len(v) for v in i.values()), 'FGV', len(f))" 2>&1 | Out-String
Log ($saida.Trim() -replace "`r?`n", " | ")
if ($saida -match "versionada") { Log "ERRO: fonte nao respondeu; nada publicado"; exit 1 }

& $git diff --quiet -- calendarios_oficiais.json
if ($LASTEXITCODE -eq 0) { Log "OK: calendarios conferidos, sem mudanca"; exit 0 }
& $git add calendarios_oficiais.json
& $git commit -q -m "Calendarios oficiais renovados (tarefa trimestral)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
& $git push -q origin main
if ($LASTEXITCODE -ne 0) { Log "ERRO no git push"; exit 1 }
Log "OK: calendarios renovados e publicados"
