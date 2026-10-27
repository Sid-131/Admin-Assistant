# OneFS 9.12.0.0 Documentation Downloader
# Run this script on your machine to download all RAG source documents
# Usage: Right-click -> Run with PowerShell

$docsDir = "$PSScriptRoot\docs"
if (-not (Test-Path $docsDir)) {
    New-Item -ItemType Directory -Path $docsDir | Out-Null
}

$docs = @(
    @{
        Name = "Web Administration Guide (PRIMARY)"
        File = "onefs-9120-web-admin-guide.pdf"
        Url  = "https://dl.dell.com/content/manual61406859-powerscale-onefs-9-12-0-0-web-administration-guide.pdf"
    },
    @{
        Name = "CLI Administration Guide"
        File = "onefs-9120-cli-admin-guide.pdf"
        Url  = "https://dl.dell.com/content/manual60806629-powerscale-onefs-9-12-0-0-cli-administration-guide.pdf"
    },
    @{
        Name = "CLI Command Reference"
        File = "onefs-9120-cli-command-reference.pdf"
        Url  = "https://dl.dell.com/content/manual51938935-powerscale-onefs-9-12-0-0-cli-command-reference.pdf"
    },
    @{
        Name = "Security Configuration Guide"
        File = "onefs-9120-security-config-guide.pdf"
        Url  = "https://dl.dell.com/content/manual53532926-powerscale-onefs-9-12-0-0-security-configuration-guide.pdf"
    },
    @{
        Name = "Technical Specifications Guide"
        File = "onefs-9120-technical-specs.pdf"
        Url  = "https://dl.dell.com/content/manual28144700-powerscale-onefs-9-12-0-0-technical-specifications-guide.pdf"
    },
    @{
        Name = "Backup and Recovery Guide"
        File = "onefs-9120-backup-recovery-guide.pdf"
        Url  = "https://dl.dell.com/content/manual28412948-powerscale-onefs-9-12-0-0-backup-and-recovery-guide.pdf"
    },
    @{
        Name = "CloudPools Administration Guide"
        File = "onefs-9120-cloudpools-admin-guide.pdf"
        Url  = "https://dl.dell.com/content/manual27693880-powerscale-onefs-9-12-0-0-cloudpools-administration-guide.pdf"
    },
    @{
        Name = "HDFS Configuration Guide"
        File = "onefs-hdfs-config-guide.pdf"
        Url  = "https://dl.dell.com/content/manual31880569-powerscale-onefs-hdfs-configuration-guide.pdf"
    },
    @{
        Name = "Event Reference Guide"
        File = "onefs-event-reference.pdf"
        Url  = "https://dl.dell.com/content/manual73474568-powerscale-onefs-event-reference-guide.pdf"
    },
    @{
        Name = "Upgrade Planning and Process Guide"
        File = "onefs-upgrade-planning-guide.pdf"
        Url  = "https://dl.dell.com/content/manual81478978-powerscale-onefs-upgrade-planning-and-process-guide.pdf"
    },
    @{
        Name = "Supportability and Compatibility Guide"
        File = "onefs-supportability-compatibility-guide.pdf"
        Url  = "https://dl.dell.com/content/manual45268461-powerscale-onefs-supportability-and-compatibility-guide.pdf"
    }
)

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  OneFS 9.12 Documentation Downloader" -ForegroundColor Cyan
Write-Host "  Saving to: $docsDir" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

$success = 0
$failed  = 0

foreach ($doc in $docs) {
    $dest = Join-Path $docsDir $doc.File
    if (Test-Path $dest) {
        $size = (Get-Item $dest).Length
        if ($size -gt 10000) {
            Write-Host "  [SKIP] $($doc.Name) (already exists)" -ForegroundColor Yellow
            $success++
            continue
        }
    }

    Write-Host "  Downloading: $($doc.Name)..." -ForegroundColor White -NoNewline
    try {
        # Dell's CDN returns 403 without a browser User-Agent
        $ua = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        Invoke-WebRequest -Uri $doc.Url -OutFile $dest -UserAgent $ua -Headers @{ "Accept" = "application/pdf,*/*" } -MaximumRedirection 5 -TimeoutSec 180
        $size = [math]::Round((Get-Item $dest).Length / 1MB, 1)
        Write-Host " $size MB" -ForegroundColor Green
        $success++
    } catch {
        Write-Host " FAILED" -ForegroundColor Red
        Write-Host "    Error: $($_.Exception.Message)" -ForegroundColor Red
        $failed++
    }
}

Write-Host ""
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host "  Done: $success downloaded, $failed failed" -ForegroundColor Cyan
Write-Host "  Docs folder: $docsDir" -ForegroundColor Cyan
Write-Host "==================================================" -ForegroundColor Cyan
Write-Host ""

if ($failed -gt 0) {
    Write-Host "NOTE: Release Notes require a Dell account login." -ForegroundColor Yellow
    Write-Host "      All other docs should download without login." -ForegroundColor Yellow
    Write-Host ""
}

Read-Host "Press Enter to close"
