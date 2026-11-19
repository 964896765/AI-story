param([switch]$List)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
Add-Type -AssemblyName System.Speech
$reader = New-Object System.Speech.Synthesis.SpeechSynthesizer
try {
    $knownVoices = @{
        'Microsoft Huihui Desktop' = 'zh-CN'
        'Microsoft Zira Desktop' = 'en-US'
    }
    $voices = @($reader.GetInstalledVoices() | Where-Object {
        $_.Enabled -and $knownVoices[$_.VoiceInfo.Name] -eq $_.VoiceInfo.Culture.Name
    } | ForEach-Object {
        @{ name = $_.VoiceInfo.Name; locale = $_.VoiceInfo.Culture.Name }
    })
    if ($List) {
        ConvertTo-Json -InputObject $voices -Compress
        return
    }
    $config = [System.IO.File]::ReadAllText((Join-Path $PWD.Path 'dialogue-input.json'), [Text.Encoding]::UTF8) | ConvertFrom-Json
    $format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(
        48000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono
    )
    $number = 0
    foreach ($line in $config.lines) {
        if (-not ($voices | Where-Object { $_.name -eq $line.voice })) { throw 'Installed offline voice unavailable' }
        $number += 1
        $reader.SelectVoice([string]$line.voice)
        $reader.Rate = [int]$line.rate
        $reader.Volume = 85
        $reader.SetOutputToWaveFile((Join-Path $PWD.Path ('line-{0:000}.wav' -f $number)), $format)
        $reader.Speak([string]$line.text)
        $reader.SetOutputToNull()
    }
} finally {
    $reader.Dispose()
}
