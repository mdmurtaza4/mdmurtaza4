# ELiXIR AI Video Studio - hardware and software check (read-only; changes nothing)
# Run in PowerShell:  powershell -ExecutionPolicy Bypass -File scripts\check-hardware.ps1
# Paste the summary it prints back to Claude to finalise the GPU configuration.

$ErrorActionPreference = "SilentlyContinue"
function Line($label, $value) { "{0,-22} {1}" -f $label, $value }

"=== ELiXIR AI Video Studio: system report ==="
$os  = Get-CimInstance Win32_OperatingSystem
$cpu = Get-CimInstance Win32_Processor | Select-Object -First 1
Line "Windows" "$($os.Caption) (build $($os.BuildNumber))"
Line "CPU" "$($cpu.Name.Trim()) - $($cpu.NumberOfCores) cores / $($cpu.NumberOfLogicalProcessors) threads"
Line "RAM" ("{0:N1} GB total, {1:N1} GB free" -f ($os.TotalVisibleMemorySize/1MB), ($os.FreePhysicalMemory/1MB))

Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Used -ne $null } | ForEach-Object {
    Line "Drive $($_.Name):" ("{0:N0} GB free of {1:N0} GB" -f ($_.Free/1GB), (($_.Used+$_.Free)/1GB))
}
Get-PhysicalDisk | ForEach-Object { Line "Disk" "$($_.FriendlyName) - $($_.MediaType)" }

"`n--- GPU ---"
if (Get-Command nvidia-smi) {
    nvidia-smi --query-gpu=name,memory.total,memory.free,driver_version --format=csv,noheader
    (nvidia-smi | Select-String "CUDA Version").Line.Trim()
} else {
    "nvidia-smi not found: install the latest NVIDIA Studio or Game Ready driver."
    Get-CimInstance Win32_VideoController | ForEach-Object { Line "Display adapter" $_.Name }
}

"`n--- Tools ---"
foreach ($t in "python","py","node","npm","git","ffmpeg","ffprobe") {
    $c = Get-Command $t
    if ($c) {
        $v = & $t --version 2>&1 | Select-Object -First 1
        if ($t -in "ffmpeg","ffprobe") { $v = & $t -version 2>&1 | Select-Object -First 1 }
        Line $t $v
    } else { Line $t "NOT FOUND" }
}
if (Get-Command py) { Line "Python 3.11" ((py -3.11 --version 2>&1) -join "") }

"`n--- Encoders (real test encode, not just the list) ---"
if (Get-Command ffmpeg) {
    foreach ($enc in "h264_nvenc","hevc_nvenc","av1_nvenc","libx264") {
        & ffmpeg -hide_banner -loglevel error -f lavfi -i testsrc2=size=256x256:rate=30:duration=0.2 -c:v $enc -f null - 2>$null
        Line $enc ($(if ($LASTEXITCODE -eq 0) { "WORKS" } else { "not available" }))
    }
}
"`n=== End of report ==="
