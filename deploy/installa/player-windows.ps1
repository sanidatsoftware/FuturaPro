<#
  FuturaPro - installazione del player su Windows 10/11 (monitor o totem).

  In PowerShell aperto come amministratore:
    irm http://SERVER/installa/player-windows.ps1 -OutFile $env:TEMP\futurapro.ps1
    powershell -ExecutionPolicy Bypass -File $env:TEMP\futurapro.ps1 -Server SERVER

  Cosa fa:
    1. se il server usa il certificato interno, lo installa tra quelli attendibili
       (dopo che hai confrontato l'impronta con quella mostrata dal server);
    2. avvia Chrome (o Edge) a schermo intero sul player, con un profilo dedicato,
       all'accesso dell'utente indicato, e lo riapre se viene chiuso;
    3. sul totem abilita la stampa senza finestre (--kiosk-printing);
    4. impedisce lo spegnimento dello schermo e la sospensione.

  Altre opzioni:
    -Tipo monitor|totem   non chiedere il tipo
    -Utente NOME          utente Windows che avvia il player (predefinito: quello attuale)
    -Configura            apre il browser del player in una finestra normale, per
                          accettare il certificato di una stampante o controllare le impostazioni
    -Rimuovi              toglie il player da questo PC
#>
#Requires -RunAsAdministrator
param(
    [string]$Server,
    [ValidateSet("monitor", "totem")][string]$Tipo,
    [string]$Utente = $env:USERNAME,
    [switch]$Configura,
    [switch]$Rimuovi
)

$ErrorActionPreference = "Stop"
# PowerShell 5.1 di serie non usa TLS 1.2, che il server richiede.
[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$Cartella = "C:\FuturaPro"
$Profilo = Join-Path $Cartella "profilo"
$Impostazioni = Join-Path $Cartella "impostazioni.json"
$NomeAttivita = "FuturaPro Player"

function Scrivi([string]$testo, [string]$colore = "Cyan") { Write-Host $testo -ForegroundColor $colore }

function Trova-Browser {
    $candidati = @(
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
        "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe"
    )
    foreach ($percorso in $candidati) { if ($percorso -and (Test-Path $percorso)) { return $percorso } }
    throw "Non trovo né Google Chrome né Microsoft Edge. Installa Chrome e rilancia lo script."
}

function Ferma-Player {
    Stop-ScheduledTask -TaskName $NomeAttivita -ErrorAction SilentlyContinue
    Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" |
        Where-Object { $_.CommandLine -like "*$Cartella\avvia.ps1*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
    Get-CimInstance Win32_Process -Filter "Name='chrome.exe' OR Name='msedge.exe'" |
        Where-Object { $_.CommandLine -like "*$Profilo*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

# --- Rimozione ---------------------------------------------------------------------
if ($Rimuovi) {
    Ferma-Player
    Unregister-ScheduledTask -TaskName $NomeAttivita -Confirm:$false -ErrorAction SilentlyContinue
    Remove-Item $Cartella -Recurse -Force -ErrorAction SilentlyContinue
    Scrivi "Player FuturaPro rimosso. Il certificato del server, se installato, resta tra quelli attendibili." "Green"
    exit 0
}

# --- Configura: finestra normale con il profilo del player -----------------------------
if ($Configura) {
    if (-not (Test-Path $Impostazioni)) { throw "Il player non è installato su questo PC." }
    $salvate = Get-Content $Impostazioni -Raw | ConvertFrom-Json
    Ferma-Player
    Scrivi "Si apre il browser del player in una finestra normale."
    Scrivi "Per una stampante Epson in HTTPS: apri https://INDIRIZZO-STAMPANTE e accetta il certificato."
    Scrivi "Chiudi la finestra quando hai finito: il player riparte da solo."
    $p = Start-Process -FilePath $salvate.browser -ArgumentList @("--user-data-dir=`"$Profilo`"", "https://$($salvate.server)/player/") -PassThru
    $p.WaitForExit()
    Start-ScheduledTask -TaskName $NomeAttivita
    exit 0
}

# --- Domande -----------------------------------------------------------------------------
Scrivi "`nFuturaPro - installazione del player`n" "Green"
if (-not $Server) { $Server = Read-Host "Indirizzo del server (es. 10.0.100.41 oppure signage.miodominio.it)" }
$Server = ($Server -replace '^https?://', '') -replace '/.*$', ''
if (-not $Tipo) {
    $risposta = Read-Host "Questo PC è un monitor (1) o un totem touch con stampante (2)? [1]"
    if ($risposta -eq "2") { $Tipo = "totem" } else { $Tipo = "monitor" }
}
$browser = Trova-Browser
Scrivi "Server: $Server · Tipo: $Tipo · Utente: $Utente · Browser: $browser"

# --- 1. Certificato interno del server ---------------------------------------------------
$fileCertificato = Join-Path $env:TEMP "futurapro-ca.crt"
$certificatoScaricato = $false
try {
    Invoke-WebRequest -UseBasicParsing -Uri "http://$Server/futurapro-ca.crt" -OutFile $fileCertificato -TimeoutSec 15
    $certificatoScaricato = (Get-Item $fileCertificato).Length -gt 0
} catch {
    $certificatoScaricato = $false
}
if ($certificatoScaricato) {
    $certificato = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2($fileCertificato)
    $sha = [System.Security.Cryptography.SHA256]::Create()
    $impronta = ($sha.ComputeHash($certificato.RawData) | ForEach-Object { $_.ToString("X2") }) -join ""
    Scrivi "`nIl server usa un certificato interno. Impronta SHA-256:" "Yellow"
    Write-Host "  $impronta"
    Scrivi "Deve coincidere con quella mostrata alla fine dell'installazione del server." "Yellow"
    $conferma = Read-Host "Coincide? (S/N)"
    if ($conferma -notmatch '^[sSyY]') { throw "Installazione interrotta: impronta non confermata." }
    Import-Certificate -FilePath $fileCertificato -CertStoreLocation Cert:\LocalMachine\Root | Out-Null
    Scrivi "Certificato installato tra quelli attendibili." "Green"
} else {
    Scrivi "Nessun certificato interno: il server usa un certificato pubblico."
}

# --- 2. Il server risponde in HTTPS? --------------------------------------------------------
try {
    Invoke-WebRequest -UseBasicParsing -Uri "https://$Server/player/" -TimeoutSec 20 | Out-Null
    Scrivi "Il server risponde in HTTPS." "Green"
} catch {
    throw "Il server non risponde su https://$Server/player/ ($($_.Exception.Message)). Controlla indirizzo, rete e certificato."
}

# --- 3. Avvio del browser a schermo intero ------------------------------------------------------
New-Item -ItemType Directory -Force -Path $Cartella, $Profilo | Out-Null
$argomenti = @(
    "--kiosk", "https://$Server/player/",
    "--user-data-dir=`"$Profilo`"",
    "--no-first-run", "--no-default-browser-check", "--disable-session-crashed-bubble",
    "--noerrdialogs", "--disable-translate", "--disable-features=Translate",
    "--autoplay-policy=no-user-gesture-required",
    "--disable-pinch", "--overscroll-history-navigation=0"
)
if ($browser -like "*msedge.exe") { $argomenti += "--edge-kiosk-type=fullscreen" }
# Sul totem i biglietti escono senza finestra di stampa, sulla stampante predefinita di Windows.
if ($Tipo -eq "totem") { $argomenti += "--kiosk-printing" }

@{ server = $Server; tipo = $Tipo; browser = $browser; argomenti = $argomenti } |
    ConvertTo-Json | Set-Content -Path $Impostazioni -Encoding UTF8

# Il "guardiano": avvia il browser e lo riapre se si chiude o si blocca.
@'
$ErrorActionPreference = "Continue"
$cartella = Split-Path -Parent $MyInvocation.MyCommand.Path
$impostazioni = Get-Content (Join-Path $cartella "impostazioni.json") -Raw | ConvertFrom-Json
$profilo = Join-Path $cartella "profilo"
Start-Sleep -Seconds 10   # rete e desktop pronti
while ($true) {
    $inCorso = Get-CimInstance Win32_Process -Filter "Name='chrome.exe' OR Name='msedge.exe'" |
        Where-Object { $_.CommandLine -like "*$profilo*" -and $_.CommandLine -notlike "*--type=*" } |
        Select-Object -First 1
    if ($inCorso) {
        Wait-Process -Id $inCorso.ProcessId -ErrorAction SilentlyContinue
    } else {
        Start-Process -FilePath $impostazioni.browser -ArgumentList $impostazioni.argomenti | Out-Null
        Start-Sleep -Seconds 15
    }
    Start-Sleep -Seconds 5
}
'@ | Set-Content -Path (Join-Path $Cartella "avvia.ps1") -Encoding UTF8

Ferma-Player
$azione = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$Cartella\avvia.ps1`""
$avvio = New-ScheduledTaskTrigger -AtLogOn -User $Utente
$principale = New-ScheduledTaskPrincipal -UserId $Utente -LogonType Interactive -RunLevel Limited
$regole = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $NomeAttivita -Action $azione -Trigger $avvio -Principal $principale -Settings $regole -Force | Out-Null
Scrivi "Il player parte a ogni accesso di $Utente." "Green"

# --- 4. Schermo sempre acceso -----------------------------------------------------------------------
powercfg /change monitor-timeout-ac 0 | Out-Null
powercfg /change standby-timeout-ac 0 | Out-Null
powercfg /change hibernate-timeout-ac 0 | Out-Null
Set-ItemProperty -Path "HKCU:\Control Panel\Desktop" -Name ScreenSaveActive -Value "0" -ErrorAction SilentlyContinue
Scrivi "Sospensione e spegnimento dello schermo disattivati." "Green"

# --- Avvio adesso ---------------------------------------------------------------------------------------
if ($Utente -eq $env:USERNAME) {
    Start-ScheduledTask -TaskName $NomeAttivita
    Scrivi "`nIl player si sta avviando: tra pochi secondi lo schermo mostra il codice di abbinamento." "Green"
} else {
    Scrivi "`nIl player partirà al prossimo accesso di $Utente." "Green"
}

Scrivi "`nUltimi passi:" "Yellow"
Write-Host "  1. Nel pannello (https://$Server/pannello/) vai in Monitor -> Abbina e inserisci il codice mostrato."
Write-Host "  2. Accesso automatico di Windows: premi Win+R, scrivi netplwiz, togli la spunta"
Write-Host "     'Per utilizzare questo computer è necessario che l'utente immetta il nome utente e la password'."
if ($Tipo -eq "totem") {
    Write-Host "  3. Stampante dei biglietti: installa il driver della stampante (per Epson TM: 'Advanced Printer Driver')"
    Write-Host "     e impostala come predefinita; nel layout del totem scegli 'Stampante di sistema'."
    Write-Host "     Per una Epson di rete con ePOS in HTTPS rilancia lo script con -Configura per accettarne il certificato."
}
Write-Host "  Per uscire dal player: Ctrl+Alt+Canc -> Esci (o Gestione attività). Per toglierlo: -Rimuovi."
