[CmdletBinding()]
param(
    [switch]$Clean,
    [switch]$WithTorrent,
    [string]$Python = "python",
    [string]$SigningCertificateThumbprint = $env:ANIRSS_SIGNING_CERT_THUMBPRINT,
    [string]$TimestampUrl = "http://timestamp.acs.microsoft.com",
    [switch]$RequireSignature
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

$projectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

Push-Location $projectRoot
try {
    & $Python -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 'AniRSS requires Python 3.11+')"
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.11 or newer is required."
    }
    $version = (& $Python -c "import tomllib; print(tomllib.load(open('pyproject.toml', 'rb'))['project']['version'])").Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($version)) {
        throw "Could not read the AniRSS version from pyproject.toml."
    }
    $releaseNotes = "RELEASE_NOTES-$version.md"
    if (-not (Test-Path -LiteralPath (Join-Path $projectRoot $releaseNotes))) {
        throw "Missing release notes: $releaseNotes"
    }
    if ($RequireSignature -and [string]::IsNullOrWhiteSpace($SigningCertificateThumbprint)) {
        throw "-RequireSignature needs -SigningCertificateThumbprint or ANIRSS_SIGNING_CERT_THUMBPRINT."
    }
    if (-not [string]::IsNullOrWhiteSpace($SigningCertificateThumbprint) -and
        $SigningCertificateThumbprint -notmatch '^[0-9A-Fa-f]{40}$') {
        throw "Signing certificate thumbprint must be a 40-character SHA-1 thumbprint."
    }

    $installTarget = if ($WithTorrent) { ".[packaging,torrent]" } else { ".[packaging]" }
    Write-Host "Installing AniRSS build dependencies from $installTarget ..."
    & $Python -m pip install -e $installTarget
    if ($LASTEXITCODE -ne 0) {
        throw "Dependency installation failed."
    }

    $pyinstallerArguments = @("-m", "PyInstaller", "--noconfirm")
    if ($Clean) {
        $pyinstallerArguments += "--clean"
    }
    $pyinstallerArguments += "AniRSS.spec"

    Write-Host "Building AniRSS ..."
    $previousBundleTorrent = $env:ANIRSS_BUNDLE_TORRENT
    try {
        $env:ANIRSS_BUNDLE_TORRENT = if ($WithTorrent) { "1" } else { "0" }
        & $Python @pyinstallerArguments
        if ($LASTEXITCODE -ne 0) {
            throw "PyInstaller build failed."
        }
    }
    finally {
        if ($null -eq $previousBundleTorrent) {
            Remove-Item Env:ANIRSS_BUNDLE_TORRENT -ErrorAction SilentlyContinue
        }
        else {
            $env:ANIRSS_BUNDLE_TORRENT = $previousBundleTorrent
        }
    }

    $bundleRoot = Join-Path $projectRoot "dist\AniRSS"
    $executablePath = Join-Path $bundleRoot "AniRSS.exe"
    if (-not [string]::IsNullOrWhiteSpace($SigningCertificateThumbprint)) {
        $signTool = Get-Command "signtool.exe" -ErrorAction SilentlyContinue
        if ($null -eq $signTool) {
            throw "signtool.exe was not found. Install the Windows SDK signing tools."
        }
        Write-Host "Signing AniRSS.exe with the configured publisher certificate ..."
        & $signTool.Source sign /sha1 $SigningCertificateThumbprint /fd SHA256 /tr $TimestampUrl /td SHA256 $executablePath
        if ($LASTEXITCODE -ne 0) {
            throw "Authenticode signing failed."
        }
        $signature = Get-AuthenticodeSignature -LiteralPath $executablePath
        if ($signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
            throw "AniRSS.exe signature verification failed: $($signature.StatusMessage)"
        }
    }
    elseif ($RequireSignature) {
        throw "A valid Authenticode signature is required for release builds."
    }
    else {
        Write-Warning "AniRSS.exe is unsigned. This is a developer build and must not be distributed as an official release."
    }
    foreach ($document in @("LICENSE", "QUICKSTART.txt", $releaseNotes, "THIRD_PARTY_NOTICES.md")) {
        Copy-Item -LiteralPath (Join-Path $projectRoot $document) -Destination $bundleRoot -Force
    }
    $licenseTarget = Join-Path $bundleRoot "licenses"
    New-Item -ItemType Directory -Force -Path $licenseTarget | Out-Null
    Copy-Item -Path (Join-Path $projectRoot "resources\licenses\*") -Destination $licenseTarget -Recurse -Force

    Write-Host "Build complete: $projectRoot\dist\AniRSS"
    if ($WithTorrent) {
        Write-Host "BT was requested; verify libtorrent loads on a clean target system before release."
    }
}
finally {
    Pop-Location
}
