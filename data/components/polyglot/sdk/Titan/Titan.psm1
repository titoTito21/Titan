# Titan for PowerShell - the Polyglot line protocol.
#   Import-Module Titan        (the SDK folder is on PSModulePath)
#   Invoke-Titan speak 'Hello'
#   $name = Invoke-Titan ask 'Your name?'
#   $i = Invoke-Titan choose 'Pick one' @('Tea','Coffee')   # from 0, or $null

$script:TitanId = 0
$script:TitanIn = New-Object System.IO.StreamReader(
    [Console]::OpenStandardInput(), (New-Object System.Text.UTF8Encoding($false)))
$script:TitanOut = New-Object System.IO.StreamWriter(
    [Console]::OpenStandardOutput(), (New-Object System.Text.UTF8Encoding($false)))
$script:TitanOut.AutoFlush = $true

function Invoke-Titan {
    param([Parameter(Mandatory = $true, Position = 0)][string]$Call,
          [Parameter(ValueFromRemainingArguments = $true)]$Arguments)
    $script:TitanId++
    $list = @()
    if ($null -ne $Arguments) { $list = @($Arguments) }
    $payload = @{ id = $script:TitanId; call = $Call; args = $list } |
        ConvertTo-Json -Compress -Depth 10
    $script:TitanOut.WriteLine($payload)
    while ($true) {
        $line = $script:TitanIn.ReadLine()
        if ($null -eq $line) { throw 'Titan has gone' }
        if (-not $line.StartsWith('{')) { continue }
        $reply = $line | ConvertFrom-Json
        if ($reply.id -ne $script:TitanId) { continue }
        if (-not $reply.ok) { throw $reply.error }
        return $reply.value
    }
}

Export-ModuleMember -Function Invoke-Titan
