param(
    [string]$Root = ".",
    [switch]$IncludeCodeBlocks
)

$ErrorActionPreference = "Stop"

$rootPath = (Resolve-Path -Path $Root).Path
$mdFiles = Get-ChildItem -Path $rootPath -Recurse -File -Filter "*.md"
$brokenLinks = @()

foreach ($file in $mdFiles) {
    $content = Get-Content -LiteralPath $file.FullName -Raw

    if (-not $IncludeCodeBlocks) {
        $content = [regex]::Replace($content, '```[\s\S]*?```', '')
    }

    $matches = [regex]::Matches($content, '\[[^\]]+\]\(([^)]+)\)')

    foreach ($match in $matches) {
        $link = $match.Groups[1].Value.Trim()

        if ($link -match '^(https?:|mailto:|#|data:)') {
            continue
        }

        $targetPath = ($link.Split('#')[0]).Trim()

        if ([string]::IsNullOrWhiteSpace($targetPath)) {
            continue
        }

        $decodedTargetPath = [System.Uri]::UnescapeDataString($targetPath)
        $resolvedPath = Join-Path -Path $file.DirectoryName -ChildPath $decodedTargetPath

        if (-not (Test-Path -LiteralPath $resolvedPath)) {
            $relativeFile = Resolve-Path -Relative -Path $file.FullName
            $brokenLinks += [PSCustomObject]@{
                File = $relativeFile
                Link = $link
            }
        }
    }
}

if ($brokenLinks.Count -eq 0) {
    Write-Host "No broken local Markdown links found in '$rootPath'." -ForegroundColor Green
    exit 0
}

Write-Host "Broken local Markdown links found:" -ForegroundColor Red
$brokenLinks | Sort-Object File, Link | Format-Table -AutoSize
exit 1
