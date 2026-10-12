' Speak each line of a term_bench corpus to a 16 kHz mono WAV with the
' Windows SAPI voices (offline). Run by tools\term_bench.py; not shipped.
'   cscript //nologo tools\tts_sapi.vbs <corpus.tsv (UTF-16)> <out dir>
' Each line: id <TAB> voice <TAB> rate <TAB> text
Option Explicit
Dim fso, src, outDir, voice, fmt, stream, line, parts, wav, v, i, names
Set fso = CreateObject("Scripting.FileSystemObject")
outDir = WScript.Arguments(1)
If Not fso.FolderExists(outDir) Then fso.CreateFolder outDir
Set voice = CreateObject("SAPI.SpVoice")
names = ""
For i = 0 To voice.GetVoices().Count - 1
    names = names & voice.GetVoices().Item(i).GetDescription() & "; "
Next
Set src = fso.OpenTextFile(WScript.Arguments(0), 1, False, -1)
Do While Not src.AtEndOfStream
    line = src.ReadLine
    parts = Split(line, vbTab)
    If UBound(parts) >= 3 Then
        wav = fso.BuildPath(outDir, parts(0) & ".wav")
        If Not fso.FileExists(wav) Then
            For i = 0 To voice.GetVoices().Count - 1
                Set v = voice.GetVoices().Item(i)
                If InStr(1, v.GetDescription(), parts(1), vbTextCompare) > 0 Then
                    Set voice.Voice = v
                    Exit For
                End If
            Next
            voice.Rate = CInt(parts(2))
            Set fmt = CreateObject("SAPI.SpAudioFormat")
            fmt.Type = 18  ' SAFT16kHz16BitMono
            Set stream = CreateObject("SAPI.SpFileStream")
            Set stream.Format = fmt
            stream.Open wav, 3, False
            Set voice.AudioOutputStream = stream
            voice.Speak parts(3)
            stream.Close
        End If
    End If
Loop
src.Close
WScript.Echo "voices: " & names
