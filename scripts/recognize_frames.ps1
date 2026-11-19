[CmdletBinding(DefaultParameterSetName='Scan')]
param(
    [Parameter(Mandatory, ParameterSetName='List')][switch]$List,
    [Parameter(Mandatory, ParameterSetName='Scan')][string]$FrameDirectory,
    [Parameter(Mandatory, ParameterSetName='Scan')][string]$Language
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
$engineType = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
if ($List) {
    $languages = @($engineType::AvailableRecognizerLanguages | ForEach-Object { $_.LanguageTag } | Sort-Object)
    ConvertTo-Json -InputObject $languages -Compress
    return
}

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethodDefinition -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1

function Complete-Operation($operation, [type]$resultType) {
    $task = $asTask.MakeGenericMethod($resultType).Invoke($null, @($operation))
    return $task.GetAwaiter().GetResult()
}

$languageType = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]
$engine = $engineType::TryCreateFromLanguage($languageType::new($Language))
if ($null -eq $engine -or $engine.RecognizerLanguage.LanguageTag -ne $Language) { throw 'Requested Windows OCR recognizer is unavailable.' }
$decoderType = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$bitmapType = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$resultType = [Windows.Media.Ocr.OcrResult, Windows.Foundation, ContentType=WindowsRuntime]
$frames = @(Get-ChildItem -LiteralPath $FrameDirectory -File -Filter 'frame-*.jpg' | Sort-Object Name)
$results = foreach ($frame in $frames) {
    $file = [IO.File]::OpenRead($frame.FullName)
    try {
        $stream = [System.IO.WindowsRuntimeStreamExtensions]::AsRandomAccessStream($file)
        $decoder = Complete-Operation ($decoderType::CreateAsync($stream)) $decoderType
        $bitmap = Complete-Operation ($decoder.GetSoftwareBitmapAsync()) $bitmapType
        try {
            $recognition = Complete-Operation ($engine.RecognizeAsync($bitmap)) $resultType
            @{ name=$frame.Name; text=[string]$recognition.Text; lines=@($recognition.Lines | ForEach-Object {[string]$_.Text}) }
        } finally { $bitmap.Dispose() }
    } finally { $file.Dispose() }
}
ConvertTo-Json -InputObject @($results) -Compress
