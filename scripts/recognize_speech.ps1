[CmdletBinding(DefaultParameterSetName='Transcribe')]
param(
    [Parameter(Mandatory, ParameterSetName='List')][switch]$List,
    [Parameter(Mandatory, ParameterSetName='Transcribe')][string]$InputWave,
    [Parameter(Mandatory, ParameterSetName='Transcribe')][string]$Recognizer
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Speech
$engine = [System.Speech.Recognition.SpeechRecognitionEngine]
$installed = @($engine::InstalledRecognizers() | Where-Object {
    $_.Id -match '^MS-[0-9]+-[0-9]+-DESK$' -and $_.AdditionalInfo['Vendor'] -eq 'Microsoft'
} | Sort-Object Id)
if ($List) {
    $items = @($installed | ForEach-Object { @{ id=$_.Id; language=$_.Culture.Name } })
    ConvertTo-Json -InputObject $items -Compress
    return
}

if (-not ($installed | Where-Object Id -CEQ $Recognizer)) { throw 'Requested offline Windows recognizer is unavailable.' }
$wavePath = (Resolve-Path -LiteralPath $InputWave).ProviderPath
Add-Type -ReferencedAssemblies @('System.dll',$engine.Assembly.Location) -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Speech.Recognition;
using System.Threading;

public static class LocalSpeechCapture {
    public sealed class Segment {
        public long start_us { get; set; }
        public long end_us { get; set; }
        public string text { get; set; }
        public float confidence { get; set; }
    }

    public static Segment[] Transcribe(string recognizer, string wavePath) {
        using (var engine = new SpeechRecognitionEngine(recognizer))
        using (var done = new ManualResetEvent(false)) {
            var segments = new List<Segment>();
            RecognizeCompletedEventArgs result = null;
            engine.LoadGrammar(new DictationGrammar());
            engine.SetInputToWaveFile(wavePath);
            engine.SpeechRecognized += (sender, args) => {
                var audio = args.Result.Audio;
                if (audio == null) return;
                long start = audio.AudioPosition.Ticks;
                lock (segments) {
                    segments.Add(new Segment {
                        start_us = start / 10,
                        end_us = (start + audio.Duration.Ticks) / 10,
                        text = args.Result.Text,
                        confidence = args.Result.Confidence
                    });
                }
            };
            engine.RecognizeCompleted += (sender, args) => {
                result = args;
                done.Set();
            };
            engine.RecognizeAsync(RecognizeMode.Multiple);
            done.WaitOne();
            if (result.Error != null) throw new InvalidOperationException("Windows speech recognition failed.", result.Error);
            if (result.Cancelled) throw new InvalidOperationException("Windows speech recognition was cancelled.");
            lock (segments) return segments.ToArray();
        }
    }
}
'@
$segments = [LocalSpeechCapture]::Transcribe($Recognizer,$wavePath)
ConvertTo-Json -InputObject @($segments) -Compress
