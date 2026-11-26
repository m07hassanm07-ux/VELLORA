[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Installer,
    [Parameter(Mandatory)][string]$Manifest,
    [Parameter(Mandatory)][string]$PublisherThumbprint,
    [Parameter(Mandatory)][uri]$TimestampUrl,
    [Parameter(Mandatory)][string]$OutputDirectory,
    [string]$SignTool = 'signtool.exe'
)

$ErrorActionPreference = 'Stop'
$thumbprint = $PublisherThumbprint -replace '\s', ''
if ($thumbprint -notmatch '^[0-9a-f]{40}$' -or
    -not $TimestampUrl.IsAbsoluteUri -or $TimestampUrl.Scheme -ne 'https') {
    throw 'Provide a certificate thumbprint and an HTTPS timestamp endpoint.'
}
$verified = & "$PSScriptRoot/verify_installer.ps1" -Installer $Installer -Manifest $Manifest
$certificate = Get-Item -LiteralPath "Cert:\CurrentUser\My\$thumbprint" -ErrorAction SilentlyContinue
if (-not $certificate -or -not $certificate.HasPrivateKey) {
    throw 'The requested signing certificate and private key must be accessible in CurrentUser\My.'
}
$tool = Get-Command $SignTool -CommandType Application
$directory = New-Item -ItemType Directory -Path $OutputDirectory
$signed = Join-Path $directory.FullName ([IO.Path]::GetFileName($verified.Path))
Copy-Item -LiteralPath $verified.Path -Destination $signed
& $tool.Source sign /sha1 $thumbprint /fd SHA256 /tr $TimestampUrl.AbsoluteUri /td SHA256 $signed
if ($LASTEXITCODE -ne 0) { throw 'SignTool signing failed. Discard the staging copy.' }
& $tool.Source verify /pa /tw $signed
if ($LASTEXITCODE -ne 0) { throw 'SignTool verification failed. Discard the staging copy.' }
$signature = Get-AuthenticodeSignature -LiteralPath $signed
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Thumbprint -ne $thumbprint -or
    -not $signature.TimeStamperCertificate) {
    throw 'Publisher or timestamp verification failed. Discard the staging copy.'
}
$hash = (Get-FileHash -LiteralPath $signed -Algorithm SHA256).Hash.ToLowerInvariant()
$signedManifest = Join-Path $directory.FullName 'SHA256SUMS.txt'
[IO.File]::WriteAllText($signedManifest, "$hash  $([IO.Path]::GetFileName($signed))`n")
& "$PSScriptRoot/verify_installer.ps1" -Installer $signed -Manifest $signedManifest -PublisherThumbprint $thumbprint
