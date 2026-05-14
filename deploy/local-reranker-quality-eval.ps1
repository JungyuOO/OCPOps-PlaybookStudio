param(
    [string]$RerankerBaseUrl = "http://127.0.0.1:8081",
    [string]$Cases = "corpus/manifests/eval/pbs_chat_quality_v012_beginner_cases.jsonl",
    [int]$TopK = 5,
    [int]$CandidateK = 24,
    [int]$MaxContextChunks = 8,
    [string]$DatabaseUrl = "",
    [switch]$SkipSmoke,
    [switch]$SmokeOnly
)

$ErrorActionPreference = "Stop"
chcp 65001 > $null
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$OutputEncoding = [System.Text.UTF8Encoding]::new($false)

$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $root

$env:RERANKER_ENABLED = "true"
$env:RERANKER_BASE_URL = $RerankerBaseUrl.TrimEnd("/")
$env:RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
$env:RERANKER_TOP_N = "4"
$env:RERANKER_BATCH_SIZE = "1"
$env:RERANKER_MAX_PARALLEL_REQUESTS = "4"
$env:RERANKER_TIMEOUT_SECONDS = "20"

Write-Host "RERANKER_BASE_URL=$env:RERANKER_BASE_URL"
Write-Host "RERANKER_MODEL=$env:RERANKER_MODEL"
Write-Host "RERANKER_TOP_N=$env:RERANKER_TOP_N"
Write-Host "RERANKER_BATCH_SIZE=$env:RERANKER_BATCH_SIZE"
Write-Host "RERANKER_MAX_PARALLEL_REQUESTS=$env:RERANKER_MAX_PARALLEL_REQUESTS"

if (-not $SkipSmoke) {
    $body = @{
        query = "Route timeout 어디서 확인해?"
        texts = @(
            "OpenShift Route timeout is configured on HAProxy router annotations.",
            "HSTS policy configures strict transport security for routes."
        )
        raw_scores = $true
        return_text = $false
        truncate = $true
    } | ConvertTo-Json -Depth 5

    Write-Host "Running reranker smoke..."
    $response = Invoke-RestMethod `
        -Uri "$env:RERANKER_BASE_URL/rerank" `
        -Method Post `
        -ContentType "application/json" `
        -Body $body `
        -TimeoutSec 60
    $response | ConvertTo-Json -Depth 10
}

if ($SmokeOnly) {
    exit 0
}

$argsList = @(
    "-m", "play_book_studio.cli",
    "eval",
    "--cases", $Cases,
    "--top-k", "$TopK",
    "--candidate-k", "$CandidateK",
    "--max-context-chunks", "$MaxContextChunks"
)

if ($DatabaseUrl.Trim()) {
    $argsList += @("--database-url", $DatabaseUrl)
}

Write-Host "Running answer quality eval..."
python @argsList
