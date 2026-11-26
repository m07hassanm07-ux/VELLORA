[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Installer,
    [Parameter(Mandatory)][string]$Manifest,
    [string]$PublisherThumbprint
)

$ErrorActionPreference = 'Stop'
$package = Get-Item -LiteralPath $Installer
if ($package.PSIsContainer -or $package.Name -notmatch '^Vellora-[0-9]+\.[0-9]+\.[0-9]+-Setup-x64\.exe$') {
    throw 'Expected a versioned VELLORA x64 installer.'
}
$filename = [regex]::Escape($package.Name)
$entries = @(Get-Content -LiteralPath $Manifest | ForEach-Object {
    if ($_ -match "^([0-9a-f]{64})\s+$filename$") { $Matches[1] }
})
if ($entries.Count -ne 1) {
    throw 'The manifest must contain exactly one hash for this installer.'
}
$actualHash = (Get-FileHash -LiteralPath $package.FullName -Algorithm SHA256).Hash
if ($actualHash -ne $entries[0]) {
    throw 'Installer SHA-256 does not match the release manifest.'
}

$signature = Get-AuthenticodeSignature -LiteralPath $package.FullName
if ($PublisherThumbprint) {
    $expected = $PublisherThumbprint -replace '\s', ''
    if ($expected -notmatch '^[0-9a-f]{40}$' -or
        $signature.Status -ne 'Valid' -or
        $signature.SignerCertificate.Thumbprint -ne $expected) {
        throw 'A valid Authenticode signature from the expected publisher is required.'
    }
}
[pscustomobject]@{
    Path = $package.FullName
    SHA256 = $actualHash
    SignatureStatus = $signature.Status
    PublisherVerified = [bool]$PublisherThumbprint
}
