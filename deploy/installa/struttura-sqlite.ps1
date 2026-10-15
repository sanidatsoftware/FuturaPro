<#
  FuturaPro - riassunto di un file SQLite (.db) di un gestionale.

  Scrive in un file di testo la struttura (tabelle, colonne, indici, numero di righe) e qualche
  riga di esempio di ogni tabella: bastano per preparare la query dei plugin Info Prezzo e Info
  Ingredienti senza mandare il file intero. Apre il file in sola lettura e non lo modifica;
  usa winsqlite3.dll, già presente in Windows 10/11: non serve installare nulla.

  Uso (PowerShell):
    powershell -ExecutionPolicy Bypass -File struttura-sqlite.ps1 -File "C:\Utility\DigiProject\digiproject.db"
  Con -Codici si cercano anche dei codici (es. le cifre sotto il codice a barre di un'etichetta
  della bilancia) in tutte le colonne di testo e numeriche: aiuta a capire dove sta il PLU.
    ... -Codici "2000123012345,2100456009876"
#>
param(
    [Parameter(Mandatory = $true)][string]$File,
    [string]$Uscita = (Join-Path ([Environment]::GetFolderPath("Desktop")) "struttura-db.txt"),
    [int]$Righe = 4,
    [string]$Codici = ""
)

$ErrorActionPreference = "Stop"
if (-not (Test-Path -LiteralPath $File)) { throw "File non trovato: $File" }

Add-Type -TypeDefinition @"
using System;
using System.Collections.Generic;
using System.Runtime.InteropServices;
using System.Text;

public static class FpEsplora
{
    const string L = "winsqlite3.dll";
    const CallingConvention C = CallingConvention.StdCall;
    [DllImport(L, CallingConvention = C)] static extern int sqlite3_open_v2(byte[] file, out IntPtr db, int flags, IntPtr vfs);
    [DllImport(L, CallingConvention = C)] static extern int sqlite3_close_v2(IntPtr db);
    [DllImport(L, CallingConvention = C)] static extern int sqlite3_busy_timeout(IntPtr db, int ms);
    [DllImport(L, CallingConvention = C)] static extern IntPtr sqlite3_errmsg(IntPtr db);
    [DllImport(L, CallingConvention = C)] static extern int sqlite3_prepare_v2(IntPtr db, byte[] sql, int n, out IntPtr stmt, IntPtr tail);
    [DllImport(L, CallingConvention = C)] static extern int sqlite3_step(IntPtr stmt);
    [DllImport(L, CallingConvention = C)] static extern int sqlite3_finalize(IntPtr stmt);
    [DllImport(L, CallingConvention = C)] static extern int sqlite3_column_count(IntPtr stmt);
    [DllImport(L, CallingConvention = C)] static extern IntPtr sqlite3_column_name(IntPtr stmt, int i);
    [DllImport(L, CallingConvention = C)] static extern int sqlite3_column_type(IntPtr stmt, int i);
    [DllImport(L, CallingConvention = C)] static extern IntPtr sqlite3_column_text(IntPtr stmt, int i);
    [DllImport(L, CallingConvention = C)] static extern int sqlite3_column_bytes(IntPtr stmt, int i);

    static byte[] Z(string s) { return Encoding.UTF8.GetBytes(s + "\0"); }

    static string Testo(IntPtr p, int n)
    {
        if (p == IntPtr.Zero) return null;
        if (n < 0) { n = 0; while (Marshal.ReadByte(p, n) != 0) n++; }
        byte[] b = new byte[n];
        Marshal.Copy(p, b, 0, n);
        return Encoding.UTF8.GetString(b);
    }

    // Le righe della query (la prima è l'intestazione), al massimo «massimo».
    public static List<string[]> Query(string percorso, string sql, int massimo)
    {
        IntPtr db;
        if (sqlite3_open_v2(Z(percorso), out db, 1, IntPtr.Zero) != 0) throw new Exception("Il file non si apre come SQLite.");
        sqlite3_busy_timeout(db, 5000);
        IntPtr st = IntPtr.Zero;
        List<string[]> righe = new List<string[]>();
        try
        {
            if (sqlite3_prepare_v2(db, Z(sql), -1, out st, IntPtr.Zero) != 0) throw new Exception(Testo(sqlite3_errmsg(db), -1));
            int n = sqlite3_column_count(st);
            string[] testa = new string[n];
            for (int c = 0; c < n; c++) testa[c] = Testo(sqlite3_column_name(st, c), -1);
            righe.Add(testa);
            while (righe.Count <= massimo && sqlite3_step(st) == 100)
            {
                string[] r = new string[n];
                for (int c = 0; c < n; c++)
                {
                    int tipo = sqlite3_column_type(st, c);
                    if (tipo == 5) r[c] = "NULL";
                    else if (tipo == 4) r[c] = "<blob " + sqlite3_column_bytes(st, c) + " byte>";
                    else
                    {
                        IntPtr t = sqlite3_column_text(st, c);
                        string v = Testo(t, sqlite3_column_bytes(st, c));
                        r[c] = v.Length > 300 ? v.Substring(0, 300) + "…" : v;
                    }
                }
                righe.Add(r);
            }
            return righe;
        }
        finally
        {
            if (st != IntPtr.Zero) sqlite3_finalize(st);
            sqlite3_close_v2(db);
        }
    }
}
"@

$testo = New-Object System.Text.StringBuilder
function Scrivi([string]$riga) { [void]$testo.AppendLine($riga) }
# La virgola davanti: l'elenco resta un elenco anche con una sola riga (PowerShell lo «srotolerebbe»).
function Q([string]$sql, [int]$max = 100000) { return ,([FpEsplora]::Query($File, $sql, $max)) }
function Nome([string]$n) { return '"' + $n.Replace('"', '""') + '"' }

$info = Get-Item -LiteralPath $File
Scrivi "File: $($info.Name)  ($([Math]::Round($info.Length / 1MB, 1)) MB, modificato $($info.LastWriteTime))"
Scrivi ""
$oggetti = Q "SELECT type, name, tbl_name, sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%' ORDER BY type DESC, name"
$tabelle = @($oggetti | Select-Object -Skip 1 | Where-Object { $_[0] -eq "table" } | ForEach-Object { $_[1] })
Write-Host "Tabelle trovate: $($tabelle.Count)"
foreach ($t in $tabelle) {
    Write-Host "  $t"
    $conta = (Q "SELECT count(*) FROM $(Nome $t)")[1][0]
    Scrivi ("=" * 80)
    Scrivi "TABELLA $t  ($conta righe)"
    Scrivi (($oggetti | Where-Object { $_[0] -eq "table" -and $_[1] -eq $t })[3])
    foreach ($i in ($oggetti | Where-Object { $_[0] -eq "index" -and $_[2] -eq $t -and $_[3] })) { Scrivi $i[3] }
    if ([int]$conta -gt 0) {
        Scrivi "-- prime righe"
        foreach ($r in (Q "SELECT * FROM $(Nome $t) LIMIT $Righe")) { Scrivi ($r -join " | ") }
        if ([int]$conta -gt $Righe) {
            Scrivi "-- righe a caso"
            foreach ($r in (Q "SELECT * FROM $(Nome $t) ORDER BY random() LIMIT $Righe" | Select-Object -Skip 1)) { Scrivi ($r -join " | ") }
        }
    }
    Scrivi ""
}
foreach ($v in ($oggetti | Select-Object -Skip 1 | Where-Object { $_[0] -eq "view" })) { Scrivi "VISTA $($v[1])"; Scrivi $v[3]; Scrivi "" }

# I codici cercati: in quali tabelle e colonne compaiono (interi, senza zeri davanti, o le prime cifre).
foreach ($codice in @($Codici -split "[,; ]+" | Where-Object { $_ })) {
    $cifre = $codice -replace "[^0-9]", ""
    if (-not $cifre) { continue }
    $varianti = @($cifre, $cifre.TrimStart("0"))
    if ($cifre.Length -eq 13) { foreach ($n in 4..7) { $varianti += $cifre.Substring(2, $n).TrimStart("0") }; $varianti += $cifre.Substring(0, 7) }
    $varianti = @($varianti | Where-Object { $_ } | Select-Object -Unique)
    Scrivi ("=" * 80)
    Scrivi "CODICE $cifre  (varianti cercate: $($varianti -join ', '))"
    Write-Host "Cerco $cifre..."
    foreach ($t in $tabelle) {
        $colonne = Q "SELECT name, type FROM pragma_table_info('$($t.Replace("'", "''"))')"
        foreach ($c in ($colonne | Select-Object -Skip 1)) {
            if ($c[1] -match "BLOB") { continue }
            $elenco = ($varianti | ForEach-Object { "'$_'" }) -join ","
            $trovate = Q "SELECT * FROM $(Nome $t) WHERE CAST($(Nome $c[0]) AS TEXT) IN ($elenco) OR ltrim(CAST($(Nome $c[0]) AS TEXT), '0') IN ($elenco) LIMIT 3" 3
            if ($trovate.Count -gt 1) {
                Scrivi "-- $t.$($c[0])"
                foreach ($r in $trovate) { Scrivi ($r -join " | ") }
            }
        }
    }
    Scrivi ""
}

[System.IO.File]::WriteAllText($Uscita, $testo.ToString(), (New-Object System.Text.UTF8Encoding($true)))
Write-Host ""
Write-Host "Fatto: $Uscita ($([Math]::Round((Get-Item $Uscita).Length / 1KB)) KB). Allegalo in chat." -ForegroundColor Green
