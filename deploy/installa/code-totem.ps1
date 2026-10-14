<#
  FuturaPro - servizio code del totem.

  Tiene le code dei reparti del negozio: assegna i numeri dei biglietti, riceve
  le chiamate di bilance e banchi, dà i numeri ai monitor. Non dipende dal server
  centrale: se la rete verso il server cade, il negozio continua a dare i turni.
  Dal server arriva solo la configurazione (nomi, colori, chiavi delle bilance),
  che il player del totem gli passa a ogni aggiornamento, con i file audio degli
  annunci dei numeri (es. «SALUMERIA_27.mp3»): restano qui, in annunci\, e i monitor
  del negozio li prendono da qui anche quando il server non è raggiungibile.

  Lo installa e lo avvia player-windows.ps1 (tipo totem) come attività di sistema.
  Porte: 8443 HTTPS (monitor e totem), 8090 HTTP (bilance e banchi in rete locale).

  Chi può fare cosa:
    - leggere i numeri (/stato): chiunque in rete; sono gli stessi mostrati a schermo;
    - leggere i file degli annunci (/annunci/<impronta>): chiunque in rete;
    - emettere biglietti, ricevere la configurazione e i file: solo il totem stesso (127.0.0.1);
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
$Versione = "1.1"
$fileStato = Join-Path $Cartella "stato.json"
$fileRegistro = Join-Path $Cartella "registro.log"
$cartellaAnnunci = Join-Path $Cartella "annunci"
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
$script:code = @{}

function Carica-Stato {
    if (-not (Test-Path $fileStato)) { return }
    $dati = Get-Content -Raw -Encoding UTF8 $fileStato | ConvertFrom-Json
    if ($dati.reparti) { $script:reparti = @($dati.reparti) }
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
    $testo = [pscustomobject]@{ reparti = $script:reparti; code = $elenco } | ConvertTo-Json -Depth 6
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
    Registra "$operazione $($r.nome) -> $(Numero $c.chiamati ([int]$r.massimo))"
}

function Emetti($r) {
    $c = Coda ([string]$r.id)
    # Se il banco è andato avanti senza biglietti, il primo biglietto parte da lì.
    $c.emessi = [Math]::Max($c.emessi, $c.chiamati) + 1
    Salva-Stato
    $stato = Stato-Reparto $r
    Registra "biglietto $($r.nome) $($stato.ultimo_emesso)"
    return [ordered]@{
        reparto_id = [string]$r.id; reparto = $r.nome; colore = $r.colore; colore_testo = $r.colore_testo
        numero = $stato.ultimo_emesso; davanti = [Math]::Max(0, $stato.in_coda - 1)
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
    if ($metodo -eq "GET" -and $percorso -eq "/certificato.cer") {
        $file = Join-Path $Cartella "certificato.cer"
        if (Test-Path $file) { Rispondi $contesto 200 ([System.IO.File]::ReadAllBytes($file)) "application/x-x509-ca-cert" }
        else { Rispondi $contesto 404 @{ errore = "Nessun certificato." } }
        return
    }

    # --- Solo dal totem stesso ---
    if ($metodo -eq "POST" -and $percorso -eq "/config") {
        if (-not (Locale $richiesta)) { Rispondi $contesto 403 @{ errore = "Solo dal totem." }; return }
        $dati = Leggi-Corpo $richiesta
        $script:reparti = @($dati.reparti)
        Salva-Stato
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
    if ($metodo -eq "POST" -and $percorso -match "^/emetti/([0-9a-fA-F-]{36})$") {
        if (-not (Locale $richiesta)) { Rispondi $contesto 403 @{ errore = "Solo dal totem." }; return }
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
$ascoltatore = New-Object System.Net.HttpListener
$ascoltatore.Prefixes.Add("http://+:$PortaHttp/")
if (-not $SoloHttp) { $ascoltatore.Prefixes.Add("https://+:$PortaHttps/") }
$ascoltatore.Start()
Registra "servizio code avviato (versione $Versione, porte $PortaHttp/$PortaHttps)"

while ($ascoltatore.IsListening) {
    $contesto = $ascoltatore.GetContext()
    try {
        Gestisci $contesto
    } catch {
        Registra "errore: $($_.Exception.Message)"
        try { Rispondi $contesto 500 @{ errore = "Errore interno." } } catch { }
    }
}
