param(
    [Parameter(Mandatory = $true)]
    [string]$Token,

    [string]$Owner = "Pawan8010",
    [string]$Repo = "tender_Project",
    [string]$Branch = "",
    [string]$CommitMessage = "Deploy Streamlit tender scraper project"
)

$ErrorActionPreference = "Stop"

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Headers = @{
    Authorization          = "Bearer $Token"
    Accept                 = "application/vnd.github+json"
    "X-GitHub-Api-Version" = "2022-11-28"
    "User-Agent"           = "tender-project-uploader"
}

function Invoke-GitHubJson {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Method,
        [Parameter(Mandatory = $true)]
        [string]$Uri,
        [object]$Body = $null
    )

    if ($null -eq $Body) {
        return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $Headers
    }

    $Json = $Body | ConvertTo-Json -Depth 10
    return Invoke-RestMethod -Method $Method -Uri $Uri -Headers $Headers -Body $Json -ContentType "application/json"
}

function Get-ExistingSha {
    param([string]$PathInRepo)

    $EscapedPath = ($PathInRepo -replace "\\", "/")
    $Uri = "https://api.github.com/repos/$Owner/$Repo/contents/$EscapedPath" + "?ref=$Branch"
    try {
        $Existing = Invoke-GitHubJson -Method "GET" -Uri $Uri
        return $Existing.sha
    }
    catch {
        if ($_.Exception.Response -and [int]$_.Exception.Response.StatusCode -eq 404) {
            return $null
        }
        throw
    }
}

$RepoInfo = Invoke-GitHubJson -Method "GET" -Uri "https://api.github.com/repos/$Owner/$Repo"
if ([string]::IsNullOrWhiteSpace($Branch)) {
    $Branch = $RepoInfo.default_branch
}

$Files = @(
    "tender_scraper_system.py",
    "tender_scraper_ui.py",
    "requirements.txt",
    "packages.txt",
    "runtime.txt",
    "README_DEPLOY.md",
    ".streamlit/config.toml",
    "realtime_all_pages_tenders.csv"
)

foreach ($File in $Files) {
    $LocalPath = Join-Path $Root $File
    if (-not (Test-Path $LocalPath)) {
        Write-Warning "Skipping missing file: $File"
        continue
    }

    $Bytes = [System.IO.File]::ReadAllBytes($LocalPath)
    $Base64 = [System.Convert]::ToBase64String($Bytes)
    $Sha = Get-ExistingSha -PathInRepo $File

    $Body = @{
        message = "$CommitMessage`: $File"
        content = $Base64
        branch  = $Branch
    }
    if ($Sha) {
        $Body.sha = $Sha
    }

    $PathForUri = ($File -replace "\\", "/")
    $Uri = "https://api.github.com/repos/$Owner/$Repo/contents/$PathForUri"
    Invoke-GitHubJson -Method "PUT" -Uri $Uri -Body $Body | Out-Null
    Write-Host "Uploaded $File to $Owner/$Repo on branch $Branch"
}

Write-Host ""
Write-Host "Done: https://github.com/$Owner/$Repo"
