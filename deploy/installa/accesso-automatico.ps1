<#
  FuturaPro - accesso automatico di Windows per monitor e totem.

  Dopo un riavvio (aggiornamenti di Windows, mancanza di corrente) Windows entra da solo con
  l'utente del player, e il player riparte senza che nessuno digiti la password.

  In PowerShell aperto come amministratore, sul PC del monitor o del totem:
    irm http://SERVER/installa/accesso-automatico.ps1 -OutFile $env:TEMP\accesso.ps1
    powershell -ExecutionPolicy Bypass -File $env:TEMP\accesso.ps1

  Cosa fa:
    1. chiede la password dell'utente e la controlla (una password sbagliata bloccherebbe il PC
       al riavvio);
    2. la salva cifrata tra i segreti di sistema di Windows (LSA, come lo strumento «Autologon» di
       Microsoft), mai in chiaro nel registro; nel registro (Winlogon) mette solo l'attivazione e il
       nome utente;
    3. se Windows nasconde l'accesso con password (Windows Hello), lo riattiva;
    4. imposta l'orario di attività di Windows Update sull'apertura del negozio, così i riavvii
       per gli aggiornamenti avvengono a negozio chiuso.

  Opzioni:
    -Utente NOME          utente che entra da solo (predefinito: quello del player, o l'attuale)
    -Apertura 7           ora di apertura del negozio (orario di attività di Windows Update)
    -Chiusura 22          ora di chiusura (al massimo 18 ore dopo l'apertura)
    -Disattiva            toglie l'accesso automatico e cancella la password salvata
#>
#Requires -RunAsAdministrator
param(
    [string]$Utente,
    [ValidateRange(0, 23)][int]$Apertura = 7,
    [ValidateRange(0, 23)][int]$Chiusura = 22,
    [switch]$Disattiva
)

$ErrorActionPreference = "Stop"
$Winlogon = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon"
$Impostazioni = "C:\FuturaPro\impostazioni.json"

function Scrivi([string]$testo, [string]$colore = "Cyan") { Write-Host $testo -ForegroundColor $colore }

# I segreti di sistema (LSA): Winlogon legge da qui la password dell'accesso automatico
# («DefaultPassword»), cifrata, invece che in chiaro dal registro.
Add-Type -TypeDefinition @"
using System;
using System.Runtime.InteropServices;
public static class FpLsa {
    [StructLayout(LayoutKind.Sequential)]
    struct LSA_UNICODE_STRING { public ushort Length; public ushort MaximumLength; public IntPtr Buffer; }
    [StructLayout(LayoutKind.Sequential)]
    struct LSA_OBJECT_ATTRIBUTES { public int Length; public IntPtr RootDirectory; public IntPtr ObjectName; public uint Attributes; public IntPtr SecurityDescriptor; public IntPtr SecurityQualityOfService; }
    [DllImport("advapi32.dll")] static extern uint LsaOpenPolicy(IntPtr SystemName, ref LSA_OBJECT_ATTRIBUTES ObjectAttributes, uint DesiredAccess, out IntPtr PolicyHandle);
    [DllImport("advapi32.dll")] static extern uint LsaStorePrivateData(IntPtr PolicyHandle, ref LSA_UNICODE_STRING KeyName, IntPtr PrivateData);
    [DllImport("advapi32.dll")] static extern uint LsaStorePrivateData(IntPtr PolicyHandle, ref LSA_UNICODE_STRING KeyName, ref LSA_UNICODE_STRING PrivateData);
    [DllImport("advapi32.dll")] static extern uint LsaClose(IntPtr PolicyHandle);
    [DllImport("advapi32.dll")] static extern uint LsaNtStatusToWinError(uint Status);
    static LSA_UNICODE_STRING Stringa(string testo) {
        var s = new LSA_UNICODE_STRING();
        s.Buffer = Marshal.StringToHGlobalUni(testo);
        s.Length = (ushort)(testo.Length * 2);
        s.MaximumLength = (ushort)(testo.Length * 2 + 2);
        return s;
    }
    // valore null: cancella il segreto.
    public static void Salva(string nome, string valore) {
        var attributi = new LSA_OBJECT_ATTRIBUTES();
        IntPtr politica;
        uint esito = LsaOpenPolicy(IntPtr.Zero, ref attributi, 0x00000020 /* POLICY_CREATE_SECRET */, out politica);
        if (esito != 0) throw new System.ComponentModel.Win32Exception((int)LsaNtStatusToWinError(esito));
        var chiave = Stringa(nome);
        try {
            if (valore == null) {
                esito = LsaStorePrivateData(politica, ref chiave, IntPtr.Zero);
            } else {
                var dato = Stringa(valore);
                try { esito = LsaStorePrivateData(politica, ref chiave, ref dato); }
                finally { Marshal.FreeHGlobal(dato.Buffer); }
            }
            // 0xC0000034: il segreto non c'era (cancellarlo non è un errore).
            if (esito != 0 && !(valore == null && esito == 0xC0000034)) throw new System.ComponentModel.Win32Exception((int)LsaNtStatusToWinError(esito));
        } finally {
            Marshal.FreeHGlobal(chiave.Buffer);
            LsaClose(politica);
        }
    }
}
"@

# --- Disattivazione ------------------------------------------------------------------------
if ($Disattiva) {
    Set-ItemProperty -Path $Winlogon -Name AutoAdminLogon -Value "0"
    Remove-ItemProperty -Path $Winlogon -Name DefaultPassword -ErrorAction SilentlyContinue
    [FpLsa]::Salva("DefaultPassword", $null)
    Scrivi "Accesso automatico disattivato e password salvata cancellata." "Green"
    exit 0
}

# --- Utente ----------------------------------------------------------------------------------
if (-not $Utente -and (Test-Path $Impostazioni)) {
    try { $Utente = (Get-Content $Impostazioni -Raw | ConvertFrom-Json).utente } catch { $Utente = $null }
}
if (-not $Utente) { $Utente = $env:USERNAME }
$risposta = Read-Host "Utente che entra da solo all'accensione [$Utente]"
if ($risposta) { $Utente = $risposta }
# «PC\nome» o «nome»: il dominio è il nome del PC per un utente locale.
$dominio = $env:COMPUTERNAME
if ($Utente -match '^(.+)\\(.+)$') { $dominio = $Matches[1]; $Utente = $Matches[2] }

# --- Password, controllata prima di salvarla -------------------------------------------------
Add-Type -AssemblyName System.DirectoryServices.AccountManagement
$contesto = New-Object System.DirectoryServices.AccountManagement.PrincipalContext(
    $(if ($dominio -eq $env:COMPUTERNAME) { "Machine" } else { "Domain" }), $dominio)
for ($tentativo = 1; ; $tentativo++) {
    $sicura = Read-Host "Password di $dominio\$Utente" -AsSecureString
    $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR([Runtime.InteropServices.Marshal]::SecureStringToBSTR($sicura))
    if ($contesto.ValidateCredentials($Utente, $password)) { break }
    Scrivi "Password non corretta (o utente inesistente)." "Red"
    if ($tentativo -ge 3) { throw "Accesso automatico non attivato: password non verificata." }
}

# --- Winlogon (registro) e segreto LSA ---------------------------------------------------------
[FpLsa]::Salva("DefaultPassword", $password)
$password = $null
Remove-ItemProperty -Path $Winlogon -Name DefaultPassword -ErrorAction SilentlyContinue   # mai in chiaro
Set-ItemProperty -Path $Winlogon -Name AutoAdminLogon -Value "1"
Set-ItemProperty -Path $Winlogon -Name DefaultUserName -Value $Utente
Set-ItemProperty -Path $Winlogon -Name DefaultDomainName -Value $dominio
# Un tentativo fallito non deve spegnere l'accesso automatico per sempre.
Remove-ItemProperty -Path $Winlogon -Name AutoLogonCount -ErrorAction SilentlyContinue
Scrivi "Accesso automatico attivato per $dominio\$Utente (password cifrata nei segreti di sistema)." "Green"

# --- Windows Hello: riattiva l'accesso con password ------------------------------------------
$senzaPassword = "HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\PasswordLess\Device"
if (Test-Path $senzaPassword) {
    $attuale = (Get-ItemProperty -Path $senzaPassword -Name DevicePasswordLessBuildVersion -ErrorAction SilentlyContinue).DevicePasswordLessBuildVersion
    if ($attuale -ne 0) {
        Set-ItemProperty -Path $senzaPassword -Name DevicePasswordLessBuildVersion -Value 0 -Type DWord
        Scrivi "Windows Hello: riattivato l'accesso con password (serve all'accesso automatico)." "Green"
    }
}

# --- Windows Update: riavvii fuori dall'orario del negozio ------------------------------------
$durata = ($Chiusura - $Apertura + 24) % 24
if ($durata -lt 1 -or $durata -gt 18) {
    Scrivi "Orario di attività non impostato: tra apertura e chiusura servono da 1 a 18 ore." "Yellow"
} else {
    $ux = "HKLM:\SOFTWARE\Microsoft\WindowsUpdate\UX\Settings"
    New-Item -Path $ux -Force | Out-Null
    Set-ItemProperty -Path $ux -Name ActiveHoursStart -Value $Apertura -Type DWord
    Set-ItemProperty -Path $ux -Name ActiveHoursEnd -Value $Chiusura -Type DWord
    Set-ItemProperty -Path $ux -Name SmartActiveHoursState -Value 0 -Type DWord
    Scrivi "Windows Update: riavvii solo fuori dalle $Apertura-$Chiusura (orario di attività)." "Green"
}

Scrivi "`nFatto. Al prossimo riavvio Windows entra da solo e il player riparte." "Green"
Write-Host "  Per toglierlo: stesso comando con -Disattiva."
Write-Host "  Ricorda nel BIOS: 'Restore on AC power loss: Power On' (riaccensione dopo un'interruzione di corrente)."
