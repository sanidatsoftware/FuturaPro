<#
  FuturaPro - servizio code del totem.

  Tiene le code dei reparti del negozio: assegna i numeri dei biglietti, riceve
  le chiamate di bilance e banchi, dà i numeri ai monitor. Non dipende dal server
  centrale: se la rete verso il server cade, il negozio continua a dare i turni.
  Dal server arriva solo la configurazione (nomi, colori, chiavi delle bilance),
  che il player del totem gli passa a ogni aggiornamento, con i file audio degli
  annunci dei numeri (es. «SALUMERIA_27.mp3»): restano qui, in annunci\, e i monitor
  del negozio li prendono da qui anche quando il server non è raggiungibile.

  Lavora sul Totem Master (server code) della sede, scelto nel pannello: è lui a detenere i
  turni. Gli eventuali altri totem del negozio chiedono a lui i numeri dei biglietti.

  Plugin (facoltativi): Info Prezzo e Info Ingredienti. Il file SQLite sta su un PC del
  negozio (cartella condivisa con utente e password): il servizio lo ricopia qui ogni tot
  minuti, solo se è cambiato, e risponde alle ricerche dei dispositivi del negozio
  (/plugin/prezzo, /plugin/ingredienti). La copia gira in un processo a parte: le code non
  aspettano. La password arriva con la configurazione e su disco resta cifrata (DPAPI).

  Lo installa e lo avvia player-windows.ps1 (tipo totem) come attività di sistema.
  Porte: 8443 HTTPS (monitor e totem), 8090 HTTP (bilance e banchi in rete locale).

  Chi può fare cosa:
    - leggere i numeri (/stato): chiunque in rete; sono gli stessi mostrati a schermo;
    - leggere i file degli annunci (/annunci/<impronta>): chiunque in rete;
    - cercare un articolo (/plugin/prezzo, /plugin/ingredienti): chiunque in rete; sono i prezzi esposti in negozio;
    - provare l'accesso al file di un plugin (/plugin/prova/…): solo il totem stesso;
    - ricevere la configurazione e i file: solo il totem stesso (127.0.0.1);
    - emettere biglietti: il totem stesso e i totem secondari della sede, con la chiave
      «Authorization: Totem <chiave>» (qui ne arriva solo l'impronta, con la configurazione);
    - chiamare i numeri (/banco/…): solo con la chiave del reparto, come nel pannello.

  Numeri da 0 a 99 (o al massimo del reparto) e poi di nuovo 0; al primo uso di un
  nuovo giorno la coda riparte. Le richieste sono servite una alla volta: due banchi
  o due biglietti insieme non ottengono mai lo stesso numero.
#>
param(
    [string]$Cartella = "C:\FuturaPro\code",
    [int]$PortaHttp = 8090,
    [int]$PortaHttps = 8443,
    [switch]$SoloHttp
)

$ErrorActionPreference = "Stop"
$Versione = "1.7.3"
$fileStato = Join-Path $Cartella "stato.json"
$fileRegistro = Join-Path $Cartella "registro.log"
$cartellaAnnunci = Join-Path $Cartella "annunci"
# Il registro di biglietti e chiamate: il player del totem lo inoltra al server (tempi d'attesa,
# coda sul telefono) appena c'è rete. Resta qui anche quando il server non risponde.
$fileEventi = Join-Path $Cartella "eventi.jsonl"
New-Item -ItemType Directory -Force -Path $Cartella | Out-Null
New-Item -ItemType Directory -Force -Path $cartellaAnnunci | Out-Null

function Registra([string]$testo) {
    $riga = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $testo
    Add-Content -Path $fileRegistro -Value $riga -Encoding UTF8
    # Il registro non cresce all'infinito.
    if ((Get-Item $fileRegistro).Length -gt 5MB) { Move-Item -Force $fileRegistro "$fileRegistro.1" }
}

# --- Stato: configurazione dei reparti e contatori della giornata ----------------

$script:reparti = @()
$script:totem = @()   # impronte delle chiavi dei totem secondari
$script:code = @{}

function Carica-Stato {
    if (-not (Test-Path $fileStato)) { return }
    $dati = Get-Content -Raw -Encoding UTF8 $fileStato | ConvertFrom-Json
    if ($dati.reparti) { $script:reparti = @($dati.reparti) }
    if ($dati.totem) { $script:totem = @($dati.totem) }
    foreach ($c in @($dati.code)) {
        if ($c) {
            $script:code[[string]$c.id] = @{
                giornata = [string]$c.giornata; chiamati = [int]$c.chiamati
                emessi = [int]$c.emessi; chiamato_il = $c.chiamato_il
            }
        }
    }
}

function Salva-Stato {
    $elenco = @(foreach ($id in $script:code.Keys) {
        $c = $script:code[$id]
        [pscustomobject]@{ id = $id; giornata = $c.giornata; chiamati = $c.chiamati; emessi = $c.emessi; chiamato_il = $c.chiamato_il }
    })
    $testo = [pscustomobject]@{ reparti = $script:reparti; totem = @($script:totem); code = $elenco } | ConvertTo-Json -Depth 6
    # Prima su un file temporaneo, poi lo scambio: un'interruzione di corrente non lascia un file a metà.
    $temporaneo = "$fileStato.tmp"
    [System.IO.File]::WriteAllText($temporaneo, $testo, (New-Object System.Text.UTF8Encoding($false)))
    Move-Item -Force $temporaneo $fileStato
}

function Trova-Reparto([string]$id) {
    foreach ($r in $script:reparti) { if ([string]$r.id -eq $id) { return $r } }
    return $null
}

function Coda([string]$id) {
    $oggi = (Get-Date).ToString("yyyy-MM-dd")
    if (-not $script:code.ContainsKey($id)) {
        $script:code[$id] = @{ giornata = $oggi; chiamati = 0; emessi = 0; chiamato_il = $null }
    }
    $c = $script:code[$id]
    if ($c.giornata -ne $oggi) {
        $c.giornata = $oggi; $c.chiamati = 0; $c.emessi = 0; $c.chiamato_il = $null
    }
    return $c
}

function Numero([int]$totale, [int]$massimo) {
    if ($totale -le 0) { return $null }
    return ($totale - 1) % ($massimo + 1)
}

function Stato-Reparto($r) {
    $c = Coda ([string]$r.id)
    $massimo = [int]$r.massimo
    return [ordered]@{
        id = [string]$r.id; nome = $r.nome; colore = $r.colore; colore_testo = $r.colore_testo
        numero = (Numero $c.chiamati $massimo)
        in_coda = [Math]::Max(0, $c.emessi - $c.chiamati)
        ultimo_emesso = (Numero $c.emessi $massimo)
        chiamato_il = $c.chiamato_il
    }
}

function Adesso { return (Get-Date).ToUniversalTime().ToString("o") }

# --- Registro degli eventi ---------------------------------------------------------

$script:eventi = New-Object System.Collections.ArrayList
$script:seq = 0

function Carica-Eventi {
    if (-not (Test-Path $fileEventi)) { return }
    foreach ($riga in Get-Content -Encoding UTF8 $fileEventi) {
        if (-not $riga) { continue }
        try { $e = $riga | ConvertFrom-Json } catch { continue }
        [void]$script:eventi.Add($e)
        if ([int]$e.seq -gt $script:seq) { $script:seq = [int]$e.seq }
    }
}

function Nota-Evento([string]$tipo, $r, [int]$progressivo, [string]$codice) {
    $script:seq += 1
    $e = [pscustomobject][ordered]@{
        seq = $script:seq; tipo = $tipo; reparto = [string]$r.id; progressivo = $progressivo; quando = (Adesso); codice = $codice
    }
    [void]$script:eventi.Add($e)
    Add-Content -Path $fileEventi -Value ($e | ConvertTo-Json -Compress) -Encoding UTF8
    # Si tengono gli ultimi 5000: il player li inoltra in pochi secondi quando c'è rete.
    if ($script:eventi.Count -gt 5000) {
        $script:eventi.RemoveRange(0, 1000)
        Set-Content -Path $fileEventi -Encoding UTF8 -Value ($script:eventi | ForEach-Object { $_ | ConvertTo-Json -Compress })
    }
}

# Il codice del QR sul biglietto: 10 caratteri casuali, come quelli del server.
function Nuovo-Codice {
    $alfabeto = "23456789abcdefghjkmnpqrstuvwxyz"
    $byte = New-Object byte[] 10
    [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($byte)
    return (-join ($byte | ForEach-Object { $alfabeto[$_ % $alfabeto.Length] }))
}

# --- Operazioni ------------------------------------------------------------------

function Esegui([string]$operazione, $r, $numero) {
    $c = Coda ([string]$r.id)
    switch ($operazione) {
        "avanti"   { $c.chiamati += 1; $c.chiamato_il = Adesso }
        "indietro" { $c.chiamati = [Math]::Max(0, $c.chiamati - 1); $c.chiamato_il = Adesso }
        "ripeti"   { $c.chiamato_il = Adesso }
        "azzera"   { $c.chiamati = 0; $c.emessi = 0; $c.chiamato_il = $null }
        "imposta"  {
            # Riparte dal numero indicato, che viene chiamato; chi era in coda resta in coda.
            $inCoda = [Math]::Max(0, $c.emessi - $c.chiamati)
            $c.chiamati = $numero + 1
            $c.emessi = $c.chiamati + $inCoda
            $c.chiamato_il = Adesso
        }
    }
    Salva-Stato
    Nota-Evento $operazione $r $c.chiamati ""
    Registra "$operazione $($r.nome) -> $(Numero $c.chiamati ([int]$r.massimo))"
}

function Emetti($r) {
    $c = Coda ([string]$r.id)
    # Se il banco è andato avanti senza biglietti, il primo biglietto parte da lì.
    $c.emessi = [Math]::Max($c.emessi, $c.chiamati) + 1
    Salva-Stato
    $stato = Stato-Reparto $r
    $codice = Nuovo-Codice
    Nota-Evento "emesso" $r $c.emessi $codice
    Registra "biglietto $($r.nome) $($stato.ultimo_emesso)"
    return [ordered]@{
        reparto_id = [string]$r.id; reparto = $r.nome; colore = $r.colore; colore_testo = $r.colore_testo
        numero = $stato.ultimo_emesso; davanti = [Math]::Max(0, $stato.in_coda - 1); codice = $codice
    }
}

# --- HTTP ---------------------------------------------------------------------------

function Rispondi($contesto, [int]$codice, $corpo, [string]$tipo = "application/json; charset=utf-8") {
    $r = $contesto.Response
    $r.StatusCode = $codice
    # I monitor leggono i numeri da un'altra origine (la pagina viene dal server centrale).
    $r.Headers["Access-Control-Allow-Origin"] = "*"
    $r.Headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type"
    $r.Headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    $r.Headers["Access-Control-Allow-Private-Network"] = "true"
    $r.Headers["Cache-Control"] = "no-store"
    if ($null -ne $corpo) {
        if ($corpo -is [byte[]]) { $byte = $corpo }
        elseif ($corpo -is [string]) { $byte = [System.Text.Encoding]::UTF8.GetBytes($corpo) }
        else { $byte = [System.Text.Encoding]::UTF8.GetBytes(($corpo | ConvertTo-Json -Depth 6 -Compress)) }
        $r.ContentType = $tipo
        $r.ContentLength64 = $byte.Length
        $r.OutputStream.Write($byte, 0, $byte.Length)
    }
    $r.OutputStream.Close()
}

# --- Annunci: un file per impronta SHA-256 (il nome non conta) ------------------------

function Impronta-Byte([byte[]]$byte) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    return (($sha.ComputeHash($byte) | ForEach-Object { $_.ToString("x2") }) -join "")
}

function Annunci-Presenti {
    return @(Get-ChildItem -Path $cartellaAnnunci -File | Where-Object { $_.Name -match "^[0-9a-f]{64}$" } | ForEach-Object { $_.Name })
}

# Tiene solo i file ancora usati dai reparti (l'elenco arriva con la configurazione).
function Pulisci-Annunci($validi) {
    $tenere = @{}
    foreach ($v in @($validi)) { $tenere[[string]$v] = $true }
    foreach ($nome in Annunci-Presenti) {
        if (-not $tenere.ContainsKey($nome)) { Remove-Item -Force (Join-Path $cartellaAnnunci $nome) }
    }
}

function Leggi-Byte($richiesta, [int]$massimo) {
    $memoria = New-Object System.IO.MemoryStream
    $blocco = New-Object byte[] 65536
    while (($letti = $richiesta.InputStream.Read($blocco, 0, $blocco.Length)) -gt 0) {
        $memoria.Write($blocco, 0, $letti)
        if ($memoria.Length -gt $massimo) { return $null }
    }
    return $memoria.ToArray()
}

function Leggi-Corpo($richiesta) {
    $lettore = New-Object System.IO.StreamReader($richiesta.InputStream, [System.Text.Encoding]::UTF8)
    $testo = $lettore.ReadToEnd()
    if (-not $testo) { return $null }
    return $testo | ConvertFrom-Json
}

function Locale($richiesta) {
    return [System.Net.IPAddress]::IsLoopback($richiesta.RemoteEndPoint.Address)
}

# Un totem secondario della sede (Authorization: Totem <chiave>).
function Totem-Secondario($richiesta) {
    $parti = ([string]$richiesta.Headers["Authorization"]) -split " "
    if ($parti.Count -ne 2 -or $parti[0] -ne "Totem" -or @($script:totem).Count -eq 0) { return $false }
    return @($script:totem) -contains (Impronta $parti[1])
}

function Impronta([string]$testo) {
    $sha = [System.Security.Cryptography.SHA256]::Create()
    return (($sha.ComputeHash([System.Text.Encoding]::UTF8.GetBytes($testo)) | ForEach-Object { $_.ToString("x2") }) -join "")
}

# Il reparto della chiave del banco (Authorization: Pulsante <chiave>), o $null.
function Reparto-Della-Chiave($richiesta) {
    $parti = ([string]$richiesta.Headers["Authorization"]) -split " "
    if ($parti.Count -ne 2 -or $parti[0] -ne "Pulsante") { return $null }
    $impronta = Impronta $parti[1]
    foreach ($r in $script:reparti) {
        if (@($r.chiavi) -contains $impronta) { return $r }
    }
    return $null
}

# --- Plugin: Info Prezzo e Info Ingredienti --------------------------------------

$cartellaPlugin = Join-Path $Cartella "plugin"
$filePlugin = Join-Path $cartellaPlugin "plugin.json"
New-Item -ItemType Directory -Force -Path $cartellaPlugin | Out-Null
$script:plugin = @{}        # tipo -> configurazione (condivisione, file, utente, password, minuti, query)
$script:statoPlugin = @{}   # tipo -> copiato, errore, dimensione, controllato, firma, prossimo, lavoro
$sqliteCaricato = $false
$fileSqlite = Join-Path $PSScriptRoot "FpSqlite.cs"
try {
    Add-Type -Path $fileSqlite
    $sqliteCaricato = $true
} catch {
    # Senza FpSqlite.cs (installazione vecchia) le code funzionano lo stesso.
}
Add-Type -AssemblyName System.Security

function Proteggi([string]$testo) {
    if (-not $testo) { return "" }
    $byte = [System.Security.Cryptography.ProtectedData]::Protect([System.Text.Encoding]::UTF8.GetBytes($testo), $null, "LocalMachine")
    return [Convert]::ToBase64String($byte)
}

function Sproteggi([string]$testo) {
    if (-not $testo) { return "" }
    try {
        $byte = [System.Security.Cryptography.ProtectedData]::Unprotect([Convert]::FromBase64String($testo), $null, "LocalMachine")
        return [System.Text.Encoding]::UTF8.GetString($byte)
    } catch { return "" }
}

# Quando fare la prossima copia: il primo fra gli orari fissi e «tra N minuti» (0 = senza).
function Prossima-Copia($c) {
    $adesso = Get-Date
    $candidati = @(foreach ($giorno in 0, 1) {
        foreach ($orario in @($c.orari)) {
            $parti = $orario -split ":"
            $adesso.Date.AddDays($giorno).AddHours([int]$parti[0]).AddMinutes([int]$parti[1])
        }
    })
    if ([int]$c.minuti -gt 0) { $candidati += $adesso.AddMinutes([int]$c.minuti) }
    $prima = $candidati | Where-Object { $_ -gt $adesso } | Sort-Object | Select-Object -First 1
    if (-not $prima) { $prima = $adesso.AddDays(1) }
    return $prima
}

# Firma e data dell'ultima copia di ogni file: restano dopo un riavvio, così un file uguale non si ricopia.
$fileFirme = Join-Path $cartellaPlugin "copie.json"
$script:firmeSalvate = @{}
if (Test-Path $fileFirme) {
    try {
        $letto = Get-Content -Raw -Encoding UTF8 $fileFirme | ConvertFrom-Json
        foreach ($p in $letto.PSObject.Properties) { $script:firmeSalvate[$p.Name] = $p.Value }
    } catch { }
}

function Salva-Firme {
    $dati = @{}
    foreach ($tipo in $script:statoPlugin.Keys) {
        $s = $script:statoPlugin[$tipo]
        $dati[$tipo] = @{ firma = $s.firma; copiato = $s.copiato; dimensione = $s.dimensione; richiesta = $s.richiesta }
    }
    [System.IO.File]::WriteAllText($fileFirme, ($dati | ConvertTo-Json -Depth 3), (New-Object System.Text.UTF8Encoding($false)))
}

function Imposta-Plugin($configurazione) {
    $nuovo = @{}
    foreach ($tipo in @("prezzo", "ingredienti")) {
        $c = $null
        if ($configurazione) { $c = $configurazione.$tipo }
        if (-not $c) { continue }
        $nuovo[$tipo] = @{
            condivisione = [string]$c.condivisione; file = [string]$c.file; utente = [string]$c.utente
            password = [string]$c.password; minuti = [Math]::Max(0, [int]$c.minuti); query = [string]$c.query
            orari = @($c.orari | Where-Object { $_ -match "^\d{2}:\d{2}$" }); richiesta = [string]$c.richiesta
        }
        $locale = Join-Path $cartellaPlugin "$tipo.db"
        if (-not $script:statoPlugin.ContainsKey($tipo)) {
            $ricordato = $script:firmeSalvate[$tipo]
            # PowerShell 7 rilegge le date del JSON come date: si riportano al formato ISO.
            $copiato = $ricordato.copiato
            if ($copiato -is [datetime]) { $copiato = $copiato.ToUniversalTime().ToString("o") }
            $script:statoPlugin[$tipo] = @{
                copiato = [string]$copiato; errore = ""; dimensione = [long]$ricordato.dimensione; controllato = ""
                firma = [string]$ricordato.firma; prossimo = (Get-Date); lavoro = $null; richiesta = [string]$ricordato.richiesta
            }
            # Con gli orari fissi e una copia già qui, dopo un riavvio si aspetta l'orario (i file grandi non si ricopiano a ogni accensione).
            if ($nuovo[$tipo].orari.Count -gt 0 -and (Test-Path $locale)) { $script:statoPlugin[$tipo].prossimo = Prossima-Copia $nuovo[$tipo] }
        }
        $s = $script:statoPlugin[$tipo]
        $vecchio = $script:plugin[$tipo]
        if ($vecchio -and (($vecchio.orari -join ",") -ne ($nuovo[$tipo].orari -join ",") -or $vecchio.minuti -ne $nuovo[$tipo].minuti)) {
            $s.prossimo = Prossima-Copia $nuovo[$tipo]
        }
        # Cambiata la fonte, o «Aggiorna adesso» dal pannello: si ricopia subito, anche se il file sembra uguale.
        $cambiata = $vecchio -and ($vecchio.condivisione -ne $nuovo[$tipo].condivisione -or $vecchio.file -ne $nuovo[$tipo].file -or $vecchio.utente -ne $nuovo[$tipo].utente -or $vecchio.password -ne $nuovo[$tipo].password)
        $richiesta = $nuovo[$tipo].richiesta -and $nuovo[$tipo].richiesta -ne $s.richiesta
        if ($cambiata -or $richiesta -or -not (Test-Path $locale)) {
            if ($cambiata -or $richiesta) { $s.firma = "" }
            $s.prossimo = (Get-Date)
        }
        $s.richiesta = $nuovo[$tipo].richiesta
    }
    $script:plugin = $nuovo
    $salvato = @{}
    foreach ($tipo in $nuovo.Keys) {
        $c = $nuovo[$tipo]
        $salvato[$tipo] = @{ condivisione = $c.condivisione; file = $c.file; utente = $c.utente; password = (Proteggi $c.password); minuti = $c.minuti; query = $c.query; orari = @($c.orari); richiesta = $c.richiesta }
    }
    [System.IO.File]::WriteAllText($filePlugin, ($salvato | ConvertTo-Json -Depth 4), (New-Object System.Text.UTF8Encoding($false)))
}

function Carica-Plugin {
    if (-not (Test-Path $filePlugin)) { return }
    try {
        $dati = Get-Content -Raw -Encoding UTF8 $filePlugin | ConvertFrom-Json
        foreach ($tipo in @("prezzo", "ingredienti")) {
            if ($dati.$tipo) { $dati.$tipo.password = Sproteggi ([string]$dati.$tipo.password) }
        }
        Imposta-Plugin $dati
    } catch {
        Registra "plugin: configurazione illeggibile ($($_.Exception.Message))"
    }
}

# La copia dal PC del negozio, in un processo a parte: una rete lenta non ferma le code.
$copiaFonte = {
    param($condivisione, $file, $utente, $password, $destinazione, $firmaPrecedente, $sorgenteSqlite)
    $esito = @{ cambiato = $false; firma = $firmaPrecedente; dimensione = 0; errore = "" }
    $nome = "FP" + [guid]::NewGuid().ToString("N").Substring(0, 8)
    try {
        $parametri = @{ Name = $nome; PSProvider = "FileSystem"; Root = $condivisione; ErrorAction = "Stop" }
        if ($utente) {
            $segreta = ConvertTo-SecureString $password -AsPlainText -Force
            $parametri.Credential = New-Object System.Management.Automation.PSCredential($utente, $segreta)
        }
        try { New-PSDrive @parametri | Out-Null } catch { throw "Cartella condivisa $condivisione non raggiungibile o credenziali errate: $($_.Exception.Message)" }
        $sorgente = "$($nome):\$file"
        if (-not (Test-Path -LiteralPath $sorgente)) { throw "Cartella raggiunta, ma il file non c'è: controlla percorso e nome del file ($file)." }
        $info = Get-Item -LiteralPath $sorgente -ErrorAction Stop
        $firma = "$($info.Length)|$($info.LastWriteTimeUtc.Ticks)"
        $wal = "$sorgente-wal"
        $conWal = Test-Path -LiteralPath $wal
        if ($conWal) { $w = Get-Item -LiteralPath $wal; $firma += "|$($w.Length)|$($w.LastWriteTimeUtc.Ticks)" }
        $esito.dimensione = $info.Length
        if ($firma -ne $firmaPrecedente -or -not (Test-Path "$destinazione")) {
            Remove-Item -Force -ErrorAction SilentlyContinue "$destinazione.tmp", "$destinazione.tmp-wal"
            Copy-Item -LiteralPath $sorgente -Destination "$destinazione.tmp" -Force
            if ($conWal) { Copy-Item -LiteralPath $wal -Destination "$destinazione.tmp-wal" -Force }
            # Anche il controllo si fa qui, fuori dal servizio: un file grande non ferma le code.
            if ($sorgenteSqlite -and (Test-Path $sorgenteSqlite)) {
                Add-Type -Path $sorgenteSqlite
                # Le modifiche ancora nel «-wal» entrano nel file: poi lo si apre in sola lettura.
                [FpSqlite]::SenzaWal("$destinazione.tmp")
                # Copiata mentre il gestionale scriveva? Si tiene la copia precedente e si riprova.
                if (-not [FpSqlite]::Integro("$destinazione.tmp")) { throw "copia non integra (il file era in scrittura): riprovo tra poco" }
            }
            $esito.cambiato = $true
            $esito.firma = $firma
        }
    } catch {
        # Nei messaggi di Windows compare l'unità temporanea (es. «FP1a2b3c4d:»): si mostra la cartella vera.
        $esito.errore = $_.Exception.Message.Replace("$($nome):", $condivisione)
    } finally {
        Remove-PSDrive -Name $nome -Force -ErrorAction SilentlyContinue
    }
    return $esito
}

# A ogni giro del servizio: parte la copia che è ora di fare, si raccoglie quella finita.
function Aggiorna-Plugin {
    foreach ($tipo in @($script:plugin.Keys)) {
        $c = $script:plugin[$tipo]
        $s = $script:statoPlugin[$tipo]
        $destinazione = Join-Path $cartellaPlugin "$tipo.db"
        if ($s.lavoro) {
            if ($s.lavoro.State -eq "Running") { continue }
            $esito = $null
            try { $esito = Receive-Job $s.lavoro -ErrorAction Stop | Select-Object -Last 1 } catch { $esito = @{ errore = $_.Exception.Message } }
            Remove-Job $s.lavoro -Force -ErrorAction SilentlyContinue
            $s.lavoro = $null
            $s.controllato = Adesso
            if (-not $esito) { $esito = @{ errore = "copia interrotta" } }
            if ($esito.errore) {
                $s.errore = [string]$esito.errore
                Registra "plugin $($tipo): $($s.errore)"
            } else {
                $s.errore = ""
                $s.dimensione = [long]$esito.dimensione
                if ($esito.cambiato) {
                    try {
                        Remove-Item -Force -ErrorAction SilentlyContinue $destinazione, "$destinazione-wal", "$destinazione-shm"
                        Move-Item -Force "$destinazione.tmp" $destinazione
                        Remove-Item -Force -ErrorAction SilentlyContinue "$destinazione.tmp-wal", "$destinazione.tmp-shm"
                        $s.firma = [string]$esito.firma
                        $s.copiato = Adesso
                        Registra "plugin $($tipo): file aggiornato ($($s.dimensione) byte)"
                    } catch {
                        $s.errore = "copia locale: $($_.Exception.Message)"
                        $s.firma = ""
                        Remove-Item -Force -ErrorAction SilentlyContinue "$destinazione.tmp", "$destinazione.tmp-wal", "$destinazione.tmp-shm"
                    }
                }
            }
            $s.prossimo = Prossima-Copia $c
            if ($s.errore) { $s.prossimo = (Get-Date).AddMinutes(2) }
            Salva-Firme
            continue
        }
        if ((Get-Date) -ge $s.prossimo) {
            $s.lavoro = Start-Job -ScriptBlock $copiaFonte -ArgumentList $c.condivisione, $c.file, $c.utente, $c.password, $destinazione, $s.firma, $(if ($sqliteCaricato) { $fileSqlite } else { "" })
            $s.prossimo = Prossima-Copia $c
        }
    }
}

function Cerca-Articolo([string]$tipo, [string]$codice, [string]$plu, [string]$reparto) {
    $c = $script:plugin[$tipo]
    $file = Join-Path $cartellaPlugin "$tipo.db"
    if (-not $c -or -not $sqliteCaricato -or -not (Test-Path $file)) { return $null }
    $parametri = @{ codice = $codice; codice_corto = $codice.TrimStart("0"); plu = $plu; reparto = $reparto }
    return [FpSqlite]::Cerca($file, $c.query, $parametri)
}

function Gestisci-Plugin($contesto, [string]$tipo) {
    $richiesta = $contesto.Request
    if (-not $script:plugin.ContainsKey($tipo)) { Rispondi $contesto 404 @{ errore = "Plugin non attivo." }; return }
    $file = Join-Path $cartellaPlugin "$tipo.db"
    if (-not $sqliteCaricato) { Rispondi $contesto 503 @{ errore = "Lettura SQLite non disponibile su questo totem." }; return }
    if (-not (Test-Path $file)) {
        $errore = $script:statoPlugin[$tipo].errore
        if (-not $errore) { $errore = "File non ancora copiato dal PC del negozio." }
        Rispondi $contesto 503 @{ errore = $errore }; return
    }
    # Solo cifre (il codice letto), il reparto come lo scrive il pannello: niente altro arriva alla query.
    $codice = ([string]$richiesta.QueryString["codice"]) -replace "[^0-9]", ""
    $plu = ([string]$richiesta.QueryString["plu"]) -replace "[^0-9]", ""
    $reparto = ([string]$richiesta.QueryString["reparto"]) -replace "[^A-Za-z0-9_-]", ""
    if ($codice.Length -gt 20 -or $plu.Length -gt 7 -or $reparto.Length -gt 20 -or (-not $codice -and -not $plu)) {
        Rispondi $contesto 400 @{ errore = "Codice non valido." }; return
    }
    try {
        $articolo = Cerca-Articolo $tipo $codice $plu $reparto
        $risposta = [ordered]@{ trovato = ($null -ne $articolo); articolo = $articolo; aggiornato = $script:statoPlugin[$tipo].copiato }
        # Info Ingredienti con il prezzo: la stessa ricerca nel file di Info Prezzo.
        if ($tipo -eq "ingredienti" -and $richiesta.QueryString["prezzo"] -eq "1" -and $script:plugin.ContainsKey("prezzo")) {
            try { $risposta.prezzo = Cerca-Articolo "prezzo" $codice $plu $reparto } catch { $risposta.prezzo = $null }
        }
        Rispondi $contesto 200 $risposta
    } catch {
        Registra "plugin $($tipo): $($_.Exception.Message)"
        Rispondi $contesto 500 @{ errore = $_.Exception.Message }
    }
}

# «Prova accesso» dal pannello: si prova cartella e file con le credenziali attuali, in un processo
# a parte (una cartella che non risponde può far aspettare decine di secondi).
$script:prove = @{}
$provaFonte = {
    param($condivisione, $file, $utente, $password)
    $nome = "FP" + [guid]::NewGuid().ToString("N").Substring(0, 8)
    try {
        $parametri = @{ Name = $nome; PSProvider = "FileSystem"; Root = $condivisione; ErrorAction = "Stop" }
        if ($utente) {
            $segreta = ConvertTo-SecureString $password -AsPlainText -Force
            $parametri.Credential = New-Object System.Management.Automation.PSCredential($utente, $segreta)
        }
        try { New-PSDrive @parametri | Out-Null } catch { return @{ ok = $false; messaggio = "Cartella condivisa non raggiungibile o credenziali errate: $($_.Exception.Message)" } }
        $sorgente = "$($nome):\$file"
        if (-not (Test-Path -LiteralPath $sorgente)) { return @{ ok = $false; messaggio = "Cartella raggiunta, ma il file non c'è: controlla il percorso ($file)." } }
        $info = Get-Item -LiteralPath $sorgente
        $flusso = [System.IO.File]::Open($info.FullName, "Open", "Read", "ReadWrite")
        try {
            $testa = New-Object byte[] 16
            [void]$flusso.Read($testa, 0, 16)
        } finally { $flusso.Dispose() }
        if ([System.Text.Encoding]::ASCII.GetString($testa, 0, 15) -ne "SQLite format 3") { return @{ ok = $false; messaggio = "Il file si apre ma non è un database SQLite." } }
        $peso = if ($info.Length -ge 1MB) { "$([Math]::Round($info.Length / 1MB, 1)) MB" } else { "$([Math]::Ceiling($info.Length / 1KB)) KB" }
        return @{ ok = $true; messaggio = "Accesso riuscito: file di $peso, modificato il $($info.LastWriteTime.ToString('dd/MM/yyyy HH:mm'))." }
    } catch {
        return @{ ok = $false; messaggio = $_.Exception.Message.Replace("$($nome):", $condivisione) }
    } finally {
        Remove-PSDrive -Name $nome -Force -ErrorAction SilentlyContinue
    }
}

function Gestisci-Prova($contesto, [string]$metodo, [string]$tipo) {
    $c = $script:plugin[$tipo]
    if ($metodo -eq "POST") {
        if (-not $c) { Rispondi $contesto 404 @{ errore = "Plugin non configurato su questo totem." }; return }
        $vecchia = $script:prove[$tipo]
        if ($vecchia -and $vecchia.lavoro) { Remove-Job $vecchia.lavoro -Force -ErrorAction SilentlyContinue }
        $script:prove[$tipo] = @{ lavoro = (Start-Job -ScriptBlock $provaFonte -ArgumentList $c.condivisione, $c.file, $c.utente, $c.password); esito = $null }
        Rispondi $contesto 202 @{ stato = "in_corso" }; return
    }
    $p = $script:prove[$tipo]
    if (-not $p) { Rispondi $contesto 404 @{ stato = "nessuna" }; return }
    if (-not $p.esito) {
        if ($p.lavoro.State -eq "Running") { Rispondi $contesto 200 @{ stato = "in_corso" }; return }
        $esito = $null
        try { $esito = Receive-Job $p.lavoro -ErrorAction Stop | Select-Object -Last 1 } catch { $esito = @{ ok = $false; messaggio = $_.Exception.Message } }
        Remove-Job $p.lavoro -Force -ErrorAction SilentlyContinue
        if (-not $esito) { $esito = @{ ok = $false; messaggio = "Prova interrotta." } }
        $p.esito = $esito
        $p.lavoro = $null
        Registra "plugin $($tipo): prova accesso $(if ($esito.ok) { 'riuscita' } else { 'non riuscita: ' + $esito.messaggio })"
    }
    Rispondi $contesto 200 @{ stato = "fatto"; ok = [bool]$p.esito.ok; messaggio = [string]$p.esito.messaggio }
}

function Stato-Plugin {
    $stato = @{}
    foreach ($tipo in $script:plugin.Keys) {
        $s = $script:statoPlugin[$tipo]
        $stato[$tipo] = @{ copiato = $s.copiato; errore = $s.errore; dimensione = $s.dimensione; controllato = $s.controllato; prossimo = $s.prossimo.ToUniversalTime().ToString("o"); in_corso = [bool]$s.lavoro }
    }
    return $stato
}

# --- Stampante Epson di rete ----------------------------------------------------------
# Il player stampa da qui: dalla pagina in HTTPS il browser dovrebbe chiamare la stampante in
# HTTPS, e il suo certificato autofirmato lo rifiuta («Failed to fetch»). Il servizio la chiama in
# HTTP; se la stampante rimanda all'HTTPS (le Epson recenti lo fanno di fabbrica) la chiama in
# HTTPS accettandone il certificato, solo per indirizzi della rete locale.

try {
Add-Type -TypeDefinition @"
using System.Net.Security;
public static class FpStampante {
    public static RemoteCertificateValidationCallback Accetta = delegate { return true; };
}
"@
} catch {
    Registra "stampa Epson in HTTPS non disponibile: $($_.Exception.Message)"
}
[System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor [System.Net.SecurityProtocolType]::Tls12
# Niente «Expect: 100-continue» (.NET lo manda di suo con i POST): il server web delle Epson non lo
# gestisce e chiude la connessione («Connessione sottostante chiusa»).
[System.Net.ServicePointManager]::Expect100Continue = $false
# TLS 1.3 (12288), dove Windows e .NET lo conoscono.
try { [System.Net.ServicePointManager]::SecurityProtocol = [System.Net.ServicePointManager]::SecurityProtocol -bor [System.Net.SecurityProtocolType]12288 } catch { }

function Indirizzo-Rete-Locale([string]$testo) {
    $ip = $null
    if (-not [System.Net.IPAddress]::TryParse($testo, [ref]$ip) -or $ip.AddressFamily -ne "InterNetwork") { return $false }
    $b = $ip.GetAddressBytes()
    return ($b[0] -eq 10) -or ($b[0] -eq 172 -and $b[1] -ge 16 -and $b[1] -le 31) -or ($b[0] -eq 192 -and $b[1] -eq 168) -or ($b[0] -eq 169 -and $b[1] -eq 254)
}

# Una chiamata ePOS-Print: @{ stato; testo; rimando } (rimando: la stampante vuole l'HTTPS).
function Invia-Epson([string]$protocollo, [string]$indirizzo, [byte[]]$corpo) {
    $invio = [System.Net.HttpWebRequest]::Create("$($protocollo)://$indirizzo/cgi-bin/epos/service.cgi?devid=local_printer&timeout=10000")
    $invio.Method = "POST"
    $invio.ContentType = "text/xml; charset=utf-8"
    # Le stesse intestazioni dell'SDK JavaScript di Epson (epos-print): alcune stampanti senza
    # SOAPAction non rispondono.
    $invio.Headers.Add("SOAPAction", '""')
    $invio.IfModifiedSince = [datetime]"1970-01-01"
    $invio.Proxy = $null
    $invio.AllowAutoRedirect = $false
    $invio.KeepAlive = $false
    $invio.ServicePoint.Expect100Continue = $false
    $invio.Timeout = 12000
    $invio.ReadWriteTimeout = 12000
    if ($protocollo -eq "https") { $invio.ServerCertificateValidationCallback = [FpStampante]::Accetta }
    $invio.ContentLength = $corpo.Length
    $risposta = $null
    try {
        $flusso = $invio.GetRequestStream()
        $flusso.Write($corpo, 0, $corpo.Length)
        $flusso.Close()
        $risposta = $invio.GetResponse()
    } catch {
        $e = $_.Exception
        while ($e -and -not ($e -is [System.Net.WebException])) { $e = $e.InnerException }
        if ($e -and $e.Response) { $risposta = $e.Response }
        else { throw $(if ($e) { $e.Message } else { $_.Exception.Message }) }
    }
    try {
        $stato = [int]$risposta.StatusCode
        $verso = [string]$risposta.Headers["Location"]
        $lettore = New-Object System.IO.StreamReader($risposta.GetResponseStream(), [System.Text.Encoding]::UTF8)
        $testo = $lettore.ReadToEnd()
    } finally {
        $risposta.Close()
    }
    return @{ stato = $stato; testo = $testo; rimando = ($stato -ge 300 -and $stato -lt 400 -and $verso -like "https:*") }
}

# --- Stampante di Windows (driver) e stampante di rete senza driver (porta 9100) -------
# Il player manda l'immagine del biglietto (PNG) o i comandi ESC/POS già pronti: qui si
# stampa con il driver di Windows scelto per nome, oppure si inviano i comandi alla porta 9100.

# Se la compilazione non riesce il servizio code resta in piedi: manca solo questa stampa.
$script:stampaWindows = $true
try {
Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @"
using System;
using System.Drawing;
using System.Drawing.Printing;
using System.IO;
public static class FpStampaWindows {
    public static string[] Elenco() {
        var installate = PrinterSettings.InstalledPrinters;
        var elenco = new string[installate.Count];
        installate.CopyTo(elenco, 0);
        return elenco;
    }
    // L'immagine larga quanto l'area stampabile, in alto a sinistra, senza finestre.
    public static void Stampa(string nome, byte[] png) {
        using (var flusso = new MemoryStream(png))
        using (var immagine = Image.FromStream(flusso))
        using (var documento = new PrintDocument()) {
            documento.PrinterSettings.PrinterName = nome;
            if (!documento.PrinterSettings.IsValid) throw new Exception("stampante «" + nome + "» non installata in Windows");
            documento.DocumentName = "FuturaPro - biglietto";
            documento.PrintController = new StandardPrintController();
            documento.DefaultPageSettings.Margins = new Margins(0, 0, 0, 0);
            documento.PrintPage += (mittente, pagina) => {
                float larghezza = pagina.PageSettings.PrintableArea.Width;
                float altezza = larghezza * immagine.Height / immagine.Width;
                pagina.Graphics.InterpolationMode = System.Drawing.Drawing2D.InterpolationMode.NearestNeighbor;
                pagina.Graphics.PixelOffsetMode = System.Drawing.Drawing2D.PixelOffsetMode.Half;
                pagina.Graphics.DrawImage(immagine, 0, 0, larghezza, altezza);
                pagina.HasMorePages = false;
            };
            documento.Print();
        }
    }
}
"@
} catch {
    $script:stampaWindows = $false
    Registra "stampa con i driver di Windows non disponibile: $($_.Exception.Message)"
}

function Stampanti-Windows {
    if (-not $script:stampaWindows) { return @() }
    try { return @([FpStampaWindows]::Elenco()) } catch { return @() }
}

# La stampante predefinita dell'utente collegato al totem (quello del player): il servizio gira
# come SYSTEM, che ha una sua predefinita. Si legge dal registro dell'utente che possiede Esplora risorse.
function Predefinita-Utente {
    # Chi è l'utente del totem: il proprietario di Esplora risorse, oppure quello scritto
    # dall'installazione del player (C:\FuturaPro\impostazioni.json, voce «utente»).
    $sid = $null
    try {
        $esplora = Get-CimInstance Win32_Process -Filter "Name='explorer.exe'" | Select-Object -First 1
        if ($esplora) { $sid = (Invoke-CimMethod -InputObject $esplora -MethodName GetOwnerSid).Sid }
    } catch { }
    if (-not $sid) {
        try {
            $utente = (Get-Content (Join-Path (Split-Path $Cartella -Parent) "impostazioni.json") -Raw | ConvertFrom-Json).utente
            if ($utente) { $sid = (New-Object System.Security.Principal.NTAccount($utente)).Translate([System.Security.Principal.SecurityIdentifier]).Value }
        } catch { }
    }
    if (-not $sid) { return "" }
    try {
        $voce = Get-ItemProperty "Registry::HKEY_USERS\$sid\Software\Microsoft\Windows NT\CurrentVersion\Windows" -Name Device -ErrorAction Stop
        if ($voce.Device) { return ([string]$voce.Device -split ",")[0] }
    } catch { }
    return ""
}

function Gestisci-Stampa-Windows($contesto) {
    $richiesta = $contesto.Request
    $nome = [string]$richiesta.QueryString["stampante"]
    # Senza nome: la predefinita di Windows dell'utente del totem.
    if (-not $nome) { $nome = Predefinita-Utente }
    if (-not $nome) { Rispondi $contesto 502 @{ errore = "nessuna stampante predefinita in Windows per l'utente del totem" }; return }
    if (-not $script:stampaWindows) { Rispondi $contesto 502 @{ errore = "stampa con i driver di Windows non disponibile su questo totem (vedi registro del servizio)" }; return }
    if (@(Stampanti-Windows) -notcontains $nome) {
        Rispondi $contesto 502 @{ errore = "stampante «$nome» non installata in Windows su questo totem" }; return
    }
    $png = Leggi-Byte $richiesta (8MB)
    if ($null -eq $png) { Rispondi $contesto 413 @{ errore = "biglietto troppo grande" }; return }
    try {
        [FpStampaWindows]::Stampa($nome, $png)
    } catch {
        $e = $_.Exception
        while ($e.InnerException) { $e = $e.InnerException }
        Registra "stampa su «$nome»: $($e.Message)"
        Rispondi $contesto 502 @{ errore = "stampa su «$nome» non riuscita ($($e.Message))" }; return
    }
    Rispondi $contesto 204 $null
}

function Gestisci-Stampa-Rete($contesto) {
    $richiesta = $contesto.Request
    $indirizzo = [string]$richiesta.QueryString["indirizzo"]
    $porta = 9100
    if ($indirizzo -match '^(.+):(\d+)$') { $indirizzo = $Matches[1]; $porta = [int]$Matches[2] }
    if (-not (Indirizzo-Rete-Locale $indirizzo)) {
        Rispondi $contesto 400 @{ errore = "indirizzo della stampante non valido (serve un IP della rete locale)" }; return
    }
    if ($porta -lt 9100 -or $porta -gt 9109) { Rispondi $contesto 400 @{ errore = "porta non valida (da 9100 a 9109)" }; return }
    $comandi = Leggi-Byte $richiesta (8MB)
    if ($null -eq $comandi) { Rispondi $contesto 413 @{ errore = "biglietto troppo grande" }; return }
    $cliente = New-Object System.Net.Sockets.TcpClient
    try {
        $collegamento = $cliente.BeginConnect($indirizzo, $porta, $null, $null)
        if (-not $collegamento.AsyncWaitHandle.WaitOne(5000)) { throw "nessuna risposta sulla porta $porta" }
        $cliente.EndConnect($collegamento)
        $flusso = $cliente.GetStream()
        $flusso.WriteTimeout = 15000
        $flusso.Write($comandi, 0, $comandi.Length)
        $flusso.Flush()
        # Chiusura ordinata: si dice «finito» e si legge quello che la stampante manda (stato),
        # finché chiude lei o passano 3 secondi. Chiudere con dati non letti farebbe un reset
        # della connessione, e alcune stampanti buttano via il biglietto appena ricevuto.
        $cliente.Client.Shutdown([System.Net.Sockets.SocketShutdown]::Send)
        $cliente.Client.ReceiveTimeout = 3000
        $avanzo = New-Object byte[] 256
        try { while ($cliente.Client.Receive($avanzo) -gt 0) { } } catch { }
    } catch {
        $motivo = "$_"
        $e = $_.Exception
        while ($e.InnerException) { $e = $e.InnerException; $motivo = $e.Message }
        Registra "stampa su $($indirizzo):$($porta): $motivo"
        Rispondi $contesto 502 @{ errore = "stampante $($indirizzo):$porta non raggiungibile dal totem ($motivo)" }; return
    } finally {
        $cliente.Close()
    }
    Rispondi $contesto 204 $null
}

function Gestisci-Stampa($contesto) {
    $richiesta = $contesto.Request
    $indirizzo = [string]$richiesta.QueryString["indirizzo"]
    if (-not (Indirizzo-Rete-Locale $indirizzo)) {
        Rispondi $contesto 400 @{ errore = "indirizzo della stampante non valido (serve un IP della rete locale)" }; return
    }
    $corpo = Leggi-Byte $richiesta (4MB)
    if ($null -eq $corpo) { Rispondi $contesto 413 @{ errore = "biglietto troppo grande" }; return }
    # Prima in HTTP; in HTTPS se la stampante rimanda lì o chiude la connessione HTTP (alcune,
    # con il rimando attivo, la chiudono appena ricevono un POST).
    $esito = $null
    $problemi = @()
    try {
        $esito = Invia-Epson "http" $indirizzo $corpo
    } catch {
        $problemi += "HTTP: $_"
    }
    if ($null -eq $esito -or $esito.rimando) {
        try {
            $esito = Invia-Epson "https" $indirizzo $corpo
        } catch {
            $problemi += "HTTPS: $_"
            $esito = $null
        }
    }
    if ($null -eq $esito) {
        $motivo = $problemi -join "; "
        Registra "stampa su $($indirizzo): $motivo"
        Rispondi $contesto 502 @{ errore = "stampante $indirizzo non raggiungibile dal totem ($motivo)" }; return
    }
    Rispondi $contesto 200 @{ stato = $esito.stato; risposta = $esito.testo }
}

function Gestisci($contesto) {
    $richiesta = $contesto.Request
    $percorso = $richiesta.Url.AbsolutePath
    $metodo = $richiesta.HttpMethod

    if ($metodo -eq "OPTIONS") { Rispondi $contesto 204 $null; return }

    if ($metodo -eq "GET" -and $percorso -eq "/salute") {
        Rispondi $contesto 200 @{ ok = $true; versione = $Versione; reparti = @($script:reparti).Count }; return
    }
    if ($metodo -eq "GET" -and $percorso -eq "/stato") {
        $attivi = @($script:reparti | Where-Object { $_.attivo } | Sort-Object { [int]$_.ordine }, { $_.nome })
        Rispondi $contesto 200 @{ reparti = @($attivi | ForEach-Object { Stato-Reparto $_ }) }; return
    }
    if ($metodo -eq "GET" -and $percorso -eq "/annunci") {
        Rispondi $contesto 200 @{ file = @(Annunci-Presenti) }; return
    }
    if ($metodo -eq "GET" -and $percorso -match "^/annunci/([0-9a-f]{64})$") {
        $file = Join-Path $cartellaAnnunci $Matches[1]
        if (Test-Path $file) { Rispondi $contesto 200 ([System.IO.File]::ReadAllBytes($file)) "audio/mpeg" }
        else { Rispondi $contesto 404 @{ errore = "Annuncio non presente." } }
        return
    }
    if ($metodo -eq "GET" -and $percorso -match "^/plugin/(prezzo|ingredienti)/?$") {
        Gestisci-Plugin $contesto $Matches[1]; return
    }
    if ($metodo -eq "GET" -and $percorso -eq "/plugin/stato") {
        Rispondi $contesto 200 (Stato-Plugin); return
    }
    if ($metodo -eq "GET" -and $percorso -eq "/certificato.cer") {
        $file = Join-Path $Cartella "certificato.cer"
        if (Test-Path $file) { Rispondi $contesto 200 ([System.IO.File]::ReadAllBytes($file)) "application/x-x509-ca-cert" }
        else { Rispondi $contesto 404 @{ errore = "Nessun certificato." } }
        return
    }

    # --- Solo dal totem stesso ---
    if ($percorso -match "^/plugin/prova/(prezzo|ingredienti)$" -and ($metodo -eq "POST" -or $metodo -eq "GET")) {
        if (-not (Locale $richiesta)) { Rispondi $contesto 403 @{ errore = "Solo dal totem." }; return }
        Gestisci-Prova $contesto $metodo $Matches[1]; return
    }
    if ($metodo -eq "GET" -and $percorso -eq "/stampanti") {
        if (-not (Locale $richiesta)) { Rispondi $contesto 403 @{ errore = "Solo dal totem." }; return }
        Rispondi $contesto 200 @{ stampanti = @(Stampanti-Windows); predefinita = (Predefinita-Utente) }; return
    }
    if ($metodo -eq "POST" -and $percorso -eq "/stampa/windows") {
        if (-not (Locale $richiesta)) { Rispondi $contesto 403 @{ errore = "Solo dal totem." }; return }
        Gestisci-Stampa-Windows $contesto; return
    }
    if ($metodo -eq "POST" -and $percorso -eq "/stampa/rete") {
        if (-not (Locale $richiesta)) { Rispondi $contesto 403 @{ errore = "Solo dal totem." }; return }
        Gestisci-Stampa-Rete $contesto; return
    }
    if ($metodo -eq "POST" -and $percorso -eq "/stampa/epson") {
        if (-not (Locale $richiesta)) { Rispondi $contesto 403 @{ errore = "Solo dal totem." }; return }
        Gestisci-Stampa $contesto; return
    }
    if ($metodo -eq "POST" -and $percorso -eq "/config") {
        if (-not (Locale $richiesta)) { Rispondi $contesto 403 @{ errore = "Solo dal totem." }; return }
        $dati = Leggi-Corpo $richiesta
        $script:reparti = @($dati.reparti)
        $script:totem = @($dati.totem | Where-Object { $_ })
        Salva-Stato
        Imposta-Plugin $dati.plugin
        if ($null -ne $dati.annunci) { Pulisci-Annunci $dati.annunci }
        Registra "configurazione: $(@($script:reparti).Count) reparti"
        Rispondi $contesto 204 $null; return
    }
    if ($metodo -eq "POST" -and $percorso -match "^/annunci/([0-9a-f]{64})$") {
        if (-not (Locale $richiesta)) { Rispondi $contesto 403 @{ errore = "Solo dal totem." }; return }
        $impronta = $Matches[1]
        $byte = Leggi-Byte $richiesta (3MB)
        if ($null -eq $byte) { Rispondi $contesto 413 @{ errore = "File troppo grande." }; return }
        # Si salva solo se il contenuto è proprio quello atteso.
        if ((Impronta-Byte $byte) -ne $impronta) { Rispondi $contesto 400 @{ errore = "Impronta diversa." }; return }
        [System.IO.File]::WriteAllBytes((Join-Path $cartellaAnnunci $impronta), $byte)
        Rispondi $contesto 204 $null; return
    }
    if ($metodo -eq "GET" -and $percorso -eq "/eventi") {
        if (-not (Locale $richiesta)) { Rispondi $contesto 403 @{ errore = "Solo dal totem." }; return }
        $dopo = [int]($richiesta.QueryString["dopo"] -as [int])
        $nuovi = @($script:eventi | Where-Object { [int]$_.seq -gt $dopo } | Select-Object -First 500)
        Rispondi $contesto 200 @{ eventi = $nuovi; ultimo = $script:seq }; return
    }
    if ($metodo -eq "POST" -and $percorso -match "^/emetti/([0-9a-fA-F-]{36})$") {
        if (-not ((Locale $richiesta) -or (Totem-Secondario $richiesta))) { Rispondi $contesto 403 @{ errore = "Solo dai totem della sede." }; return }
        $r = Trova-Reparto $Matches[1]
        if (-not $r -or -not $r.attivo) { Rispondi $contesto 400 @{ errore = "Reparto non disponibile." }; return }
        Rispondi $contesto 201 (Emetti $r); return
    }

    # --- Banco: bilance, tablet, pulsanti (con la chiave del reparto) ---
    if ($metodo -eq "GET" -and ($percorso -eq "/banco/" -or $percorso -eq "/banco")) {
        $file = Join-Path $Cartella "banco.html"
        Rispondi $contesto 200 ([System.IO.File]::ReadAllText($file, [System.Text.Encoding]::UTF8)) "text/html; charset=utf-8"; return
    }
    if ($percorso -match "^/banco/(stato|avanti|indietro|ripeti|azzera|imposta)/?$") {
        $operazione = $Matches[1]
        $r = Reparto-Della-Chiave $richiesta
        if (-not $r) {
            $contesto.Response.Headers["WWW-Authenticate"] = "Pulsante"
            Rispondi $contesto 401 @{ errore = "Chiave non valida." }; return
        }
        if ($operazione -ne "stato") {
            if ($metodo -ne "POST") { Rispondi $contesto 405 $null; return }
            $numero = $null
            if ($operazione -eq "imposta") {
                $dati = Leggi-Corpo $richiesta
                $numero = $dati.numero -as [int]
                if ($null -eq $dati.numero -or $null -eq $numero -or $numero -lt 0 -or $numero -gt [int]$r.massimo) {
                    Rispondi $contesto 400 @{ errore = "Numero da 0 a $($r.massimo)." }; return
                }
            }
            Esegui $operazione $r $numero
        }
        Rispondi $contesto 200 (Stato-Reparto $r); return
    }

    Rispondi $contesto 404 @{ errore = "Non trovato." }
}

# --- Avvio ----------------------------------------------------------------------------

Carica-Stato
Carica-Eventi
Carica-Plugin
$ascoltatore = New-Object System.Net.HttpListener
$ascoltatore.Prefixes.Add("http://+:$PortaHttp/")
if (-not $SoloHttp) { $ascoltatore.Prefixes.Add("https://+:$PortaHttps/") }
$ascoltatore.Start()
Registra "servizio code avviato (versione $Versione, porte $PortaHttp/$PortaHttps)"

while ($ascoltatore.IsListening) {
    # Si aspetta una richiesta, ma ogni pochi secondi si guarda se c'è da copiare un file dei plugin.
    $attesa = $ascoltatore.BeginGetContext($null, $null)
    while (-not $attesa.AsyncWaitHandle.WaitOne(5000)) {
        try { Aggiorna-Plugin } catch { Registra "plugin: $($_.Exception.Message)" }
    }
    $contesto = $ascoltatore.EndGetContext($attesa)
    try { Aggiorna-Plugin } catch { Registra "plugin: $($_.Exception.Message)" }
    try {
        Gestisci $contesto
    } catch {
        Registra "errore: $($_.Exception.Message)"
        try { Rispondi $contesto 500 @{ errore = "Errore interno." } } catch { }
    }
}
