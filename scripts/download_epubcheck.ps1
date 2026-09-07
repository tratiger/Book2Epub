<#
.SYNOPSIS
    Downloads and extracts EPUBCheck 5.3.0 to .tools/epubcheck-5.3.0/
.DESCRIPTION
    Complies with Book2Epub M0 specification. Uses canonical GitHub release ZIP.
#>
[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$RepoRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$ToolsDir = Join-Path $RepoRoot ".tools"
$DownloadsDir = Join-Path $ToolsDir "downloads"
$TargetDir = Join-Path $ToolsDir "epubcheck-5.3.0"
$JarPath = Join-Path $TargetDir "epubcheck.jar"
$ZipUrl = "https://github.com/w3c/epubcheck/releases/download/v5.3.0/epubcheck-5.3.0.zip"
$ZipFile = Join-Path $DownloadsDir "epubcheck-5.3.0.zip"

Write-Host "==> EPUBCheck 5.3.0 Bootstrap" -ForegroundColor Cyan

# Check if already installed and valid
if (Test-Path $JarPath) {
    Write-Host "EPUBCheck 5.3.0 is already installed at $JarPath" -ForegroundColor Green
    try {
        java -jar $JarPath --version
        return
    } catch {
        Write-Warning "Existing epubcheck.jar verification failed. Re-downloading..."
    }
}

New-Item -ItemType Directory -Force -Path $DownloadsDir | Out-Null
New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null

Write-Host "Downloading EPUBCheck 5.3.0 from: $ZipUrl"
Invoke-WebRequest -Uri $ZipUrl -OutFile $ZipFile -UseBasicParsing

if (-not (Test-Path $ZipFile) -or ((Get-Item $ZipFile).Length -lt 1000000)) {
    throw "Downloaded zip file is missing or unexpectedly small: $ZipFile"
}

Write-Host "Extracting $ZipFile to $ToolsDir..."
if (Test-Path $TargetDir) {
    Remove-Item -Recurse -Force $TargetDir
}

Expand-Archive -Path $ZipFile -DestinationPath $ToolsDir -Force

if (-not (Test-Path $JarPath)) {
    throw "Extraction failed to produce $JarPath"
}

Write-Host "Verifying EPUBCheck installation..." -ForegroundColor Cyan
java -jar $JarPath --version

Write-Host "EPUBCheck 5.3.0 setup completed successfully." -ForegroundColor Green
