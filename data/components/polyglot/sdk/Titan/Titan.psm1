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

# A function of this program Titan may keep and call later.
function New-TitanFunction([string]$Name) { return @{ __function = $Name } }

# Every add-on Titan CALLS ends with this: the functions it may call, by the
# same names a Python add-on of that kind defines.
#   Start-TitanServe @{ get_statusbar_item_text = { (Get-Date).ToString('HH:mm') } }
function Start-TitanServe {
    param([Parameter(Mandatory = $true)][hashtable]$Handlers)
    Invoke-Titan provide @(,[string[]]$Handlers.Keys) | Out-Null
    while ($true) {
        $event = Invoke-Titan next_event -1
        if ($null -eq $event) { continue }
        if ($event.type -eq 'close') { return }
        if ($event.type -ne 'call') { continue }
        $handler = $Handlers[$event.name]
        try {
            $value = $null
            # Splatted, so each argument is a parameter of the handler.
            $arguments = @($event.args)
            if ($null -ne $handler) { $value = & $handler @arguments }
            Invoke-Titan reply $event.id $value | Out-Null
        } catch {
            Invoke-Titan reply $event.id $null $_.Exception.Message | Out-Null
        }
    }
}

Export-ModuleMember -Function Invoke-Titan, New-TitanFunction, Start-TitanServe
